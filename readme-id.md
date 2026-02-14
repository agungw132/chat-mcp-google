# Dokumentasi (Ringkas - Bahasa Indonesia)

Dokumentasi utama proyek ini menggunakan bahasa Inggris dan selalu diperbarui di:
- `README.md`

File ini adalah ringkasan cepat dalam bahasa Indonesia.

## Ringkasan Aplikasi

Chat app berbasis Gradio yang terhubung ke MCP server:
- Gmail
- Google Calendar
- Google Contacts
- Google Drive
- Google Docs
- Google Maps

Mendukung:
- Model Gemini (`google-genai`)
- Model OpenAI-compatible (melalui `BASE_URL` + `API_KEY`)

## Update Penting Terbaru

- Default model fallback: `azure_ai/kimi-k2.5`
- Multi-round tool calls untuk model non-Gemini
- Intent-based tool gating (tool yang dikirim ke model difilter sesuai domain intent prompt)
- Ringkasan policy MCP dari `docs/mcp-servers/*.md` sekarang diinjeksi ke system prompt runtime
- Kontrak hasil tool terstruktur (`success`, `error`, `data`) untuk orkestrasi yang lebih stabil
- Penanganan timeout dan retry yang lebih baik
- Auto-invite flow: jika prompt berisi `invite` + email dan event berhasil dibuat
- Auto-invite flow: sistem mengirim undangan via Gmail MCP
- Auto-invite flow: prioritas `send_calendar_invite_email` (ICS `text/calendar`, bisa accept/reject)
- Auto-invite flow: fallback ke `send_email` plain text

## Menjalankan Aplikasi

```powershell
Copy-Item .env.template .env
uv sync
uv run python app.py
```

## Catatan Konfigurasi

- Contoh starter config: `.env.template`
- Nilai default model di template: `MODEL=azure_ai/kimi-k2.5`
- Drive sekarang mendukung auto-refresh token via:
  - `GOOGLE_DRIVE_REFRESH_TOKEN`
  - `GOOGLE_OAUTH_CLIENT_ID`
  - `GOOGLE_OAUTH_CLIENT_SECRET`
- Gunakan script `get_google_drive_access_token.py` untuk isi access token + refresh token + OAuth client credentials sekaligus.
- Untuk Google Maps, lihat `README.md` section `How to Get GOOGLE_MAPS_API_KEY and Required APIs`.
- API minimal yang harus aktif: `Geocoding API`, `Directions API`, `Places API`.
- Tersedia script programatik: `get_google_maps_api_key.py` (lihat contoh command di `README.md`).

## Troubleshooting Ringkas

1. Error Gemini (`429`/quota, `503`, dll): cek `GOOGLE_GEMINI_API_KEY`, jika quota habis coba model non-Gemini, untuk error sementara coba ulang prompt.
2. Error non-Gemini (`500`/timeout): cek `BASE_URL` dan `API_KEY`, lalu coba prompt lebih sempit jika sering timeout.
3. Invite tidak terkirim: gunakan kata `invite` + email di prompt, lalu cek `chat_app.log`/`metrics.jsonl` apakah `send_calendar_invite_email` atau `send_email` terpanggil.
4. Drive `401/403`: cek `GOOGLE_DRIVE_ACCESS_TOKEN`/refresh config valid, dan scope token mencakup `https://www.googleapis.com/auth/drive`.
5. Maps gagal: cek `GOOGLE_MAPS_API_KEY` valid dan Maps APIs sudah di-enable di Google Cloud.
6. Gmail/Calendar/Contacts gagal login: cek `GOOGLE_ACCOUNT` dan `GOOGLE_APP_KEY`, pastikan 2-Step Verification + App Password sudah aktif.
7. Muncul warning MCP server unavailable: cek `chat_app.log` (`Failed to start MCP server`), jalankan server terkait manual, lalu retry query.

## Referensi Lengkap

Untuk daftar tools, arsitektur, troubleshooting, dan changelog terbaru, lihat:
- `README.md`
- `CHANGELOG.md`
- `docs/mcp-servers/README.md` (panduan per MCP untuk calling agent)
- `docs/mcp-servers/docs.md` (panduan MCP Google Docs)
