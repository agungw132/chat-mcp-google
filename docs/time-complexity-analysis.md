# Time Complexity Analysis and Improvement Opportunities

This analysis is based on:

- `docs/pseudocode-chat-app.md`
- `docs/pseudocode-mcp-gmail.md`
- `docs/pseudocode-mcp-calendar.md`
- `docs/pseudocode-mcp-contacts.md`
- `docs/pseudocode-mcp-drive.md`

## 1) Notation

- `H`: number of chat history messages
- `X`: total normalized text size across `history + user message`
- `S`: number of MCP servers (currently 4)
- `T`: total number of discovered MCP tools (across all servers)
- `R`: number of tool-calling rounds in one model request
- `C`: total tool calls in one request
- `N`: number of items returned by an external provider (emails/events/files/contacts)
- `L`: user-requested list limit (typically <= 100)
- `F`: number of CardDAV contact links
- `B`: contacts fetch batch size (`FETCH_BATCH_SIZE`, currently 20)
- `K`: number of matching results
- `Q`: number of invite recipients parsed from prompt
- `M`: file content size (bytes/chars) for read/upload operations

Notes:

- Many operations are network-bound; Big-O expresses algorithmic growth, not absolute latency.
- Some loops are explicitly bounded in code (for safety), so worst-case complexity is effectively capped.

## 2) Chat Application Complexity

## 2.1 Input normalization and setup

- `normalize_history` + `normalize_content_text`: `O(X)`
- Extract invite emails / detect intent / regex helpers: `O(|message|)`
- MCP server startup and tool discovery per request: `O(S + T)` plus process startup + network overhead.

## 2.2 Model orchestration loops

### Gemini branch

- In theory: `O(R * (LLM_call + tool_execution))`
- In implementation:
- total tool calls bounded by `max_total_tool_calls = 12`
- per response function call count bounded by `max_tool_rounds = 6`
- effective upper bound per request is constant-scale, but each step can be expensive due to network/tool latency.

### OpenAI-compatible branch

- In theory: `O(R * (HTTP_model_call + tool_execution))`
- In implementation:
- round bound `max_tool_rounds = 8`
- each round may append more context; payload size grows across rounds.

## 2.3 Tool output post-processing

- URL extraction + append missing URLs: `O(response_length + num_urls)`
- Tool output truncation: `O(tool_output_length)` per tool call
- Metrics logging: amortized `O(1)` append.

## 2.4 Practical bottleneck

Largest recurring overhead is repeated MCP session bootstrap (`uv run python <server>`) on every chat request. This is effectively constant in Big-O, but high in wall-clock time.

## 3) Gmail MCP Complexity

## 3.1 Tool complexity summary

- `list_recent_emails(count=L)`: `O(L)` local parsing, 1 range fetch from IMAP.
- `read_email(email_id)`: `O(P + body_size)` where `P` is MIME part traversal.
- `summarize_emails(count=L)`: `O(L)` fetch/parse loop after search.
- `list_unread_emails(count=L)`: `O(L)`.
- `mark_as_read`: `O(1)`.
- `list_labels`: `O(number_of_labels)`.
- `search_emails_by_label(count=L)`: `O(L)`.
- `search_emails(query)`: capped to latest 10 IDs => `O(min(N,10))` after search response.
- `send_email`: `O(body_size)` for message build + SMTP send.
- `send_calendar_invite_email`: `O(body_size + ICS_size)` with mostly constant ICS field count.

## 3.2 Bottleneck notes

- Multiple tools perform sequential IMAP fetches; high latency grows linearly with fetched message count.

## 4) Calendar MCP Complexity

## 4.1 Tool complexity summary

- `summarize_agenda`:
- event scan/parse `O(N)`
- final `sorted(results)` adds `O(N log N)`
- `list_events`:
- scan `O(N)`
- sorting `O(N log N)`
- `add_event`: `O(1)` (single create request).
- `search_events`:
- scan `O(N)` over fetched window
- sort matches `O(K log K)`.

## 4.2 Bottleneck notes

- Unbounded event retrieval windows can increase `N`; sorting adds avoidable overhead when chronological order is not strictly required.

## 5) Contacts MCP Complexity

## 5.1 Tool complexity summary

- `_fetch_vcf_links` / `_search_vcf_links` XML parse: `O(F)` on number of XML response nodes.
- `_fetch_contacts`:
- network requests across links in batches: `O(F)` requests
- parse/filter per response: `O(F)`
- total algorithmic complexity: `O(F)`, latency influenced by batching and external server.
- `list_contacts(limit=L)`:
- currently fetches only `links[:L]` => about `O(L)`.
- `search_contacts(query)` worst case:
- REPORT fails or returns empty -> fallback PROPFIND
- then fetch many/all links and filter locally with `max_results=5`
- worst-case `O(F)` despite small output.

