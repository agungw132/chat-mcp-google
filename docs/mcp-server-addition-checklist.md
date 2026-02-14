# MCP Server Addition Checklist

Use this quick checklist when adding a new MCP server.

Reference runbook:
- `docs/mcp-server-addition-runbook.md`

## A) Scope and Planning

- [ ] Define phase (`phase 1`, `phase 1.1`) and out-of-scope items.
- [ ] Propose tool list and get approval before implementation.
- [ ] Confirm expected behavior for ambiguous intents (for example invite behavior).
- [ ] Confirm pricing/quota constraints of the upstream API.

## B) Auth and Config

- [ ] Decide auth mode (API key, app password, OAuth token, refresh token).
- [ ] Add required env vars to `.env.template`.
- [ ] Add short explanation for each new env var in docs.
- [ ] Provide setup guide in `README.md` (manual steps).
- [ ] Add root helper script for programmatic setup (if feasible).

## C) Server Implementation

- [ ] Add implementation file: `src/chat_google/mcp_servers/<name>_server.py`.
- [ ] Add wrapper entrypoint: `<name>_server.py`.
- [ ] Implement and validate all approved tools.
- [ ] Standardize error outputs with actionable hints.

## D) Orchestrator Integration

- [ ] Register server in `get_servers_config()` (`src/chat_google/chat_service.py`).
- [ ] Add server literal to `ServerConfig` (`src/chat_google/models.py`).
- [ ] Update system instructions in `src/chat_google/constants.py` if needed.
- [ ] Add intent keywords for tool gating (if needed).
- [ ] Add or update `docs/mcp-servers/<name>.md` for runtime policy injection.

## E) Tests

- [ ] Add unit tests: `tests/test_<name>_server.py`.
- [ ] Add smoke test: `tests/test_<name>_server_smoke.py`.
- [ ] Add orchestration tests in `tests/test_chat_service.py` for routing and failure paths.
- [ ] Run full tests:

```powershell
uv run --with pytest --with pytest-asyncio --with-requirements requirements.txt pytest -q
```

## F) Documentation

- [ ] Update `README.md` (features, architecture, setup, tool list, troubleshooting).
- [ ] Update `readme-id.md` summary if behavior changed.
- [ ] Update `docs/README.md`.
- [ ] Add/update `docs/pseudocode-mcp-<name>.md`.
- [ ] Update `docs/pseudocode-chat-app.md` if orchestration changed.
- [ ] Update `docs/time-complexity-analysis.md` if complexity changed.
- [ ] Update `CHANGELOG.md` under `[Unreleased]`.

## G) Smoke Validation

- [ ] Run at least one real query (default model).
- [ ] Verify expected tools are invoked.
- [ ] Verify final response includes required artifacts (for example URL).
- [ ] Check `chat_app.log` and `metrics.jsonl` for errors and latency.

## H) Release and Delivery

- [ ] Do not push unless explicitly requested by user.
- [ ] If requested, bump version exactly as instructed (patch/minor/major).
- [ ] Create release notes from changelog when requested.

## Done Criteria

- [ ] Server runs locally.
- [ ] Tools callable from `chat_service`.
- [ ] Auth flow works and is documented.
- [ ] Tests pass.
- [ ] Docs are fully synchronized.
