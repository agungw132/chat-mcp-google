# Pseudocode - Chat Application

This document summarizes runtime behavior of:

- `app.py`
- `src/chat_google/ui.py`
- `src/chat_google/chat_service.py`
- supporting data models/constants used by orchestration

## 1) Bootstrap (`app.py`)

```text
SET PROJECT_ROOT = directory of current file
SET SRC_PATH = PROJECT_ROOT + "/src"
IF SRC_PATH not in sys.path:
    INSERT SRC_PATH at sys.path[0]

IMPORT main from chat_google.ui

IF executed as script:
    CALL main()
```

## 2) UI Layer (`src/chat_google/ui.py`)

## 2.1 `build_demo()`

```text
CREATE Gradio Blocks with title "Sumopod AI Chat"
RENDER heading: "Sumopod AI Chat (Gmail, Calendar, Contacts, Drive)"
CREATE chatbot component
CREATE textbox for user prompt + Retry button
CREATE model dropdown with AVAILABLE_MODELS, default DEFAULT_MODEL + Clear button
CREATE state variable `last_message`

DEFINE async user_submit(message, history):
    APPEND {"role":"user","content":message} to history
    RETURN cleared textbox, updated history, and last_message=message

DEFINE async bot_respond(history, model_name):
    user_msg = last history item content
    STREAM from chat(user_msg, history_without_latest_user, model_name)
    YIELD each updated history for live UI refresh

WIRE textbox submit:
    user_submit -> bot_respond

WIRE Retry click:
    put last_message back into textbox -> user_submit -> bot_respond

WIRE Clear click:
    reset chatbot history to []

RETURN demo
```

## 2.2 `main()`

```text
demo = build_demo()
demo.launch()
```

## 3) Configuration + Models

## 3.1 Constants (`src/chat_google/constants.py`)

```text
LOAD .env
DEFINE AVAILABLE_MODELS list (Gemini + OpenAI-compatible providers)
DEFINE fallback default model = "azure_ai/kimi-k2.5"

FUNCTION resolve_default_model():
    model_from_env = MODEL env var
    IF model_from_env exists AND in AVAILABLE_MODELS:
        RETURN model_from_env
    RETURN fallback

SET DEFAULT_MODEL = resolve_default_model()
DEFINE system instruction variants:
    - Gemini system instruction
    - OpenAI-compatible system instruction
```

## 3.2 Pydantic models (`src/chat_google/models.py`)

```text
ServerConfig:
    name in {"gmail","calendar","contacts","drive"}
    script non-empty string

RuntimeSettings:
    base_url, api_key, google_gemini_api_key

ChatMessage:
    role in {"system","user","assistant","tool","model"}
    content string

MetricsRecord:
    timestamp, request_id, model, user_question, duration_seconds
    invoked_tools[], invoked_servers[]
    status, optional error_message, tool_errors[]
```

## 4) Orchestrator (`src/chat_google/chat_service.py`)

## 4.1 High-level responsibilities

```text
1. Normalize user/history payloads
2. Load runtime config from .env
3. Start MCP stdio sessions (gmail/calendar/contacts/drive)
4. Build tool schemas for selected model family (Gemini vs OpenAI-compatible)
5. Execute multi-round tool-calling loop
6. Apply special behavior:
   - normalize relative date words for add_event
   - auto-send invites when user asks "invite ..."
   - force display of Drive share URLs in final answer
   - retry transient Gemini API errors
7. Persist metrics to metrics.jsonl
8. Write structured logs to chat_app.log
```

## 4.2 Core helper pseudocode

### `get_servers_config()`

```text
RETURN list:
    ("gmail", "gmail_server.py")
    ("calendar", "calendar_server.py")
    ("contacts", "contacts_server.py")
    ("drive", "drive_server.py")
```

### `load_runtime_settings()`

```text
LOAD .env
RETURN RuntimeSettings(
    base_url=BASE_URL or "https://ai.sumopod.com",
    api_key=API_KEY,
    google_gemini_api_key=GOOGLE_GEMINI_API_KEY
)
```

### `normalize_content_text(value)`

```text
IF value is None: RETURN ""
IF value is str: RETURN value
IF primitive (int/float/bool): RETURN str(value)
IF dict:
    IF dict has text string: RETURN dict["text"]
    ELSE IF dict has "content": recurse
    ELSE IF dict has "value": recurse
    ELSE RETURN json-dump(dict)
IF list:
    CONVERT each item recursively to text
    JOIN non-empty texts with newline
ELSE:
    RETURN str(value)
```

### `normalize_history(history)`

```text
FOR each history item:
    infer role/content
    normalize content with normalize_content_text
    validate with ChatMessage
RETURN normalized list[dict]
```

### `_normalize_add_event_args_from_message(tool_args, user_message)`