## 5.2 Bottleneck notes

- Contact search can become slow for large contact sets because fallback path still scans many cards.

## 6) Drive MCP Complexity

## 6.1 Tool complexity summary

- `list_drive_files(limit=L)`: `O(L)`.
- `search_drive_files(limit=L)`: `O(L)`.
- `get_drive_file_metadata`: `O(1)`.
- `read_drive_text_file(file_id, max_chars)`:
- metadata request: `O(1)`
- media download/decode: `O(M)`
- truncation to `max_chars` after decode still requires reading full payload.
- `list_shared_with_me(limit=L)`: `O(L)`.
- `create_drive_folder`: `O(1)`.
- `upload_text_file(name, content)`:
- metadata create `O(1)`
- upload content `O(M)`
- metadata refresh `O(1)`.
- `move_drive_file`:
- read current metadata + patch: `O(1)` (plus small parent list handling).
- `create_drive_shared_link_to_user`:
- typical: `O(1)` (permission create + metadata fetch)
- with `cannotSetExpiration` fallback: still `O(1)` with one extra create call.
- `create_drive_public_link`: `O(1)` (permission create + metadata fetch).

## 6.2 Bottleneck notes

- Reading large text files fully before truncation can waste bandwidth/time.

## 7) End-to-End Hotspots (Priority Order)

## 7.1 P1 - Reuse MCP sessions across chat requests

Current behavior starts and initializes all servers for every request.

- Big-O remains `O(S + T)`, but constant factor is very large.
- Improvement:
- Create long-lived MCP session manager with lazy init + health checks.
- Reconnect only on failure.
- Expected impact: significant latency reduction per chat turn.

## 7.2 P1 - Optimize Contacts `search_contacts` fallback path

- Current worst case `O(F)` with many GET calls even when only top 1-5 matches needed.
- Improvement options:
- Use server-side query endpoint that returns richer fields directly (if available).
- Build and cache lightweight local index (name/email -> card URL) with TTL.
- Stop fetching as soon as enough high-confidence matches found.
- Expected impact: major reduction for large address books.

## 7.3 P1 - Parallelize independent tool calls in a round

- Current execution is sequential per tool call.
- Improvement:
- Run calls concurrently when:
- tool calls are independent
- no ordering dependency exists
- session/client thread-safety is guaranteed (or separated by server/session).
- Expected impact: lower round latency when model emits multiple independent calls.

## 7.4 P2 - Cap context growth in multi-round orchestration

- Repeatedly appending tool outputs can increase request payload size across rounds.
- Improvement:
- Summarize/compress old tool outputs.
- Keep only latest relevant turns + structured memory summary.
- Expected impact: reduced model latency/cost and lower timeout probability.

## 7.5 P2 - Stream/truncate Drive file reads earlier

- `read_drive_text_file` downloads full content before truncation.
- Improvement:
- Use ranged reads/streaming and stop after `max_chars` threshold when feasible.
- Expected impact: better performance on large files.

## 7.6 P2 - Reduce unnecessary sorting in Calendar lists

- `sorted(results)` introduces `O(N log N)`.
- Improvement:
- Skip sorting when provider already returns chronological order.
- or request sorted order upstream.
- Expected impact: moderate CPU savings for larger event sets.

## 7.7 P3 - Batch IMAP fetch patterns in Gmail tools

- Several tools fetch message headers one-by-one.
- Improvement:
- Prefer batched sequence fetch where possible.
- Minimize repeated mailbox select calls.
- Expected impact: moderate latency reduction for larger `count` values.

## 8) Suggested Implementation Roadmap

## Phase A (highest ROI)

1. Persistent MCP session manager (singleton/lifecycle-managed).
2. Contacts search optimization + caching.
3. Concurrent execution for independent multi-tool rounds.

## Phase B

1. Context compaction/summarization strategy in chat orchestrator.
2. Drive text read streaming/range handling.
3. Calendar sorting and query-window tuning.

## Phase C

1. Gmail fetch batching refinements.
2. Additional perf telemetry (per-step timing, cache hit rate, queue depth).

## 9) Optional Metrics to Track After Improvements

- `mcp_session_init_ms` and session reuse ratio
- `tool_round_count` and `tool_call_count`
- `contacts_search_links_scanned`
- `contacts_search_fallback_used`
- `drive_read_bytes_downloaded`
- `model_payload_chars_per_round`
- `p50/p95/p99` end-to-end latency per model and per tool

This instrumentation will validate whether complexity optimizations produce real latency improvements.
