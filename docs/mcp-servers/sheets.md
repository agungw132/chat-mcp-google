# Sheets MCP Server

Source:

- `src/chat_google/mcp_servers/sheets_server.py`
- wrapper: `sheets_server.py`
- FastMCP server name: `GoogleSheets`

## Purpose

Use this server for Google Sheets discovery, metadata retrieval, tab creation, cell-level read/write operations, export, batch range operations, and spreadsheet sharing.

## Required configuration

- `GOOGLE_DRIVE_ACCESS_TOKEN`

Optional long-lived auth (recommended):

- `GOOGLE_DRIVE_REFRESH_TOKEN`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`

When all three are set, Sheets MCP auto-refreshes access tokens and avoids short-lived token failures.

Required Google API enablement:

- Google Sheets API
- Google Drive API (used for listing/searching spreadsheet files)

## Tool catalog

- `list_sheets_spreadsheets(limit=10)`
- `search_sheets_spreadsheets(query, limit=10)`
- `get_sheets_metadata(spreadsheet_id)`
- `read_sheet_values(spreadsheet_id, range_a1='A1:Z50', max_rows=50, max_cols=20)`
- `append_sheet_row(spreadsheet_id, range_a1, values)`
- `update_sheet_values(spreadsheet_id, range_a1, values, value_input_option='USER_ENTERED')`
- `create_sheets_spreadsheet(title, sheet_title='Sheet1')`
- `add_sheet_tab(spreadsheet_id, title, row_count=1000, column_count=26)`
- `list_spreadsheets(limit=10, include_excel=True)`
- `search_spreadsheets(query, limit=10, include_excel=True)`
- `get_spreadsheet_metadata(file_id)` (native Sheets or `.xlsx/.xls`)
- `read_excel_values(file_id, sheet_name='', range_a1='A1:Z50', max_rows=50, max_cols=20)`
- `convert_excel_to_google_sheet(file_id, new_title='', move_to_parent=True)`
- `export_google_sheet(file_id, export_format='xlsx', gid=None, range_a1='', max_preview_chars=2000)` (`xlsx`, `ods`, `pdf`, `zip`, `csv`, `tsv`)
- `batch_get_sheet_values(spreadsheet_id, ranges, value_render_option='FORMATTED_VALUE', date_time_render_option='SERIAL_NUMBER', max_rows_per_range=20, max_cols_per_row=20)`
- `batch_update_sheet_values(spreadsheet_id, updates, value_input_option='USER_ENTERED')`
- `share_spreadsheet(file_id, user_email, role='writer', send_notification=True, message='')`
- `create_spreadsheet_from_template(template_file_id, new_title, destination_folder_id='')`
- `import_csv_to_sheet(spreadsheet_id, sheet_name, csv_text, overwrite=False)`
- `insert_sheet_chart(spreadsheet_id, sheet_id, chart_spec)`
- `protect_sheet_or_range(spreadsheet_id, sheet_id=None, range_a1='', editors=[], warning_only=False)`
- `create_pivot_table(spreadsheet_id, source_range, target_sheet, target_cell='A1', summarize_function='COUNTA')`
- `get_spreadsheet_permissions(file_id)`

## Calling guidance

Discovery:

- recent spreadsheet overview -> `list_sheets_spreadsheets`
- title-based lookup -> `search_sheets_spreadsheets`
- mixed spreadsheet inventory (native + `.xlsx/.xls`) -> `list_spreadsheets` / `search_spreadsheets`

Read:

- spreadsheet/tab metadata -> `get_sheets_metadata`
- cell/range read -> `read_sheet_values`
- cross-type metadata lookup -> `get_spreadsheet_metadata`
- direct `.xlsx/.xls` cell read without conversion -> `read_excel_values`

Write:

- append one row -> `append_sheet_row`
- update fixed range -> `update_sheet_values`
- create new spreadsheet -> `create_sheets_spreadsheet`
- add new tab -> `add_sheet_tab`
- convert `.xlsx/.xls` to native Google Sheet -> `convert_excel_to_google_sheet`
- update multiple ranges in one request -> `batch_update_sheet_values`
- share spreadsheet access to one user -> `share_spreadsheet`
- copy from template -> `create_spreadsheet_from_template`
- import CSV text into tab -> `import_csv_to_sheet`

Export:

- export native Google Sheet -> `export_google_sheet`
- preview text formats (`csv`, `tsv`) directly in chat output
- for binary exports (`xlsx`, `ods`, `pdf`, `zip`), tool returns export metadata + byte size

Batch read:

- read multiple ranges in one request -> `batch_get_sheet_values`

Structure and governance:

- insert chart with raw chart spec -> `insert_sheet_chart`
- protect full sheet or A1 range -> `protect_sheet_or_range`
- create basic pivot table -> `create_pivot_table`
- audit file permissions -> `get_spreadsheet_permissions`

## Output semantics

- Server returns plain text summaries and action results.
- In this repository orchestration path, `chat_service` wraps tool output into a structured contract before feeding model context.
- Write tools include updated range/cell counts when available from Sheets API.

## Error semantics

- Sheets API errors are normalized as:
- `Error: Google Sheets API request failed: <status> ...`
- Drive API errors are normalized as:
- `Error: Drive API request failed: <status> ...`

Typical causes:

- missing/expired token
- Sheets API not enabled in GCP project
- insufficient OAuth scope for Sheets/Drive
- spreadsheet permission mismatch

## Constraints and limits

- `read_sheet_values` can cap output via `max_rows` and `max_cols` to keep chat responses bounded.
- `read_excel_values` can cap output via `max_rows` and `max_cols` to keep chat responses bounded.
- `batch_get_sheet_values` can cap output via `max_rows_per_range` and `max_cols_per_row`.
- `update_sheet_values` supports only `RAW` and `USER_ENTERED` for `value_input_option`.
- `batch_update_sheet_values` supports only `RAW` and `USER_ENTERED` for `value_input_option`.
- `append_sheet_row` appends exactly one row per call (`values` is one list).
- `read_excel_values` requires `openpyxl` (`.xlsx`) and `xlrd` (`.xls`) runtime dependencies.
- `export_google_sheet` only supports native Google Sheets input files.
- `share_spreadsheet` roles are limited to `reader`, `commenter`, `writer`.
- `insert_sheet_chart` expects valid Google Sheets chart spec object in `chart_spec`.
- `protect_sheet_or_range` requires `sheet_id` or `range_a1`.
- `create_pivot_table` creates a basic pivot configuration (first source column grouped, next source column summarized when available).

## Recommended patterns

Create and populate:

1. `create_sheets_spreadsheet(title, sheet_title=...)`
2. `append_sheet_row(spreadsheet_id, range_a1='Sheet1!A:Z', values=[...])`
3. `update_sheet_values(spreadsheet_id, range_a1='Sheet1!A1:C1', values=[[...]])`

Find and inspect:

1. `search_sheets_spreadsheets(query=...)`
2. `get_sheets_metadata(spreadsheet_id=...)`
3. `read_sheet_values(spreadsheet_id=..., range_a1=...)`

Excel workflow:

1. `search_spreadsheets(query=..., include_excel=True)`
2. `read_excel_values(file_id=...)`
3. optional: `convert_excel_to_google_sheet(file_id=...)` for native Sheets workflows

Batch processing workflow:

1. `batch_get_sheet_values(spreadsheet_id=..., ranges=[...])`
2. derive changes in app/model
3. `batch_update_sheet_values(spreadsheet_id=..., updates=[...])`

Share workflow:

1. `search_spreadsheets(query=..., include_excel=True)` or `list_spreadsheets(...)`
2. `share_spreadsheet(file_id=..., user_email=..., role='writer')`
