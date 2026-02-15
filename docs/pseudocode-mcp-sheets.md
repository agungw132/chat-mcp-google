# Pseudocode - MCP Google Sheets

Source implementation:
- `src/chat_google/mcp_servers/sheets_server.py`

Wrapper entrypoint:
- `sheets_server.py`

## 1) Bootstrap

```text
LOAD .env
CREATE FastMCP server named "GoogleSheets"
DEFINE API bases:
  SHEETS_API_BASE = https://sheets.googleapis.com/v4/spreadsheets
  DRIVE_API_BASE = https://www.googleapis.com/drive/v3
  OAUTH_TOKEN_ENDPOINT = https://oauth2.googleapis.com/token
```

## 2) Input Schemas

```text
List/Search:
  limit (1..100), query non-empty

ID operations:
  spreadsheet_id non-empty

Read values:
  spreadsheet_id, range_a1, max_rows (1..500), max_cols (1..200)

Append row:
  spreadsheet_id, range_a1, values[] (single row)

Update values:
  spreadsheet_id, range_a1, values[][], value_input_option in {RAW, USER_ENTERED}

Create spreadsheet:
  title, sheet_title

Add tab:
  spreadsheet_id, title, row_count, column_count

Unified spreadsheet tools:
  list/search with include_excel flag
  metadata by file_id for native Sheets or .xlsx/.xls
  list_spreadsheet_templates(limit, folder_name, name_contains, include_excel)

Excel tools:
  read_excel_values(file_id, sheet_name, range_a1, max_rows, max_cols)
  convert_excel_to_google_sheet(file_id, new_title, move_to_parent)

Phase-2 tools:
  export_google_sheet(file_id, export_format, gid, range_a1, max_preview_chars)
  batch_get_sheet_values(spreadsheet_id, ranges, value_render_option, date_time_render_option, max_rows_per_range, max_cols_per_row)
  batch_update_sheet_values(spreadsheet_id, updates, value_input_option)
  share_spreadsheet(file_id, user_email, role, send_notification, message)
  create_spreadsheet_from_template(template_file_id, new_title, destination_folder_id)
  import_csv_to_sheet(spreadsheet_id, sheet_name, csv_text, overwrite)
  insert_sheet_chart(spreadsheet_id, sheet_id, chart_spec)
  protect_sheet_or_range(spreadsheet_id, sheet_id, range_a1, editors, warning_only)
  create_pivot_table(spreadsheet_id, source_range, target_sheet, target_cell, summarize_function)
  get_spreadsheet_permissions(file_id)
```

## 3) Auth and HTTP Helpers

```text
FUNCTION _get_access_token():
  RELOAD .env (override enabled)
  IF cached token exists and valid: return cached

  READ static + refresh config:
    GOOGLE_DRIVE_ACCESS_TOKEN
    GOOGLE_DRIVE_REFRESH_TOKEN
    GOOGLE_OAUTH_CLIENT_ID
    GOOGLE_OAUTH_CLIENT_SECRET

  IF refresh config complete:
    REFRESH token via OAuth endpoint
    CACHE token with expiry margin
    STORE refreshed token in process env
    RETURN refreshed token

  IF static token exists: return static token
  ELSE raise ValueError with setup guidance

FUNCTION _sheets_get/_sheets_post/_sheets_put():
  SEND request with bearer token
  IF 401:
    invalidate cache
    retry once with refreshed/reloaded token
  IF non-success:
    return normalized Sheets error
  RETURN JSON payload

FUNCTION _drive_get():
  same retry/auth logic, but normalized Drive error

FUNCTION _drive_get_bytes():
  download raw bytes from Drive file media endpoint (with same auth retry)

FUNCTION _drive_post():
  generic Drive POST helper (with same auth retry)

FUNCTION _drive_upload_multipart():
  upload media as multipart for conversion fallback path

FUNCTION _drive_export_google_sheet_bytes():
  for csv/tsv with gid:
    call docs export endpoint with format + gid
  otherwise:
    call Drive export endpoint with mimeType
  return bytes payload
```

## 4) Utility Helpers

