# Time Complexity Analysis and Improvement Opportunities

This analysis is based on:

- `docs/pseudocode-chat-app.md`
- `docs/pseudocode-mcp-gmail.md`
- `docs/pseudocode-mcp-calendar.md`
- `docs/pseudocode-mcp-contacts.md`
- `docs/pseudocode-mcp-drive.md`
- `docs/pseudocode-mcp-docs.md`
- `docs/pseudocode-mcp-maps.md`

## 1) Notation

- `H`: number of chat history messages
- `X`: total normalized text size across `history + user message`
- `S`: number of MCP servers (currently 6)
- `T`: total number of discovered MCP tools (across all servers)
- `R`: number of tool-calling rounds in one model request
- `C`: total tool calls in one request
- `N`: number of items returned by an external provider (emails/events/files/documents/contacts/places/routes)
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
- Intent keyword routing (`_infer_requested_servers`): `O(|message| * keyword_count)` with small fixed keyword sets.
- MCP policy summary load from `docs/mcp-servers/*.md`:
  - first load (cold): `O(D)` where `D` is total docs size
  - subsequent requests (cache hit): `O(1)` for cache access + `O(selected_servers)` assembly
- MCP server startup and tool discovery per request: `O(S + T)` plus process startup + network overhead.
- Tool filtering by inferred server set: `O(T)` per request.

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
- however, tool gating reduces candidate tool schema size from `T` to `T'` (`T' <= T`) for most domain-specific prompts.

## 2.3 Tool output post-processing

- URL extraction + append missing URLs: `O(response_length + num_urls)`
- Tool output truncation: `O(tool_output_length)` per tool call
- Tool result contract normalization (JSON parse/fallback): `O(tool_output_length)` per tool call
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

- Drive token resolution:
- cached token path: `O(1)`
- refresh path on expiry: `O(1)` logic + 1 OAuth token HTTP request
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

## 7) Docs MCP Complexity

## 7.1 Tool complexity summary

- `list_docs_documents(limit=L)`: `O(L)` formatting on Drive list results.
- `search_docs_documents(limit=L)`: `O(L)` formatting on search results.
- `get_docs_document_metadata(document_id)`:
- Docs fetch `O(1)` + Drive metadata fetch `O(1)`.
- `read_docs_document(document_id, max_chars)`:
- Docs fetch + body traversal `O(N)` on document structural elements, truncation bounded by `max_chars`.
- `create_docs_document(title, initial_content)`:
- create call `O(1)` + optional initial insert `O(|initial_content|)`.
- `append_docs_text(document_id, text)`:
- read structure `O(N)` to find append index + batch update `O(|text|)`.
- `replace_docs_text(document_id, find_text, replace_text)`:
- single batch update request, practical complexity dominated by Docs backend processing.
- `share_docs_to_user(document_id, user_email, role, ...)`:
- permission create `O(1)` + metadata fetch `O(1)`.
- `export_docs_document(document_id, export_format, max_chars)`:
- export fetch `O(B)` where `B` is exported byte size; text decode/truncate is `O(min(B, max_chars))`.
- `append_docs_structured_content(...)`:
- build structured block `O(K)` (sum of item lengths) + append path `O(N + K)`.
- `replace_docs_text_if_revision(...)`:
- revision fetch `O(1)` + conditional replace batch update `O(1)` request count (backend-dependent processing).

## 7.2 Bottleneck notes

- Large documents increase `read_docs_document` traversal cost.
- Repeated write operations in separate tool calls (create -> append -> replace) add network round trips.
- Exporting large docs to text/binary increases payload transfer time (`O(B)`).
- Revision-safe writes add one extra pre-check call but reduce race-condition risk.

## 8) Maps MCP Complexity

## 8.1 Tool complexity summary

- `search_places_text(limit=L)`: `O(L)` formatting on returned place results.
- `geocode_address(limit=L)`: `O(L)` formatting on geocode candidates.
- `reverse_geocode(limit=L)`: `O(L)` formatting on reverse-geocode candidates.
- `get_place_details(place_id)`: `O(1)` data extraction from one payload.
- `get_directions(...)`:
- route scan `O(Routes * Legs)` with small practical caps (`<=3` routes when alternatives enabled).
- each leg contributes constant-time aggregation for distance/duration.

## 8.2 Bottleneck notes

- Directions complexity depends on number of returned route legs; inter-city routes with many legs increase parsing work.
- Most latency is external API/network, not local CPU.

## 9) End-to-End Hotspots (Priority Order)

