# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

## [1.2.0] - 2026-02-14

### Added
- Added comprehensive agent-oriented MCP READMEs in `docs/mcp-servers/` for:
  - `gmail`
  - `calendar`
  - `contacts`
  - `drive`
  - `docs`
  - `maps`
- Added new Google Docs MCP server (phase 1) with tools:
  - `list_docs_documents`
  - `search_docs_documents`
  - `get_docs_document_metadata`
  - `read_docs_document`
  - `create_docs_document`
  - `append_docs_text`
  - `replace_docs_text`
- Added root wrapper entrypoint: `docs_server.py`.
- Added Docs unit and smoke tests.
- Added Docs pseudocode and agent-oriented documentation.

### Changed
- Chat orchestration now derives a compact MCP policy summary from `docs/mcp-servers/*.md` and injects it into model system instructions.
- Added intent-based MCP tool gating so model tool schemas are filtered to relevant server domains per request.
- Tool execution feedback to models now uses a structured contract (`success`, `error`, `data`) in both Gemini and OpenAI-compatible flows.
- User responses now include contextual warning when required MCP server(s) are unavailable for the current request.
- Request ID format now includes UUID suffix for better collision safety in concurrent runs.
- Integrated Docs MCP into server registry, intent routing keywords, and policy doc mapping.
- Updated app caption and README architecture/tooling docs to include Docs MCP.
- Updated onboarding runbook/checklist with parser-compatible MCP doc requirements and auth/env reuse guidance.

### Quality
- Expanded chat orchestration tests for:
  - intent-based tool filtering
  - runtime policy injection
  - unavailable-server warning surfacing
  - structured tool-result contract handling
- Added Docs auth tests for refresh-token flow and missing credential behavior.

### Fixed
- Improved Docs MCP auth reliability by reloading `.env` at token read time and retrying once after `401` responses.
- Improved Docs/Drive MCP error hints to explicitly guide OAuth refresh-token setup on `401`.

## [1.1.2] - 2026-02-14

### Added
- Added Google Maps MCP server with tools:
  - `search_places_text`
  - `geocode_address`
  - `reverse_geocode`
  - `get_place_details`
  - `get_directions`
- Added root wrapper entrypoint: `maps_server.py`.
- Added Maps unit and smoke tests.
- Added programmatic helper script: `get_google_maps_api_key.py`.
- Added Drive token helper enhancements to store:
  - `GOOGLE_DRIVE_REFRESH_TOKEN`
  - `GOOGLE_OAUTH_CLIENT_ID`
  - `GOOGLE_OAUTH_CLIENT_SECRET`

### Changed
- Integrated Maps MCP into chat server registry and validation model.
- Updated UI caption and README to include Maps support.
- Added `GOOGLE_MAPS_API_KEY` to `.env.template`.
- Added setup guide for obtaining `GOOGLE_MAPS_API_KEY` and required Maps APIs.
- Improved `get_google_maps_api_key.py` token flow with OAuth client-secret fallback when `gcloud` is unavailable.
- Updated `docs/` pseudocode and time-complexity documents to include Maps MCP coverage.
- Added Drive auto-refresh token flow in `drive_server.py` (with cache + refresh-token fallback behavior).
- Updated `.env.template` and README with Drive refresh OAuth credential guidance.

## [1.1.1] - 2026-02-13

### Added
- Added comprehensive pseudocode documentation for chat app orchestration and all MCP servers/tools in `docs/`.
- Added time complexity analysis and performance improvement proposals in `docs/time-complexity-analysis.md`.

## [1.1.0] - 2026-02-13

### Added
- Added new Google Drive MCP server (phase 1 + 1.1) with tools:
  - `list_drive_files`
  - `search_drive_files`
  - `get_drive_file_metadata`
  - `read_drive_text_file` (non-Google Workspace files)
  - `list_shared_with_me`
  - `create_drive_folder`
  - `upload_text_file`
  - `move_drive_file`
  - `create_drive_shared_link_to_user` (default expiration 7 days)
  - `create_drive_public_link` (supports file/folder)