```text
_encode_a1_range:
  URL-encode A1 notation safely for Sheets path usage

_format_sheet_file_line:
  normalize Drive file metadata into parseable line format
```

## 5) Tool Flows

## 5.1 list_sheets_spreadsheets(limit=10)

```text
VALIDATE input
QUERY Drive files with mimeType=spreadsheet and trashed=false
ORDER by modifiedTime desc
FORMAT each result line (name, id, modified, link)
RETURN list text
```

## 5.2 search_sheets_spreadsheets(query, limit=10)

```text
VALIDATE input
ESCAPE query
QUERY Drive files where spreadsheet title contains query
FORMAT and RETURN results
```

## 5.3 get_sheets_metadata(spreadsheet_id)

```text
VALIDATE input
GET spreadsheet metadata from Sheets API:
  title, spreadsheet URL, tabs with grid sizes
FORMAT summary:
  spreadsheet title/id/url + tab lines
RETURN metadata text
```

## 5.4 read_sheet_values(spreadsheet_id, range_a1='A1:Z50', max_rows=50, max_cols=20)

```text
VALIDATE input
GET values from Sheets API for encoded A1 range
IF empty: return no-values message
APPLY max_rows and max_cols for bounded output
FORMAT rows as parseable text lines
APPEND truncation notes when output was capped
RETURN values summary
```

## 5.5 append_sheet_row(spreadsheet_id, range_a1, values)

```text
VALIDATE input
POST values.append with valueInputOption=USER_ENTERED and insertDataOption=INSERT_ROWS
GET spreadsheet title/url
RETURN updatedRange, updatedRows, updatedCells, link
```

## 5.6 update_sheet_values(spreadsheet_id, range_a1, values, value_input_option='USER_ENTERED')

```text
VALIDATE input and option
PUT values.update with provided 2D values
RETURN updated range/row/column/cell counters
```

## 5.7 create_sheets_spreadsheet(title, sheet_title='Sheet1')

```text
VALIDATE input
POST spreadsheets.create with title and initial tab title
RETURN spreadsheet id/url/title + initial tab details
```

## 5.8 add_sheet_tab(spreadsheet_id, title, row_count=1000, column_count=26)

```text
VALIDATE input
POST spreadsheets.batchUpdate with addSheet request
GET spreadsheet metadata for title/url
RETURN tab id/title + grid + spreadsheet URL
```

## 5.9 list_spreadsheets(limit=10, include_excel=True)

```text
VALIDATE input
QUERY Drive files with mime filter:
  include_excel=false -> native Sheets only
  include_excel=true -> native Sheets OR xlsx/xls
FORMAT lines with normalized type labels (google_sheet/excel_xlsx/excel_xls)
RETURN list output
```

## 5.9b list_spreadsheet_templates(limit=10, folder_name='Documents', name_contains='template', include_excel=True)

```text
VALIDATE input
RESOLVE folder id by folder_name:
  QUERY Drive folders where name == folder_name and trashed=false
  select latest modified match
BUILD unified spreadsheet mime query from include_excel
ADD parent filter: '<folder_id>' in parents
IF name_contains is non-empty:
  ADD name contains filter
QUERY Drive files
FORMAT lines with normalized type labels
RETURN template candidate summary
```

## 5.10 search_spreadsheets(query, limit=10, include_excel=True)

```text
VALIDATE input
BUILD Drive query with title contains + mime filter
FORMAT lines with normalized type labels
RETURN search output
```

## 5.11 get_spreadsheet_metadata(file_id)

```text
GET Drive metadata (name, mime, owners, size, link)
IF native Google Sheet:
  GET sheet tabs from Sheets API
IF .xlsx/.xls:
  download bytes from Drive
  inspect workbook sheet names via openpyxl (if available)
RETURN unified metadata summary
```

## 5.12 read_excel_values(file_id, sheet_name='', range_a1='A1:Z50', max_rows=50, max_cols=20)

