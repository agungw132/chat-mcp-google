from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from datetime import datetime
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from chat_google.constants import OPENAI_SYSTEM_INSTRUCTION, SYSTEM_INSTRUCTION
from chat_google.models import ChatMessage, MetricsRecord, RuntimeSettings, ServerConfig

try:
    import google.genai as genai
    from google.genai import errors as genai_errors
    from google.genai import types as genai_types
except Exception as genai_import_error:  # pragma: no cover - environment specific
    genai = None
    genai_errors = None
    genai_types = None


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


def _summarize_for_log(value: Any, limit: int = 200) -> str:
    text = normalize_content_text(value).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _looks_like_error_text(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered.startswith("error:") or lowered.startswith("search failed:") or lowered.startswith(
        "fetch failed:"
    )


def _history_role_to_gemini_role(role: str) -> str:
    if role == "assistant":
        return "model"
    return role


def _make_gemini_content(role: str, text: str) -> genai_types.Content:
    return genai_types.Content(
        role=_history_role_to_gemini_role(role),
        parts=[genai_types.Part.from_text(text=text)],
    )


def _to_plain_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    try:
        return dict(value)
    except Exception:
        return {}


def _extract_gemini_text(response) -> str:
    if getattr(response, "text", None):
        return response.text

    candidates = getattr(response, "candidates", None) or []
    text_parts = []
    for candidate in candidates:
        content_obj = getattr(candidate, "content", None)
        parts = getattr(content_obj, "parts", None) or []
        for part in parts:
            text = getattr(part, "text", None)
            if text:
                text_parts.append(text)
    return "".join(text_parts)


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
    gemini_function_declarations = []

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
                if genai_types is not None:
                    gemini_function_declarations.append(
                        genai_types.FunctionDeclaration(
                            name=tool.name,
                            description=tool.description,
                            parameters_json_schema=sanitize_schema_for_gemini(
                                tool.inputSchema
                            ),
                        )
                    )
        except Exception as exc:
            logger.error("Failed to start MCP server %s: %s", cfg.name, exc)

    return tool_to_session, tool_to_server_name, mcp_tools, gemini_function_declarations


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
    error_message = None
    tool_errors = []

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
                gemini_function_declarations,
            ) = await _collect_mcp_tools(stack, servers_config)
            full_response = ""

            if model_name.startswith("gemini"):
                if genai is None or genai_types is None:
                    status = "error_missing_gemini_sdk"
                    full_response = (
                        "Error: google-genai is not installed correctly. "
                        "Run `uv sync` or install `google-genai`."
                    )
                    error_message = full_response
                    current_history[-1]["content"] = full_response
                    yield current_history
                    return

                if not google_gemini_api_key:
                    status = "error_missing_gemini_key"
                    full_response = "Error: GOOGLE_GEMINI_API_KEY not found in .env"
                    error_message = full_response
                    current_history[-1]["content"] = full_response
                    yield current_history
                    return

                gemini_tool_config = (
                    [genai_types.Tool(function_declarations=gemini_function_declarations)]
                    if gemini_function_declarations
                    else None
                )
                gemini_config = genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    tools=gemini_tool_config,
                )

                gemini_contents = []
                for history_item in validated_history:
                    gemini_contents.append(
                        _make_gemini_content(
                            role=history_item["role"],
                            text=history_item["content"],
                        )
                    )
                gemini_contents.append(_make_gemini_content("user", normalized_message))

                try:
                    async with genai.Client(api_key=google_gemini_api_key).aio as aclient:
                        while True:
                            response = await aclient.models.generate_content(
                                model=model_name,
                                contents=gemini_contents,
                                config=gemini_config,
                            )

                            function_calls = getattr(response, "function_calls", None) or []
                            if not function_calls:
                                full_response = _extract_gemini_text(response)
                                current_history[-1]["content"] = full_response
                                yield current_history
                                break

                            candidates = getattr(response, "candidates", None) or []
                            if candidates:
                                model_content = getattr(candidates[0], "content", None)
                                if model_content is not None:
                                    gemini_contents.append(model_content)

                            tool_response_parts = []
                            for function_call in function_calls:
                                tool_name = function_call.name
                                tool_args = _to_plain_dict(getattr(function_call, "args", {}))
                                invoked_tools.append(tool_name)
                                server_name = tool_to_server_name.get(tool_name, "unknown")
                                invoked_servers.add(
                                    server_name
                                )
                                logger.info(
                                    "[%s] Invoking tool=%s server=%s args=%s",
                                    request_id,
                                    tool_name,
                                    server_name,
                                    _summarize_for_log(tool_args),
                                )

                                session = tool_to_session.get(tool_name)
                                if not session:
                                    status = "error_tool_session_not_found"
                                    full_response = (
                                        f"Error: Tool '{tool_name}' is not available from MCP session."
                                    )
                                    error_message = full_response
                                    tool_errors.append(f"{tool_name}: session not found")
                                    current_history[-1]["content"] = full_response
                                    yield current_history
                                    return

                                tool_started_at = time.perf_counter()
                                try:
                                    result = await session.call_tool(tool_name, tool_args)
                                    tool_content = _result_to_text(result)
                                except Exception as tool_exc:
                                    tool_content = (
                                        f"Error: Tool '{tool_name}' failed with exception: {tool_exc}"
                                    )
                                    tool_error = f"{tool_name}: {tool_exc}"
                                    tool_errors.append(tool_error)
                                    status = "error_tool_execution"
                                    error_message = tool_error
                                    logger.error(
                                        "[%s] Tool %s failed after %.3fs: %s",
                                        request_id,
                                        tool_name,
                                        time.perf_counter() - tool_started_at,
                                        tool_exc,
                                        exc_info=True,
                                    )
                                else:
                                    logger.info(
                                        "[%s] Tool %s completed in %.3fs",
                                        request_id,
                                        tool_name,
                                        time.perf_counter() - tool_started_at,
                                    )
                                if _looks_like_error_text(tool_content):
                                    tool_error = f"{tool_name}: {tool_content}"
                                    tool_errors.append(tool_error)
                                    if error_message is None:
                                        error_message = tool_error
                                    logger.warning(
                                        "[%s] Tool %s returned error content: %s",
                                        request_id,
                                        tool_name,
                                        _summarize_for_log(tool_content),
                                    )
                                logger.debug(
                                    "[%s] Tool %s output: %s",
                                    request_id,
                                    tool_name,
                                    _summarize_for_log(tool_content, limit=300),
                                )
                                tool_response_parts.append(
                                    genai_types.Part.from_function_response(
                                        name=tool_name,
                                        response={"result": tool_content},
                                    )
                                )

                            gemini_contents.append(
                                genai_types.Content(role="tool", parts=tool_response_parts)
                            )
                except Exception as exc:
                    if (
                        genai_errors is not None
                        and isinstance(exc, genai_errors.APIError)
                        and getattr(exc, "code", None) == 429
                    ):
                        status = "error_gemini_quota_exhausted"
                        full_response = "Error: Your Gemini API quota is exhausted."
                        error_message = full_response
                    else:
                        status = "error_gemini_api"
                        code = getattr(exc, "code", "unknown")
                        full_response = f"Error: Gemini API error ({code})."
                        error_message = full_response
                    current_history[-1]["content"] = full_response
                    yield current_history
                    return
            else:
                if not api_key:
                    status = "error_missing_api_key"
                    full_response = "Error: API_KEY not found in .env"
                    error_message = full_response
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
                        error_message = full_response
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
                            server_name = tool_to_server_name.get(tool_name, "unknown")
                            invoked_servers.add(server_name)
                            logger.info(
                                "[%s] Invoking tool=%s server=%s args=%s",
                                request_id,
                                tool_name,
                                server_name,
                                _summarize_for_log(tool_args),
                            )

                            session = tool_to_session.get(tool_name)
                            if not session:
                                tool_error = f"{tool_name}: session not found"
                                tool_errors.append(tool_error)
                                if error_message is None:
                                    error_message = tool_error
                                logger.warning("[%s] %s", request_id, tool_error)
                                continue

                            tool_started_at = time.perf_counter()
                            try:
                                result = await session.call_tool(tool_name, tool_args)
                                tool_content = _result_to_text(result)
                            except Exception as tool_exc:
                                tool_content = (
                                    f"Error: Tool '{tool_name}' failed with exception: {tool_exc}"
                                )
                                tool_error = f"{tool_name}: {tool_exc}"
                                tool_errors.append(tool_error)
                                status = "error_tool_execution"
                                error_message = tool_error
                                logger.error(
                                    "[%s] Tool %s failed after %.3fs: %s",
                                    request_id,
                                    tool_name,
                                    time.perf_counter() - tool_started_at,
                                    tool_exc,
                                    exc_info=True,
                                )
                            else:
                                logger.info(
                                    "[%s] Tool %s completed in %.3fs",
                                    request_id,
                                    tool_name,
                                    time.perf_counter() - tool_started_at,
                                )
                            if _looks_like_error_text(tool_content):
                                tool_error = f"{tool_name}: {tool_content}"
                                tool_errors.append(tool_error)
                                if error_message is None:
                                    error_message = tool_error
                                logger.warning(
                                    "[%s] Tool %s returned error content: %s",
                                    request_id,
                                    tool_name,
                                    _summarize_for_log(tool_content),
                                )
                            logger.debug(
                                "[%s] Tool %s output: %s",
                                request_id,
                                tool_name,
                                _summarize_for_log(tool_content, limit=300),
                            )
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
                                error_message = full_response
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
        error_message = str(exc)
        logger.error("Chat Error: %s", exc, exc_info=True)
        current_history[-1]["content"] = f"Error: {str(exc)}"
        yield current_history
    finally:
        if status == "success" and tool_errors:
            status = "success_with_tool_errors"
        if error_message is None and tool_errors:
            error_message = "; ".join(tool_errors)
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
                "error_message": error_message,
                "tool_errors": tool_errors,
            }
        )