```text
IF tool name not add_event OR start_time missing: return as-is
IF user_message already contains explicit date pattern: return as-is

offset = detect relative day keyword:
    yesterday=-1, today=0, tomorrow=1, day after tomorrow=2
IF no offset: return as-is

extract HH:MM from user message
IF not found, fallback to HH:MM from tool_args["start_time"]
IF still not found: return as-is

target_date = now + offset days
tool_args["start_time"] = "{target_date} {hh:mm}"
RETURN updated args
```

### `_maybe_auto_send_invites(...)` (nested in `chat()`)

```text
RUN once only
PRECONDITION:
    user had invite intent keyword
    at least one email extracted from user message
    add_event args captured from successful tool call
    invite was not already sent manually by model

PREFER tool send_calendar_invite_email
FALLBACK to send_email when:
    invite tool unavailable OR invite tool returns error-like text

FOR each recipient email:
    build payload from created event data
    call chosen tool
    log duration and result
    collect tool errors and status updates

APPEND invitation delivery summary block to assistant response
RETURN updated response text
```

### `_append_share_links_if_missing(assistant_text, share_urls)`

```text
EXTRACT URLs already present in assistant_text
COMPUTE missing share_urls
IF missing exists:
    APPEND section:
        Shared URL(s):
        - <url1>
        - <url2>
RETURN final text
```

### `_collect_mcp_tools(stack, servers_config)`

```text
INIT maps:
    tool_to_session
    tool_to_server_name
INIT lists:
    mcp_tools (OpenAI-compatible schema)
    gemini_function_declarations

FOR each server config:
    START stdio server via:
        command="uv", args=["run","python", <server_script>]
    CREATE ClientSession
    session.initialize()
    tools = session.list_tools()

    FOR each tool:
        map tool -> session + server name
        append OpenAI-compatible function schema
        append Gemini FunctionDeclaration schema (sanitized)

RETURN all maps/lists
```

## 4.3 Main flow: `async chat(message, history, model_name)`

```text
1) Normalize inputs
   - normalize user message text
   - if empty message: yield original history and return
   - normalize history structure

2) Initialize request state
   - start timer, request_id
   - invoked_tools[], invoked_servers set
   - status="success", error_message=None, tool_errors[]
   - share_urls[] for Drive share tool outputs
   - capture invite intent + invite emails
   - keep last successful tool output for timeout fallback

3) Open MCP sessions and collect tool schemas
   - call _collect_mcp_tools(...)

4) Branch by model family

   A. Gemini path (model_name starts with "gemini")
      - validate google-genai import and GOOGLE_GEMINI_API_KEY
      - build GenerateContentConfig with runtime date/time context + tools
      - convert history to Gemini content objects
      - loop with safeguards:
          max_total_tool_calls = 12
          max_tool_rounds_per_response = 6
          repeated all-error rounds threshold = 2
      - request generation with retry for transient API errors
      - if no function_calls:
          extract text
          maybe auto-send invites
          append missing Drive URLs
          yield final history and break
      - else execute each requested tool:
          normalize add_event args if needed
          call MCP tool session
          track output/errors/timing
          capture share URLs from drive share tools
          track add_event args for auto-invite
          append function_response parts back to Gemini contents
      - on API exceptions:
          map to quota / transient / generic error messages
          yield error response

   B. OpenAI-compatible path (all non-Gemini models)
      - require API_KEY
      - compose messages with system instruction + runtime date context
      - loop max 8 rounds:
          POST /v1/chat/completions with model/messages/tools/tool_choice=auto
          if timeout:
              if had successful tool result:
                  return timeout warning + last tool result
              else:
                  return timeout error
          if non-200 or malformed response:
              return error
          if assistant has no tool_calls:
              use assistant text as final response
              maybe auto-send invites
              append missing Drive URLs
              yield final history and break
          else:
              append assistant message to api_messages
              for each tool_call:
                  parse JSON args
                  normalize add_event args if needed
                  execute MCP tool
                  track outputs/errors/timing
                  capture share URLs
                  track add_event args for auto-invite
                  append tool message to api_messages
              if all tool calls error in 2 consecutive rounds:
                  return repeated-failure error
      - if loop exhausted:
          return tool loop limit error

5) Global exception guard
   - return "Error: <exception>"

6) finally block (always)
   - if status success but tool_errors exists => success_with_tool_errors
   - write MetricsRecord to metrics.jsonl:
       timestamp, request_id, model, user_question, duration_seconds,
       invoked_tools, invoked_servers, status, error_message, tool_errors
```

## 5) Log and Metrics Behavior

```text
Logger:
    - console INFO
    - file DEBUG -> chat_app.log
Metrics:
    - append JSON line per request -> metrics.jsonl
    - validation via pydantic MetricsRecord
```

## 6) MCP Server Startup Wrappers (root files)

Files:

- `gmail_server.py`
- `calendar_server.py`
- `contacts_server.py`
- `drive_server.py`

Pattern:

```text
Inject ./src into sys.path
Import run() from src/chat_google/mcp_servers/<server>_server.py
Execute run() when file is run as script
```