## 9.1 P0 (Implemented) - Intent-based tool gating + MCP policy injection

- Implemented:
- infer requested server domains from prompt text
- filter tool schemas to relevant server subset
- inject compact MCP policy summary derived from `docs/mcp-servers/*.md`
- Complexity effect:
- adds small local overhead `O(T + D_cold)` / `O(T)` with cache warm
- typically reduces LLM tool-schema payload size from `T` to `T'`
- Expected impact: lower prompt/tool-selection noise, lower model latency, and better tool precision.

## 9.2 P1 - Reuse MCP sessions across chat requests

Current behavior starts and initializes all servers for every request.

- Big-O remains `O(S + T)`, but constant factor is very large.
- Improvement:
- Create long-lived MCP session manager with lazy init + health checks.
- Reconnect only on failure.
- Expected impact: significant latency reduction per chat turn.

## 9.3 P1 - Optimize Contacts `search_contacts` fallback path

- Current worst case `O(F)` with many GET calls even when only top 1-5 matches needed.
- Improvement options:
- Use server-side query endpoint that returns richer fields directly (if available).
- Build and cache lightweight local index (name/email -> card URL) with TTL.
- Stop fetching as soon as enough high-confidence matches found.
- Expected impact: major reduction for large address books.

## 9.4 P1 - Parallelize independent tool calls in a round

- Current execution is sequential per tool call.
- Improvement:
- Run calls concurrently when:
- tool calls are independent
- no ordering dependency exists
- session/client thread-safety is guaranteed (or separated by server/session).
- Expected impact: lower round latency when model emits multiple independent calls.

## 9.5 P2 - Cap context growth in multi-round orchestration

- Repeatedly appending tool outputs can increase request payload size across rounds.
- Improvement:
- Summarize/compress old tool outputs.
- Keep only latest relevant turns + structured memory summary.
- Expected impact: reduced model latency/cost and lower timeout probability.

## 9.6 P2 - Stream/truncate Drive file reads earlier

- `read_drive_text_file` downloads full content before truncation.
- Improvement:
- Use ranged reads/streaming and stop after `max_chars` threshold when feasible.
- Expected impact: better performance on large files.

## 9.7 P2 - Reduce unnecessary sorting in Calendar lists

- `sorted(results)` introduces `O(N log N)`.
- Improvement:
- Skip sorting when provider already returns chronological order.
- or request sorted order upstream.
- Expected impact: moderate CPU savings for larger event sets.

## 9.8 P3 - Batch IMAP fetch patterns in Gmail tools

- Several tools fetch message headers one-by-one.
- Improvement:
- Prefer batched sequence fetch where possible.
- Minimize repeated mailbox select calls.
- Expected impact: moderate latency reduction for larger `count` values.

## 9.9 P3 - Add response caching for frequent Maps lookups

- Repeated geocode/place details for the same query can trigger duplicate API calls.
- Improvement:
- Cache normalized query responses with short TTL (for example 1 to 10 minutes).
- Cache keys:
- `search_places_text`: (`query`,`language`,`region`,`limit`)
- `geocode_address`: (`address`,`language`,`region`,`limit`)
- `get_place_details`: (`place_id`,`language`)
- `get_directions`: (`origin`,`destination`,`mode`,`alternatives`,`units`)
- Expected impact: lower cost and faster responses on repeated lookups.

## 10) Suggested Implementation Roadmap

## Phase A (highest ROI)

1. Persistent MCP session manager (singleton/lifecycle-managed).
2. Contacts search optimization + caching.
3. Concurrent execution for independent multi-tool rounds.
4. Standardize MCP server native JSON error contracts to reduce plain-text fallback parsing.

## Phase B

1. Context compaction/summarization strategy in chat orchestrator.
2. Drive text read streaming/range handling.
3. Calendar sorting and query-window tuning.

## Phase C

1. Gmail fetch batching refinements.
2. Additional perf telemetry (per-step timing, cache hit rate, queue depth).

## 11) Optional Metrics to Track After Improvements

- `mcp_session_init_ms` and session reuse ratio
- `tool_round_count` and `tool_call_count`
- `contacts_search_links_scanned`
- `contacts_search_fallback_used`
- `drive_read_bytes_downloaded`
- `maps_cache_hit_rate`
- `maps_request_count_by_tool`
- `maps_error_status_count`
- `model_payload_chars_per_round`
- `p50/p95/p99` end-to-end latency per model and per tool

This instrumentation will validate whether complexity optimizations produce real latency improvements.
