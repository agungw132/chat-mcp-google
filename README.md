# Sumopod AI Chat (Gradio + MCP Gmail/Calendar/Contacts)

Aplikasi chat berbasis Gradio yang menghubungkan LLM ke 3 MCP server:
- Gmail (IMAP/SMTP)
- Google Calendar (CalDAV)
- Google Contacts (CardDAV)

App mendukung dua backend model:
- Gemini langsung (`google-generativeai`)
- OpenAI-compatible endpoint (`BASE_URL` + `API_KEY`)

## Fitur

- Chat UI interaktif via Gradio.
- Tool-calling otomatis ke MCP Gmail, Calendar, Contacts.
- Pilih model langsung dari dropdown.
- Retry pesan terakhir dan clear chat.
- Logging detail ke `chat_app.log`.
- Metrik request ke `metrics.jsonl`.

## Arsitektur

Alur `chat_service`:
1. Jalankan 3 MCP server via stdio (`uv run python <server>.py`).
2. Ambil schema tools tiap server.
3. Kirim prompt ke model terpilih.
4. Saat model meminta tool, jalankan tool MCP terkait.
5. Kirim hasil tool kembali ke model hingga jawaban final.

## Struktur Repo (Refactor)

- `app.py`: entrypoint UI (wrapper, backward-compatible).
- `gmail_server.py`: wrapper entrypoint MCP Gmail.
- `calendar_server.py`: wrapper entrypoint MCP Calendar.
- `contacts_server.py`: wrapper entrypoint MCP Contacts.
- `src/chat_google/chat_service.py`: orchestration chat + tool-calling.
- `src/chat_google/ui.py`: komponen dan wiring Gradio.
- `src/chat_google/constants.py`: daftar model + system prompts.
- `src/chat_google/models.py`: model validasi berbasis Pydantic (settings, message, metrics, server config).
- `src/chat_google/mcp_servers/gmail_server.py`: implementasi tools Gmail.
- `src/chat_google/mcp_servers/calendar_server.py`: implementasi tools Calendar.
- `src/chat_google/mcp_servers/contacts_server.py`: implementasi tools Contacts.
- `tests/`: test unit komprehensif semua tools + flow chat.
- `requirements.txt`: dependency runtime.
- `requirements-dev.txt`: dependency runtime + test.
- `pyproject.toml`: konfigurasi pytest.

## Prasyarat

- Python 3.10+
- `uv` terpasang dan ada di PATH.
- Akun Google dengan 2-Step Verification + App Password.

## Panduan Mendapatkan Google App Key (Akun Personal)

Google App Key = Google App Password (16 karakter) yang dipakai untuk `GOOGLE_APP_KEY`.

1. Login ke akun Google personal Anda di `https://myaccount.google.com/`.
2. Buka menu `Security`.
3. Aktifkan `2-Step Verification` jika belum aktif.
4. Buka halaman App Passwords: `https://myaccount.google.com/apppasswords`.
5. Pada pilihan app/device:
   - App: pilih `Mail` (atau `Other (Custom name)` lalu isi misalnya `Sumopod Chat`).
   - Device: pilih device yang sesuai (atau custom).
6. Klik `Generate`.
7. Salin password 16 karakter yang muncul, lalu isi ke `.env`:
   - `GOOGLE_ACCOUNT=alamatgmailanda@gmail.com`
   - `GOOGLE_APP_KEY=<16-char-app-password>`

Catatan penting:
- App Password hanya muncul jika 2-Step Verification aktif.
- Opsi App Password bisa tidak muncul untuk akun Workspace yang dibatasi admin, akun dengan Advanced Protection, atau konfigurasi 2SV tertentu (mis. security key only).
- Saat password akun Google utama diubah, App Password biasanya ikut dicabut dan perlu generate ulang.

## Environment

Gunakan `.env.template` sebagai starter config:

```powershell
Copy-Item .env.template .env
```

