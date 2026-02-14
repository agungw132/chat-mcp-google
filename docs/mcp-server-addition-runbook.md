# MCP Server Addition Runbook

This runbook is the standard procedure to add a new MCP server into this repository and keep implementation, tests, and documentation consistent.

Use this when asked to add any new server (for example: Maps, Drive, Docs, Sheets, etc.).

Quick companion checklist:
- `docs/mcp-server-addition-checklist.md`

## 1) Confirm Scope First

1. Define phase and boundaries (`phase 1`, `phase 1.1`, optional items).
2. Confirm what is explicitly out-of-scope.
3. Propose tool list first, then get approval before coding.
4. Clarify default behavior for ambiguous intent (for example: invite means send calendar invite email).

Deliverable:
- approved tool matrix with required/optional status.

## 2) Cost and Product Constraints

1. Check whether upstream API is paid/free tier and summarize practical impact.
2. Clarify user account type constraints (personal account vs Workspace/project-based APIs).
3. Confirm quota expectations for smoke tests.

Deliverable:
- short cost/limits note in `README.md`.

## 3) Authentication Design

1. Decide auth mode(s):
- app password
- API key
- OAuth access token
- refresh token flow
2. Prefer long-lived auth path where possible (refresh token).
3. Add required env vars to `.env.template` with short per-variable explanation.
4. Provide both manual and programmatic setup guidance:
- manual steps in `README.md`
- helper script in repo root when feasible.

Deliverable:
- working auth config and setup docs.

## 4) Implement Server

1. Add server implementation:
- `src/chat_google/mcp_servers/<name>_server.py`
2. Add root wrapper entrypoint:
- `<name>_server.py`
3. Keep tool outputs stable and parseable.
4. Standardize error text and include actionable hints for common auth/scope failures.

Deliverable:
- runnable MCP server (`uv run python <name>_server.py`).

## 5) Integrate Into Chat Orchestrator

1. Register server in `get_servers_config()` in `src/chat_google/chat_service.py`.
2. Ensure server name is allowed in `ServerConfig` (`src/chat_google/models.py`).
3. Update system instruction guidance in `src/chat_google/constants.py` if new domain behavior matters.
4. Ensure intent-based tool gating includes the new server keywords.
5. Ensure `docs/mcp-servers/<name>.md` can be consumed by runtime MCP policy injection.

Deliverable:
- new tools discoverable and callable by `chat_service`.

## 6) Add Tests (Minimum Bar)

1. Unit tests for every tool:
- `tests/test_<name>_server.py`
2. Smoke test:
- `tests/test_<name>_server_smoke.py`
3. Orchestration tests (chat flow):
- tool routing
- error handling
- fallback behavior
4. Optional live no-UI smoke for end-to-end validation with real credentials.

Recommended command:

```powershell
uv run --with pytest --with pytest-asyncio --with-requirements requirements.txt pytest -q
```

Deliverable:
- tests pass locally, including new server coverage.

## 7) Update Documentation (Mandatory)

1. Main docs:
- `README.md` (features, architecture, setup, tools, troubleshooting)
- `readme-id.md` (short Indonesian pointer summary)
- `CHANGELOG.md` (`[Unreleased]` section)
2. Docs folder:
- `docs/mcp-servers/<name>.md` (agent-oriented usage guide)
- `docs/pseudocode-mcp-<name>.md`
- `docs/pseudocode-chat-app.md` if orchestration changed
- `docs/time-complexity-analysis.md` if complexity profile changed
- `docs/README.md` file list/scope updates
3. Keep language professional and consistent with current repo style.

Deliverable:
- no feature/docs mismatch.

## 8) Smoke Test Real Query

1. Run at least one realistic query using the default model.
2. Verify:
- correct tool invocation
- final response quality
- response includes important artifacts (for example share URLs)
3. Check observability:
- `chat_app.log`
- `metrics.jsonl`

Deliverable:
- validated real-world behavior, not only unit tests.

## 9) Release Hygiene

1. Only push when user explicitly asks to push.
2. If asked, bump version appropriately (patch/minor/major as instructed).
3. Update changelog before tag/release.
4. Create release notes from changelog summary.

Deliverable:
- clean release process with traceable changes.

## 10) Definition of Done

A new MCP server is done only when all below are true:

1. Server + wrapper implemented and runnable.
2. Registered in orchestrator and model validation.
3. Auth flow documented (manual + programmatic if feasible).
4. Unit + smoke tests added and passing.
5. README + docs folder fully updated.
6. Real query smoke test validated via logs/metrics.
7. Version/changelog/release updated when requested.
