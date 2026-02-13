from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
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
    logging.raiseExceptions = False
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
DRIVE_SHARE_TOOL_NAMES = {"create_drive_shared_link_to_user", "create_drive_public_link"}
URL_PATTERN = re.compile(r"https?://[^\s<>()\"']+")
OPENAI_API_TIMEOUT_SECONDS = 120.0
MAX_TOOL_CONTENT_CHARS = 5000
GEMINI_TRANSIENT_ERROR_CODES = {500, 502, 503, 504}
GEMINI_MAX_RETRIES = 3
GEMINI_RETRY_BASE_DELAY_SECONDS = 1.0
EXPLICIT_DATE_PATTERN = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b"
)
TIME_PATTERN = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")
HOUR_ONLY_PATTERN = re.compile(r"\b(?:jam|pukul|at)\s*([01]?\d|2[0-3])\b", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
INVITE_KEYWORDS = ("invite", "invitation", "undang", "undangan")


def get_servers_config() -> list[ServerConfig]:
    return [
        ServerConfig(name="gmail", script="gmail_server.py"),
        ServerConfig(name="calendar", script="calendar_server.py"),
        ServerConfig(name="contacts", script="contacts_server.py"),
        ServerConfig(name="drive", script="drive_server.py"),
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
    return (
        lowered.startswith("error:")
        or lowered.startswith("search failed:")
        or lowered.startswith("fetch failed:")
        or lowered.startswith("drive api request failed:")
    )


def _extract_urls(text: str) -> list[str]:
    if not text:
        return []
    urls = []
    for raw_url in URL_PATTERN.findall(text):
        cleaned = raw_url.rstrip(".,;:)]}")
        if cleaned:
            urls.append(cleaned)
    return urls


def _append_share_links_if_missing(assistant_text: str, share_urls: list[str]) -> str:
    if not share_urls:
        return assistant_text

    current_text = assistant_text or ""
    existing_urls = set(_extract_urls(current_text))
    missing_urls = [url for url in share_urls if url not in existing_urls]
    if not missing_urls:
        return current_text

    links_block = "Shared URL(s):\n" + "\n".join([f"- {url}" for url in missing_urls])
    if current_text.strip():
        return current_text.rstrip() + "\n\n" + links_block
    return links_block


def _truncate_tool_content_for_model(text: str, limit: int = MAX_TOOL_CONTENT_CHARS) -> str:
    normalized = normalize_content_text(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "\n\n[Truncated for model context]"


def _with_runtime_time_context(system_instruction: str) -> str:
    now = datetime.now()
    return (
        f"{system_instruction} "
        f"Current local date: {now:%Y-%m-%d}. "
        f"Current local time: {now:%H:%M}. "
        "Interpret relative date words (today, tomorrow, yesterday, hari ini, besok, kemarin, lusa) "
        "using this date, and do not ask the user to confirm current date."
    )


def _detect_relative_day_offset(text: str) -> int | None:
    lowered = text.lower()
    if "day after tomorrow" in lowered or "lusa" in lowered:
        return 2
    if "tomorrow" in lowered or "besok" in lowered:
        return 1
    if "today" in lowered or "hari ini" in lowered:
        return 0
    if "yesterday" in lowered or "kemarin" in lowered:
        return -1
    return None


def _extract_hhmm(value: str) -> str | None:
    if not value:
        return None
    match = TIME_PATTERN.search(value)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        return f"{hour:02d}:{minute:02d}"
    hour_only = HOUR_ONLY_PATTERN.search(value)
    if hour_only:
        return f"{int(hour_only.group(1)):02d}:00"
    return None


def _normalize_add_event_args_from_message(
    tool_args: dict[str, Any], user_message: str, now: datetime | None = None
) -> dict[str, Any]:
    if not isinstance(tool_args, dict):
        return tool_args
    if "start_time" not in tool_args:
        return tool_args

    text = normalize_content_text(user_message)
    if EXPLICIT_DATE_PATTERN.search(text):
        return tool_args

    offset = _detect_relative_day_offset(text)
    if offset is None:
        return tool_args

    current = now or datetime.now()
    target_date = current + timedelta(days=offset)
    start_value = normalize_content_text(tool_args.get("start_time"))
    hhmm = _extract_hhmm(text) or _extract_hhmm(start_value)
    if not hhmm:
        return tool_args

    normalized = dict(tool_args)
    normalized["start_time"] = f"{target_date:%Y-%m-%d} {hhmm}"
    return normalized


def _extract_invite_emails(text: str) -> list[str]:
    candidates = EMAIL_PATTERN.findall(text or "")
    unique: list[str] = []
    seen = set()
    for email in candidates:
        lowered = email.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique.append(email)
    return unique


def _has_invite_intent(text: str) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in INVITE_KEYWORDS)


def _build_invitation_email_payload(
    event_args: dict[str, Any], to_email: str
) -> dict[str, str]:
    summary = normalize_content_text(event_args.get("summary")) or "Calendar Event"
    start_time = normalize_content_text(event_args.get("start_time")) or "-"
    duration = event_args.get("duration_minutes", 60)
    description = normalize_content_text(event_args.get("description"))
    subject = f"Invitation: {summary}"
    body_parts = [
        "Hello,",
        "",
        "You are invited to this event:",
        f"- Event: {summary}",
        f"- Time: {start_time}",
        f"- Duration: {duration} minutes",
    ]
    if description:
        body_parts.extend(["", "Details:", description])
    body_parts.extend(["", "Best regards,"])
    return {
        "to_email": to_email,
        "subject": subject,
        "body": "\n".join(body_parts),
    }


def _extract_event_location(event_args: dict[str, Any]) -> str:
    description = normalize_content_text(event_args.get("description"))
    if not description:
        return ""
    for line in description.splitlines():
        lowered = line.lower().strip()
        if lowered.startswith("lokasi:") or lowered.startswith("location:"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                return parts[1].strip()
    return ""


def _build_calendar_invitation_email_payload(
    event_args: dict[str, Any], to_email: str
) -> dict[str, Any]:
    summary = normalize_content_text(event_args.get("summary")) or "Calendar Event"
    start_time = normalize_content_text(event_args.get("start_time")) or ""
    duration = event_args.get("duration_minutes", 60)
    description = normalize_content_text(event_args.get("description"))
    location = _extract_event_location(event_args)
    body = (
        "Hello,\n\n"
        "Please see the calendar invitation attached/included in this email. "
        "You can accept or decline the invitation from your calendar client.\n"
    )
    if description:
        body += f"\nDetails:\n{description}\n"
    return {
        "to_email": to_email,
        "subject": f"Invitation: {summary}",
        "body": body,
        "summary": summary,
        "start_time": start_time,
        "duration_minutes": duration,
        "description": description,
        "location": location,
    }


async def _generate_gemini_with_retry(aclient, model_name, gemini_contents, gemini_config, request_id):
    last_exception = None
    for attempt in range(1, GEMINI_MAX_RETRIES + 1):
        try:
            return await aclient.models.generate_content(
                model=model_name,
                contents=gemini_contents,
                config=gemini_config,
            )
        except Exception as exc:
            last_exception = exc
            code = getattr(exc, "code", None)
            is_transient = (
                genai_errors is not None
                and isinstance(exc, genai_errors.APIError)
                and code in GEMINI_TRANSIENT_ERROR_CODES
            )
            if not is_transient or attempt >= GEMINI_MAX_RETRIES:
                raise

            delay = GEMINI_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "[%s] Gemini transient API error (%s), retry %d/%d in %.1fs",
                request_id,
                code,
                attempt,
                GEMINI_MAX_RETRIES,
                delay,
            )
            await asyncio.sleep(delay)

    raise last_exception  # pragma: no cover - defensive fallback


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
    share_urls: list[str] = []
    last_successful_tool_name: str | None = None
    last_successful_tool_content: str | None = None
    invite_requested = _has_invite_intent(normalized_message)
    invite_emails = _extract_invite_emails(normalized_message)
    last_added_event_args: dict[str, Any] | None = None
    auto_invites_attempted = False

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

            async def _maybe_auto_send_invites(current_response: str) -> str:
                nonlocal auto_invites_attempted, status, error_message
                nonlocal last_successful_tool_name, last_successful_tool_content
                if auto_invites_attempted:
                    return current_response
                auto_invites_attempted = True

                if not invite_requested or not invite_emails or not last_added_event_args:
                    return current_response
                if "send_email" in invoked_tools or "send_calendar_invite_email" in invoked_tools:
                    return current_response
                has_calendar_invite_tool = tool_to_session.get("send_calendar_invite_email") is not None
                has_plain_email_tool = tool_to_session.get("send_email") is not None
                if not has_calendar_invite_tool and not has_plain_email_tool:
                    return current_response

                result_lines: list[str] = []
                for to_email in invite_emails:
                    tool_name = (
                        "send_calendar_invite_email"
                        if has_calendar_invite_tool
                        else "send_email"
                    )
                    if tool_name == "send_calendar_invite_email":
                        payload = _build_calendar_invitation_email_payload(
                            last_added_event_args, to_email
                        )
                    else:
                        payload = _build_invitation_email_payload(last_added_event_args, to_email)

                    invoked_tools.append(tool_name)
                    invoked_servers.add(tool_to_server_name.get(tool_name, "gmail"))
                    logger.info(
                        "[%s] Auto-invoking tool=%s server=%s args=%s",
                        request_id,
                        tool_name,
                        tool_to_server_name.get(tool_name, "gmail"),
                        _summarize_for_log(payload),
                    )
                    started_at = time.perf_counter()
                    send_content = ""
                    try:
                        send_result = await tool_to_session[tool_name].call_tool(tool_name, payload)
                        send_content = _result_to_text(send_result)
                    except Exception as tool_exc:
                        send_content = f"Error: Tool '{tool_name}' failed with exception: {tool_exc}"
                        tool_error = f"{tool_name}: {tool_exc}"
                        tool_errors.append(tool_error)
                        status = "error_tool_execution"
                        error_message = tool_error
                        logger.error(
                            "[%s] Auto %s failed after %.3fs: %s",
                            request_id,
                            tool_name,
                            time.perf_counter() - started_at,
                            tool_exc,
                            exc_info=True,
                        )
                    else:
                        logger.info(
                            "[%s] Auto %s completed in %.3fs",
                            request_id,
                            tool_name,
                            time.perf_counter() - started_at,
                        )

                    if (
                        _looks_like_error_text(send_content)
                        and tool_name == "send_calendar_invite_email"
                        and has_plain_email_tool
                    ):
                        fallback_tool = "send_email"
                        fallback_payload = _build_invitation_email_payload(
                            last_added_event_args, to_email
                        )
                        invoked_tools.append(fallback_tool)
                        invoked_servers.add(tool_to_server_name.get(fallback_tool, "gmail"))
                        logger.info(
                            "[%s] Auto fallback tool=%s server=%s args=%s",
                            request_id,
                            fallback_tool,
                            tool_to_server_name.get(fallback_tool, "gmail"),
                            _summarize_for_log(fallback_payload),
                        )
                        started_at = time.perf_counter()
                        try:
                            fallback_result = await tool_to_session[fallback_tool].call_tool(
                                fallback_tool, fallback_payload
                            )
                            fallback_content = _result_to_text(fallback_result)
                        except Exception as tool_exc:
                            fallback_content = (
                                f"Error: Tool '{fallback_tool}' failed with exception: {tool_exc}"
                            )
                            tool_error = f"{fallback_tool}: {tool_exc}"
                            tool_errors.append(tool_error)
                            status = "error_tool_execution"
                            error_message = tool_error
                            logger.error(
                                "[%s] Auto fallback %s failed after %.3fs: %s",
                                request_id,
                                fallback_tool,
                                time.perf_counter() - started_at,
                                tool_exc,
                                exc_info=True,
                            )
                        else:
                            logger.info(
                                "[%s] Auto fallback %s completed in %.3fs",
                                request_id,
                                fallback_tool,
                                time.perf_counter() - started_at,
                            )
                        send_content = (
                            f"{send_content}\nFallback ({fallback_tool}): {fallback_content}"
                        )

                    if _looks_like_error_text(send_content):
                        tool_error = f"{tool_name}({to_email}): {send_content}"
                        tool_errors.append(tool_error)
                        if error_message is None:
                            error_message = tool_error
                        logger.warning(
                            "[%s] Auto invite returned error content: %s",
                            request_id,
                            _summarize_for_log(send_content),
                        )
                    else:
                        last_successful_tool_name = tool_name
                        last_successful_tool_content = send_content
                    result_lines.append(f"- {to_email}: {send_content}")

                if not result_lines:
                    return current_response

                block = "Invitation delivery result(s):\n" + "\n".join(result_lines)
                if current_response.strip():
                    return current_response.rstrip() + "\n\n" + block
                return block

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
                    system_instruction=_with_runtime_time_context(SYSTEM_INSTRUCTION),
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
                    max_tool_rounds = 6
                    max_total_tool_calls = 12
                    total_tool_calls = 0
                    consecutive_all_error_rounds = 0
                    async with genai.Client(api_key=google_gemini_api_key).aio as aclient:
                        while True:
                            if total_tool_calls >= max_total_tool_calls:
                                status = "error_tool_loop_limit"
                                full_response = (
                                    "Error: Tool call loop limit reached. "
                                    "Please retry with a more specific request."
                                )
                                error_message = full_response
                                current_history[-1]["content"] = full_response
                                yield current_history
                                return
                            response = await _generate_gemini_with_retry(
                                aclient=aclient,
                                model_name=model_name,
                                gemini_contents=gemini_contents,
                                gemini_config=gemini_config,
                                request_id=request_id,
                            )

                            function_calls = getattr(response, "function_calls", None) or []
                            if not function_calls:
                                full_response = _extract_gemini_text(response)
                                full_response = await _maybe_auto_send_invites(full_response)
                                full_response = _append_share_links_if_missing(
                                    full_response, share_urls
                                )
                                current_history[-1]["content"] = full_response
                                yield current_history
                                break
                            if len(function_calls) > max_tool_rounds:
                                status = "error_tool_round_limit"
                                full_response = (
                                    "Error: Too many tool calls requested in one round. "
                                    "Please retry with a narrower request."
                                )
                                error_message = full_response
                                current_history[-1]["content"] = full_response
                                yield current_history
                                return

                            candidates = getattr(response, "candidates", None) or []
                            if candidates:
                                model_content = getattr(candidates[0], "content", None)
                                if model_content is not None:
                                    gemini_contents.append(model_content)

                            tool_response_parts = []
                            round_error_count = 0
                            for function_call in function_calls:
                                total_tool_calls += 1
                                tool_name = function_call.name
                                tool_args = _to_plain_dict(getattr(function_call, "args", {}))
                                if tool_name == "add_event" and isinstance(tool_args, dict):
                                    tool_args = _normalize_add_event_args_from_message(
                                        tool_args, normalized_message
                                    )
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
                                    round_error_count += 1
                                    if error_message is None:
                                        error_message = tool_error
                                    logger.warning(
                                        "[%s] Tool %s returned error content: %s",
                                        request_id,
                                        tool_name,
                                        _summarize_for_log(tool_content),
                                    )
                                elif tool_name in DRIVE_SHARE_TOOL_NAMES:
                                    for url in _extract_urls(tool_content):
                                        if url not in share_urls:
                                            share_urls.append(url)
                                if not _looks_like_error_text(tool_content):
                                    if tool_name == "add_event" and isinstance(tool_args, dict):
                                        last_added_event_args = dict(tool_args)
                                    last_successful_tool_name = tool_name
                                    last_successful_tool_content = tool_content
                                logger.debug(
                                    "[%s] Tool %s output: %s",
                                    request_id,
                                    tool_name,
                                    _summarize_for_log(tool_content, limit=300),
                                )
                                tool_response_parts.append(
                                    genai_types.Part.from_function_response(
                                        name=tool_name,
                                        response={
                                            "result": _truncate_tool_content_for_model(
                                                tool_content
                                            )
                                        },
                                    )
                                )

                            if round_error_count == len(function_calls):
                                consecutive_all_error_rounds += 1
                            else:
                                consecutive_all_error_rounds = 0
                            if consecutive_all_error_rounds >= 2:
                                status = "error_tool_repeated_failures"
                                full_response = (
                                    "Error: Tool execution failed repeatedly. "
                                    "Please check token permissions or provide the exact file ID."
                                )
                                if not error_message and tool_errors:
                                    error_message = "; ".join(tool_errors[-3:])
                                current_history[-1]["content"] = full_response
                                yield current_history
                                return

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
                        if code in GEMINI_TRANSIENT_ERROR_CODES:
                            full_response = (
                                "Error: Gemini API is temporarily unavailable "
                                f"({code}) after retries. Please retry."
                            )
                        else:
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

                api_messages = [
                    {
                        "role": "system",
                        "content": _with_runtime_time_context(OPENAI_SYSTEM_INSTRUCTION),
                    }
                ]
                api_messages.extend(validated_history)
                api_messages.append({"role": "user", "content": normalized_message})

                async with httpx.AsyncClient() as client:
                    max_tool_rounds = 8
                    consecutive_all_error_rounds = 0
                    for _ in range(max_tool_rounds):
                        try:
                            completion_response = await client.post(
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
                                timeout=OPENAI_API_TIMEOUT_SECONDS,
                            )
                        except httpx.TimeoutException:
                            if last_successful_tool_name and last_successful_tool_content:
                                status = "error_http_timeout_after_tool"
                                full_response = (
                                    "Warning: Model API response timed out after tool execution. "
                                    "Last successful tool result:\n\n"
                                    f"{last_successful_tool_content}"
                                )
                                full_response = await _maybe_auto_send_invites(full_response)
                            else:
                                status = "error_http_timeout"
                                full_response = (
                                    "Error: Model API request timed out. "
                                    "Please retry or narrow the request scope."
                                )
                            error_message = full_response
                            current_history[-1]["content"] = full_response
                            yield current_history
                            return

                        if completion_response.status_code != 200:
                            status = "error_http_status"
                            full_response = f"Error: {completion_response.status_code}"
                            error_message = full_response
                            current_history[-1]["content"] = full_response
                            yield current_history
                            return

                        completion_data = completion_response.json()
                        choices = completion_data.get("choices", [])
                        if not choices:
                            status = "error_http_response_shape"
                            full_response = "Error: Invalid response shape from model API."
                            error_message = full_response
                            current_history[-1]["content"] = full_response
                            yield current_history
                            return

                        assistant_msg = choices[0].get("message", {}) or {}
                        tool_calls = assistant_msg.get("tool_calls") or []
                        if not tool_calls:
                            full_response = normalize_content_text(assistant_msg.get("content", ""))
                            full_response = await _maybe_auto_send_invites(full_response)
                            full_response = _append_share_links_if_missing(
                                full_response, share_urls
                            )
                            current_history[-1]["content"] = full_response
                            yield current_history
                            break

                        api_messages.append(assistant_msg)
                        round_error_count = 0
                        for tool_call in tool_calls:
                            function_obj = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
                            tool_name = function_obj.get("name", "")
                            if not tool_name:
                                tool_error = "missing_tool_name: tool call payload malformed"
                                tool_errors.append(tool_error)
                                if error_message is None:
                                    error_message = tool_error
                                round_error_count += 1
                                logger.warning("[%s] %s", request_id, tool_error)
                                continue

                            raw_args = function_obj.get("arguments", "{}")
                            if isinstance(raw_args, str):
                                try:
                                    tool_args = json.loads(raw_args)
                                except json.JSONDecodeError:
                                    tool_args = {}
                            else:
                                tool_args = raw_args
                            if tool_name == "add_event" and isinstance(tool_args, dict):
                                tool_args = _normalize_add_event_args_from_message(
                                    tool_args, normalized_message
                                )

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
                                round_error_count += 1
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
                                round_error_count += 1
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
                                round_error_count += 1
                                logger.warning(
                                    "[%s] Tool %s returned error content: %s",
                                    request_id,
                                    tool_name,
                                    _summarize_for_log(tool_content),
                                )
                            elif tool_name in DRIVE_SHARE_TOOL_NAMES:
                                for url in _extract_urls(tool_content):
                                    if url not in share_urls:
                                        share_urls.append(url)
                            if not _looks_like_error_text(tool_content):
                                if tool_name == "add_event" and isinstance(tool_args, dict):
                                    last_added_event_args = dict(tool_args)
                                last_successful_tool_name = tool_name
                                last_successful_tool_content = tool_content
                            logger.debug(
                                "[%s] Tool %s output: %s",
                                request_id,
                                tool_name,
                                _summarize_for_log(tool_content, limit=300),
                            )
                            api_messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call.get("id", tool_name),
                                    "name": tool_name,
                                    "content": _truncate_tool_content_for_model(tool_content),
                                }
                            )

                        if round_error_count == len(tool_calls):
                            consecutive_all_error_rounds += 1
                        else:
                            consecutive_all_error_rounds = 0

                        if consecutive_all_error_rounds >= 2:
                            status = "error_tool_repeated_failures"
                            full_response = (
                                "Error: Tool execution failed repeatedly. "
                                "Please retry with a more specific request."
                            )
                            if not error_message and tool_errors:
                                error_message = "; ".join(tool_errors[-3:])
                            current_history[-1]["content"] = full_response
                            yield current_history
                            return
                    else:
                        status = "error_tool_round_limit"
                        full_response = (
                            "Error: Tool call loop limit reached. "
                            "Please retry with a more specific request."
                        )
                        error_message = full_response
                        current_history[-1]["content"] = full_response
                        yield current_history
                        return
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
