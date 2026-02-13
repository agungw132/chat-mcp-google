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

Mendukung:
- Model Gemini (`google-genai`)
- Model OpenAI-compatible (melalui `BASE_URL` + `API_KEY`)

## Update Penting Terbaru

- Default model fallback: `azure_ai/kimi-k2.5`
- Multi-round tool calls untuk model non-Gemini
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

## Troubleshooting Ringkas

1. Error Gemini (`429`/quota, `503`, dll): cek `GOOGLE_GEMINI_API_KEY`, jika quota habis coba model non-Gemini, untuk error sementara coba ulang prompt.
2. Error non-Gemini (`500`/timeout): cek `BASE_URL` dan `API_KEY`, lalu coba prompt lebih sempit jika sering timeout.
3. Invite tidak terkirim: gunakan kata `invite` + email di prompt, lalu cek `chat_app.log`/`metrics.jsonl` apakah `send_calendar_invite_email` atau `send_email` terpanggil.
4. Drive `401/403`: cek `GOOGLE_DRIVE_ACCESS_TOKEN` masih valid dan scope token mencakup `https://www.googleapis.com/auth/drive`.
5. Gmail/Calendar/Contacts gagal login: cek `GOOGLE_ACCOUNT` dan `GOOGLE_APP_KEY`, pastikan 2-Step Verification + App Password sudah aktif.

## Referensi Lengkap

Untuk daftar tools, arsitektur, troubleshooting, dan changelog terbaru, lihat:
- `README.md`
- `CHANGELOG.md`
