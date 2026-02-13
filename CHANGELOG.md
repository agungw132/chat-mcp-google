# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

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