```text
VALIDATE input
GET Drive metadata and verify file is .xlsx or .xls
DOWNLOAD bytes via Drive media endpoint
OPEN workbook with openpyxl (read_only, data_only)
RESOLVE target sheet from:
  explicit sheet_name
  or A1 sheet prefix
  or first workbook tab
PARSE A1 bounds and cap by max_rows/max_cols
ITERATE row values and format output lines
RETURN values summary
```

## 5.13 convert_excel_to_google_sheet(file_id, new_title='', move_to_parent=True)

```text
VALIDATE input
GET source file metadata and verify mime is .xlsx or .xls
TRY Drive copy conversion:
  POST /files/{id}/copy with mimeType=google-sheet
IF copy conversion fails:
  download source bytes
  upload multipart with metadata mimeType=google-sheet
RETURN created spreadsheet id + link
```

## 5.14 export_google_sheet(file_id, export_format='xlsx', gid=None, range_a1='', max_preview_chars=2000)

```text
VALIDATE input and export format
GET Drive metadata and verify file is native Google Sheet
DOWNLOAD export bytes:
  csv/tsv with gid -> docs export endpoint
  others -> Drive export endpoint
IF text format (csv/tsv):
  decode payload and return bounded preview text
ELSE:
  return binary metadata summary (byte size, mime type)
```

## 5.15 batch_get_sheet_values(spreadsheet_id, ranges, ...)

```text
VALIDATE input ranges + render options
GET /values:batchGet with all ranges in one request
FOR each returned range:
  format bounded rows/cols preview
RETURN aggregated multi-range summary
```

## 5.16 batch_update_sheet_values(spreadsheet_id, updates, value_input_option='USER_ENTERED')

```text
VALIDATE input updates + option
NORMALIZE update values to strings
POST /values:batchUpdate with all range updates
RETURN totals + per-range update counters
```

## 5.17 share_spreadsheet(file_id, user_email, role='writer', send_notification=True, message='')

```text
VALIDATE email + role
GET Drive metadata and verify spreadsheet mime type
POST Drive permissions.create for target user
RETURN permission id + share link metadata
```

## 5.18 create_spreadsheet_from_template(template_file_id, new_title, destination_folder_id='')

```text
VALIDATE input
GET template Drive metadata and verify spreadsheet mime type
POST Drive files.copy with new title (+ optional destination folder)
GET copied file metadata
RETURN copied file id, type, and link
```

## 5.19 import_csv_to_sheet(spreadsheet_id, sheet_name, csv_text, overwrite=False)

```text
VALIDATE input
PARSE csv_text into row matrix
IF overwrite:
  clear target sheet range via values.clear
PUT values update starting at Sheet!A1
RETURN updated range and counters
```

## 5.20 insert_sheet_chart(spreadsheet_id, sheet_id, chart_spec)

```text
VALIDATE input and non-empty chart_spec
NORMALIZE payload into addChart request shape
POST spreadsheets.batchUpdate with addChart
RETURN chart id from reply
```

## 5.21 protect_sheet_or_range(spreadsheet_id, sheet_id=None, range_a1='', editors=[], warning_only=False)

```text
VALIDATE input (sheet_id or range_a1 required)
IF range_a1 provided:
  resolve sheet id + parse A1 to GridRange
ELSE:
  protect full sheet by sheet_id
POST spreadsheets.batchUpdate with addProtectedRange
RETURN protectedRangeId + scope details
```

## 5.22 create_pivot_table(spreadsheet_id, source_range, target_sheet, target_cell='A1', summarize_function='COUNTA')

```text
VALIDATE input and summarize function
LOAD sheet mappings to resolve source/target sheet ids
PARSE source range and target cell coordinates
BUILD basic pivotTable object:
  rows: first source column
  values: second source column when available, else first
POST spreadsheets.batchUpdate with updateCells(pivotTable)
RETURN summary + spreadsheet URL
```

## 5.23 get_spreadsheet_permissions(file_id)

```text
VALIDATE file id
GET file metadata and verify spreadsheet mime type
GET Drive permissions list
FORMAT each permission (id/type/role/principal)
RETURN permission summary
```

## 6) Runtime Entry

```text
FUNCTION run():
  mcp.run()

IF __main__:
  run()
```
