import contextlib
import json
import logging
import os
import time
from datetime import datetime
from typing import Any

import google.generativeai as genai
import httpx
from dotenv import load_dotenv
from google.ai.generativelanguage_v1beta.types import content
from google.api_core import exceptions as google_exceptions
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from chat_google.constants import OPENAI_SYSTEM_INSTRUCTION, SYSTEM_INSTRUCTION
from chat_google.models import ChatMessage, MetricsRecord, RuntimeSettings, ServerConfig


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("SumopodChat")
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    c_handler = logging.StreamHandler()
    f_handler = logging.FileHandler("chat_app.log")
    c_handler.setLevel(logging.INFO)
    f_handler.setLevel(logging.DEBUG)

    log_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"
    )
    c_handler.setFormatter(log_format)
    f_handler.setFormatter(log_format)

    logger.addHandler(c_handler)
    logger.addHandler(f_handler)
    return logger


logger = _build_logger()


def get_servers_config() -> list[ServerConfig]:
    return [
        ServerConfig(name="gmail", script="gmail_server.py"),
        ServerConfig(name="calendar", script="calendar_server.py"),
        ServerConfig(name="contacts", script="contacts_server.py"),
    ]


def sanitize_schema_for_gemini(schema):
    if isinstance(schema, dict):
        return {
            key: sanitize_schema_for_gemini(value)
            for key, value in schema.items()
            if key not in ("title", "default")
        }
    if isinstance(schema, list):
        return [sanitize_schema_for_gemini(item) for item in schema]
    return schema


def load_runtime_settings() -> RuntimeSettings:
    load_dotenv()
    return RuntimeSettings.model_validate(
        {
            "base_url": os.getenv("BASE_URL", "https://ai.sumopod.com"),
            "api_key": os.getenv("API_KEY"),
            "google_gemini_api_key": os.getenv("GOOGLE_GEMINI_API_KEY"),
        }
    )


def normalize_history(history) -> list[dict]:
    normalized = []
    for item in history:
        role = item.get("role", "user") if isinstance(item, dict) else "user"
        raw_content = item.get("content", "") if isinstance(item, dict) else item
        normalized.append(
            ChatMessage.model_validate(
                {"role": role, "content": normalize_content_text(raw_content)}
            ).model_dump()
        )
    return normalized


def normalize_content_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if "content" in value:
            return normalize_content_text(value.get("content"))
        if "value" in value:
            return normalize_content_text(value.get("value"))
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        parts = []
        for item in value:
            text = normalize_content_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    return str(value)


def log_metrics(metrics_data: dict, file_path: str = "metrics.jsonl") -> None:
    try:
        metrics_record = MetricsRecord.model_validate(metrics_data)
        with open(file_path, "a", encoding="utf-8") as metrics_file:
            metrics_file.write(metrics_record.model_dump_json() + "\n")
    except Exception as exc:  # pragma: no cover - log fallback
        logger.error("Failed to save metrics: %s", exc)


def _result_to_text(result) -> str:
    if not hasattr(result, "content"):
        return str(result)

    text_parts = []
    for item in result.content:
        if hasattr(item, "text"):
            text_parts.append(item.text)
        else:
            text_parts.append(str(item))
    return "".join(text_parts)


async def _collect_mcp_tools(stack, servers_config):
    tool_to_session = {}
    tool_to_server_name = {}
    mcp_tools = []
    gemini_tools = []

    for cfg in servers_config:
        try:
            server_params = StdioServerParameters(
                command="uv", args=["run", "python", cfg.script]
            )
            read, write = await stack.enter_async_context(stdio_client(server_params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            tools_resp = await session.list_tools()
            for tool in tools_resp.tools:
                tool_to_session[tool.name] = session
                tool_to_server_name[tool.name] = cfg.name
                mcp_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.inputSchema,
                        },
                    }
                )
                gemini_tools.append(
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": sanitize_schema_for_gemini(tool.inputSchema),
                    }
                )
        except Exception as exc:
            logger.error("Failed to start MCP server %s: %s", cfg.name, exc)

    return tool_to_session, tool_to_server_name, mcp_tools, gemini_tools