- Added backward-compatible root wrapper entrypoint: `drive_server.py`.
- Added comprehensive Drive test coverage (unit + smoke).
- Added setup guide for `GOOGLE_DRIVE_ACCESS_TOKEN` in `README.md`.
- Added live non-UI smoke test: `tests/test_live_smoke_no_ui.py` (opt-in via `RUN_LIVE_SMOKE=1`).
- Added new non-Gemini models:
  - `kimi-k2-thinking-251104`
  - `seed-1-8-251228`
  - `deepseek-r1-250528`
  - `whisper-1`
- Added Gmail MCP tool `send_calendar_invite_email` to deliver ICS invitation emails (`text/calendar`, accept/reject capable).

### Changed
- Added `GOOGLE_DRIVE_ACCESS_TOKEN` to `.env.template`.
- Integrated Drive MCP server into chat orchestration server registry.
- Updated Drive token guidance to use `https://www.googleapis.com/auth/drive` as default script scope.
- Refactored OpenAI-compatible chat flow to support multi-round tool calls.
- Added truncation for large tool outputs before feeding back into model context.
- Added explicit timeout handling for OpenAI-compatible model calls (`error_http_timeout`).
- Changed fallback default model to `azure_ai/kimi-k2.5` (when `.env` `MODEL` is missing/invalid).
- Changed invite behavior: when user asks to invite and event is created, app now auto-sends invitation email (prefers ICS invite tool, falls back to plain email).

### Fixed
- Fixed Drive user-sharing flow for items that reject expiration (`403 cannotSetExpiration`) by auto-retrying without expiration.
- Fixed partial non-Gemini responses that stopped after intermediate tool-intent text by continuing tool rounds until final answer.

### Quality
- Expanded chat orchestration tests for multi-round OpenAI-compatible tool calls and timeout behavior.

## [1.0.2] - 2026-02-13

### Changed
- Improved observability for MCP tool execution with request-scoped logs (tool args summary, execution duration, and tool output summaries).
- Extended `metrics.jsonl` schema with `error_message` and `tool_errors`.
- Added `success_with_tool_errors` status for requests that complete but include tool-level failures.

### Fixed
- Fixed `search_contacts` runtime failure when `httpx` HTTP/2 support (`h2`) is not installed by auto-falling back to HTTP/1.1.
- Hardened contacts search diagnostics with explicit logging for `REPORT` failures and `PROPFIND` fallback behavior.

### Quality
- Added regression tests for HTTP/1.1 fallback path in contacts server.
- Updated test baseline: `35 passed`.

## [1.0.1] - 2026-02-13

### Added
- Added Sumopod model option: `azure_ai/kimi-k2.5`.

### Changed
- Updated chat UI text to English (`Type your message...`, `Retry`, `Clear`, `Select Model`).
- Updated default model instructions to English for both Gemini and OpenAI-compatible flows.
- Standardized user-facing error messages in chat flow to English.

### Quality
- Updated and validated constants tests for the new model default resolution path.

## [1.0.0] - 2026-02-13

### Added
- Refactored codebase into `src/chat_google` package layout with backward-compatible root entrypoint wrappers.
- Comprehensive test suite covering chat orchestration and all MCP tools (`gmail`, `calendar`, `contacts`).
- Pydantic validation for runtime settings, normalized chat payloads, metrics records, and MCP tool inputs.
- Architecture diagram and improved operational documentation in `README.md`.
- `.env.template` with documented configuration variables.

### Changed
- Default UI model now resolves from `.env` `MODEL` with fallback to built-in default.
- Chat payload normalization now handles non-string/multimodal-like message input for stable metrics logging.
- Repository documentation standardized to English.

### Quality
- Test baseline for this release: `31 passed`.

