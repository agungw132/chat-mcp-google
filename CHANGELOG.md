# Changelog

All notable changes to this project will be documented in this file.

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