Lalu edit nilai di `.env` sesuai akun dan API key Anda.

Buat `.env` di root:

```env
GOOGLE_ACCOUNT=you@example.com
GOOGLE_APP_KEY=xxxxxxxxxxxxxxxx
GOOGLE_GEMINI_API_KEY=your_gemini_key
BASE_URL=https://ai.sumopod.com
API_KEY=your_api_key
MODEL=gemini-3-flash-preview
```

Keterangan:
- `GOOGLE_ACCOUNT` + `GOOGLE_APP_KEY` dipakai oleh semua MCP server.
- Model `gemini*` menggunakan `GOOGLE_GEMINI_API_KEY`.
- Model non-Gemini menggunakan `BASE_URL` + `API_KEY`.

## Menjalankan App

```powershell
python app.py
```

Default URL Gradio: `http://127.0.0.1:7860`.

## Menjalankan MCP Server Manual

```powershell
python gmail_server.py
python calendar_server.py
python contacts_server.py
```

## Daftar Tools MCP

### Gmail
- `list_recent_emails(count=5)`
- `read_email(email_id)`
- `summarize_emails(timeframe='24h', label='inbox', count=10)`
- `list_unread_emails(count=5)`
- `mark_as_read(email_id)`
- `list_labels()`
- `search_emails_by_label(label, count=5)`
- `search_emails(query)`
- `send_email(to_email, subject, body)`

### Calendar
- `summarize_agenda(timeframe='24h', days=None)`
- `list_events(days=7)`
- `add_event(summary, start_time, duration_minutes=60, description='')`
- `search_events(query)`

### Contacts
- `list_contacts(limit=10)`
- `search_contacts(query)`

## Testing (Comprehensive)

Install dependency test dan jalankan seluruh suite dengan `uv`:

```powershell
uv run --with pytest --with pytest-asyncio --with-requirements requirements.txt pytest -q
```

Cakupan test saat ini:
- `tests/test_gmail_server.py`: semua tool Gmail (9 tool), termasuk path sukses/error utama.
- `tests/test_calendar_server.py`: semua tool Calendar (4 tool), termasuk fallback saat kalender tidak tersedia.
- `tests/test_contacts_server.py`: semua tool Contacts (2 tool), termasuk parsing CardDAV dan no-match.
- `tests/test_chat_service.py`: flow utama `chat()` untuk:
  - empty message
  - sanitasi schema
  - Gemini missing key
  - Gemini tool-call roundtrip
  - OpenAI-compatible non-200
  - OpenAI-compatible tool-call + streaming

Catatan implementasi:
- `chat_service` memakai Pydantic untuk validasi input internal:
  - runtime env settings
  - history message shape
  - MCP server config
  - metrics record sebelum ditulis ke `metrics.jsonl`
- Semua tool MCP juga memakai Pydantic untuk validasi argumen input (mis. `count`, `days`, `duration_minutes`, `query`, `email_id`).

Hasil terakhir:
- `27 passed`.

## Logging & Metrics

- `chat_app.log`: log proses dan error.
- `metrics.jsonl`: metrik per request (timestamp, model, duration, tools/server yang dipanggil, status).

## Troubleshooting

1. MCP tidak kebaca tools
- Pastikan `uv` tersedia.
- Cek dependency runtime terpasang.
- Jalankan server manual (perintah di atas).

2. Gagal autentikasi Google
- Pastikan App Password valid.
- Pastikan 2-Step Verification aktif.

3. Model Gemini gagal
- Cek `GOOGLE_GEMINI_API_KEY`.
- Jika kuota habis, gunakan model non-Gemini.

4. Model non-Gemini gagal
- Cek `BASE_URL` + `API_KEY`.
- Pastikan endpoint support tool-calling.

## Keamanan

- `.env`, `chat_app.log`, `metrics.jsonl` sudah sebaiknya di-ignore git.
- App memiliki akses ke email, kalender, dan kontak asli Anda.