async def chat(message, history, model_name):
    normalized_message = normalize_content_text(message)
    if not normalized_message.strip():
        yield history
        return

    settings = load_runtime_settings()
    base_url = settings.base_url
    api_key = settings.api_key
    google_gemini_api_key = settings.google_gemini_api_key
    validated_history = normalize_history(history)

    start_time = time.time()
    request_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    invoked_tools = []
    invoked_servers = set()
    status = "success"

    logger.info("--- New Chat Request [%s] ---", request_id)

    servers_config = get_servers_config()
    current_history = validated_history + [
        {"role": "user", "content": normalized_message},
        {"role": "assistant", "content": ""},
    ]

    try:
        async with contextlib.AsyncExitStack() as stack:
            (
                tool_to_session,
                tool_to_server_name,
                mcp_tools,
                gemini_tools,
            ) = await _collect_mcp_tools(stack, servers_config)
            full_response = ""

            if model_name.startswith("gemini"):
                if not google_gemini_api_key:
                    status = "error_missing_gemini_key"
                    full_response = "Error: GOOGLE_GEMINI_API_KEY not found in .env"
                    current_history[-1]["content"] = full_response
                    yield current_history
                    return

                genai.configure(api_key=google_gemini_api_key)
                model = genai.GenerativeModel(
                    model_name,
                    tools=[{"function_declarations": gemini_tools}] if gemini_tools else None,
                    system_instruction=SYSTEM_INSTRUCTION,
                )
                chat_session = model.start_chat(history=[])

                for history_item in validated_history:
                    role = "user" if history_item["role"] == "user" else "model"
                    chat_session.history.append(
                        content.Content(
                            role=role,
                            parts=[content.Part(text=history_item["content"])],
                        )
                    )

                try:
                    response = await chat_session.send_message_async(normalized_message)
                except google_exceptions.ResourceExhausted:
                    status = "error_gemini_quota_exhausted"
                    full_response = "Error: Kuota API Gemini Anda habis."
                    current_history[-1]["content"] = full_response
                    yield current_history
                    return

                while True:
                    if not response.parts:
                        break

                    function_call = None
                    text_segments = []
                    for part in response.parts:
                        if getattr(part, "function_call", None) and function_call is None:
                            function_call = part.function_call
                        if getattr(part, "text", None):
                            text_segments.append(part.text)

                    if function_call:
                        tool_name = function_call.name
                        tool_args = dict(function_call.args)
                        invoked_tools.append(tool_name)
                        invoked_servers.add(tool_to_server_name.get(tool_name, "unknown"))

                        session = tool_to_session.get(tool_name)
                        if not session:
                            status = "error_tool_session_not_found"
                            full_response = (
                                f"Error: Tool '{tool_name}' tidak tersedia dari MCP session."
                            )
                            current_history[-1]["content"] = full_response
                            yield current_history
                            break

                        result = await session.call_tool(tool_name, tool_args)
                        tool_content = _result_to_text(result)
                        response = await chat_session.send_message_async(
                            content.Content(
                                parts=[
                                    content.Part(
                                        function_response=content.FunctionResponse(
                                            name=tool_name,
                                            response={"result": tool_content},
                                        )
                                    )
                                ]
                            )
                        )
                        continue

                    full_response += "".join(text_segments)
                    current_history[-1]["content"] = full_response
                    yield current_history
                    break
            else:
                if not api_key:
                    status = "error_missing_api_key"
                    full_response = "Error: API_KEY not found in .env"
                    current_history[-1]["content"] = full_response
                    yield current_history
                    return

                api_messages = [{"role": "system", "content": OPENAI_SYSTEM_INSTRUCTION}]
                api_messages.extend(validated_history)
                api_messages.append({"role": "user", "content": normalized_message})

                async with httpx.AsyncClient() as client:
                    first_response = await client.post(
                        f"{base_url.rstrip('/')}/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": model_name,
                            "messages": api_messages,
                            "tools": mcp_tools,
                            "tool_choice": "auto",
                        },
                        timeout=60.0,
                    )

                    if first_response.status_code != 200:
                        status = "error_http_status"
                        full_response = f"Error: {first_response.status_code}"
                        current_history[-1]["content"] = full_response
                        yield current_history
                        return

                    first_data = first_response.json()
                    assistant_msg = first_data["choices"][0]["message"]

                    if assistant_msg.get("tool_calls"):
                        api_messages.append(assistant_msg)
                        for tool_call in assistant_msg["tool_calls"]:
                            tool_name = tool_call["function"]["name"]
                            raw_args = tool_call["function"].get("arguments", "{}")
                            if isinstance(raw_args, str):
                                try:
                                    tool_args = json.loads(raw_args)
                                except json.JSONDecodeError:
                                    tool_args = {}
                            else:
                                tool_args = raw_args

                            invoked_tools.append(tool_name)
                            invoked_servers.add(tool_to_server_name.get(tool_name, "unknown"))

                            session = tool_to_session.get(tool_name)
                            if not session:
                                continue

                            result = await session.call_tool(tool_name, tool_args)
                            tool_content = _result_to_text(result)
                            api_messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call["id"],
                                    "name": tool_name,
                                    "content": tool_content,
                                }
                            )

                        async with client.stream(
                            "POST",
                            f"{base_url.rstrip('/')}/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "model": model_name,
                                "messages": api_messages,
                                "tools": mcp_tools,
                                "stream": True,
                            },
                            timeout=60.0,
                        ) as final_resp:
                            if final_resp.status_code != 200:
                                status = "error_http_stream_status"
                                full_response = f"Error: {final_resp.status_code}"
                                current_history[-1]["content"] = full_response
                                yield current_history
                                return

                            async for line in final_resp.aiter_lines():
                                if not line.startswith("data: "):
                                    continue

                                chunk_data = line[6:]
                                if chunk_data == "[DONE]":
                                    break

                                try:
                                    chunk = json.loads(chunk_data)
                                except json.JSONDecodeError:
                                    continue

                                if "choices" not in chunk or not chunk["choices"]:
                                    continue

                                delta = chunk["choices"][0].get("delta", {})
                                full_response += delta.get("content", "")
                                current_history[-1]["content"] = full_response
                                yield current_history
                    else:
                        full_response = assistant_msg.get("content", "")
                        current_history[-1]["content"] = full_response
                        yield current_history
    except Exception as exc:  # pragma: no cover - defensive fallback
        status = "error_exception"
        logger.error("Chat Error: %s", exc, exc_info=True)
        current_history[-1]["content"] = f"Kesalahan: {str(exc)}"
        yield current_history
    finally:
        duration = time.time() - start_time
        log_metrics(
            {
                "timestamp": datetime.now().isoformat(),
                "request_id": request_id,
                "model": model_name,
                "user_question": normalized_message,
                "duration_seconds": round(duration, 3),
                "invoked_tools": invoked_tools,
                "invoked_servers": sorted(invoked_servers),
                "status": status,
            }
        )
