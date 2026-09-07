# yt-dlp API di Cloudflare Worker + Containers

## Kenapa arsitekturnya begini?

Cloudflare **Worker biasa** (V8 isolate) **tidak bisa** menjalankan proses eksternal
seperti `yt-dlp` (butuh Python + subprocess + filesystem). Yang bisa menjalankan
`yt-dlp` sungguhan adalah **Cloudflare Containers** — fitur yang menjalankan Docker
image biasa di edge Cloudflare, dikontrol lewat Worker.

Jadi:
- **Worker** (`src/index.ts`) = gateway publik: auth, validasi, routing.
- **Container** (`Dockerfile` + `main.py`) = benar-benar menjalankan `yt-dlp` via FastAPI.

## Struktur project

```
ytdlp-worker/
├── Dockerfile          # image container: python + yt-dlp + ffmpeg + FastAPI
├── requirements.txt
├── main.py             # API internal container (/info, /download, /health)
├── src/index.ts        # Worker: auth + proxy ke container
├── wrangler.jsonc       # konfigurasi Worker + Container
└── package.json
```

## Prasyarat

- Akun Cloudflare dengan **Containers** aktif (masih beta, cek dashboard billing).
- Docker terinstal di mesin lokal (untuk build image saat deploy).
- Node.js >= 18, dan `wrangler` CLI.

## Setup

```bash
npm install

# Set API key rahasia untuk autentikasi Worker
npx wrangler secret put API_KEY
```

## Jalankan lokal

```bash
npx wrangler dev
```

Wrangler akan membangun image Docker dan menjalankan container + Worker secara lokal.

## Deploy

```bash
npx wrangler deploy
```

Perintah ini akan:
1. Deploy Worker.
2. Build image dari `Dockerfile`.
3. Push image ke Cloudflare Registry & rollout container instance.

## Cara pakai API

### Cek metadata / daftar format

```bash
curl -X POST https://<your-worker>.workers.dev/info \
  -H "x-api-key: <API_KEY_kamu>" \
  -H "content-type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=XXXXXXXXXXX"}'
```

Response berisi `title`, `duration`, `thumbnail`, dan daftar `formats` dengan `format_id`
masing-masing.

### Download video (kualitas terbaik, mp4)

```bash
curl -X POST https://<your-worker>.workers.dev/download \
  -H "x-api-key: <API_KEY_kamu>" \
  -H "content-type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=XXXXXXXXXXX", "format": "best"}' \
  --output video.mp4
```

### Download audio saja (mp3)

```bash
curl -X POST https://<your-worker>.workers.dev/download \
  -H "x-api-key: <API_KEY_kamu>" \
  -H "content-type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=XXXXXXXXXXX", "format": "audio"}' \
  --output audio.mp3
```

### Download format spesifik

Pakai `format_id` dari hasil `/info`, misalnya:

```bash
curl -X POST https://<your-worker>.workers.dev/download \
  -H "x-api-key: <API_KEY_kamu>" \
  -H "content-type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=XXXXXXXXXXX", "format": "137"}' \
  --output video_137.mp4
```

## Hal-hal penting yang perlu kamu sesuaikan

1. **Pembersihan file sementara** — saat ini file hasil download disimpan di
   `/tmp/downloads/<job_id>/` dan **tidak otomatis dihapus** setelah dikirim (supaya
   `FileResponse` sempat membaca file dulu). Tambahkan job pembersihan berkala
   (mis. cron di dalam container yang menghapus folder lebih tua dari beberapa menit),
   kalau tidak disk container bisa penuh.
2. **Rate limiting / kuota** — `MAX_CONCURRENT_JOBS` di `main.py` cuma membatasi paralelisme
   di satu instance container. Untuk kuota per-user, tambahkan logic di Worker
   (misalnya pakai Cloudflare KV atau Durable Object counter).
3. **Legalitas & ToS** — mengunduh konten dari platform seperti YouTube bisa melanggar
   Terms of Service platform tersebut tergantung yurisdiksi dan tujuan penggunaan.
   Pastikan kamu punya hak/izin atas konten yang diunduh (video milik sendiri, konten
   berlisensi bebas, dsb), dan patuhi ToS platform sumber.
4. **Biaya Containers** — Containers dikenakan biaya berdasarkan waktu aktif (per 10ms slice)
   plus CPU/RAM yang dipakai. `sleepAfter = "5m"` di `src/index.ts` bikin container tidur
   otomatis kalau idle supaya hemat biaya.
5. **Update yt-dlp berkala** — YouTube sering mengubah struktur internal, jadi `yt-dlp`
   perlu di-update rutin. Sesuaikan versi di `requirements.txt` atau ganti jadi
   `yt-dlp` tanpa pin versi kalau mau selalu pakai versi terbaru saat build image.
