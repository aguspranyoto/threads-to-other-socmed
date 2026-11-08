# threads-to-other-socmed

Screenshot Threads -> konten IG Feed + Reels/TikTok. Headless (Playwright jalan di background, tanpa UI).

## Cara pakai

1. Isi `links.txt` — satu URL threads.com per baris.
   Tambah `+comment` di belakang URL untuk mode postingan + komentar:

   ```
   https://www.threads.com/@user/post/XXXX
   https://www.threads.com/@user/post/YYYY +comment
   ```

2. Jalanin:

   ```
   ./.venv/bin/python generate.py
   ```

   Opsi: `--limit N` (coba N link pertama), `--links-only`, `--manual-only`.

3. Fallback manual: taro file `.txt` di `manual/` (baris pertama `@handle` opsional, sisanya isi thread).

## Output

Tiap konten jadi satu folder di `output/<slug>/`:

| File | Isi |
|---|---|
| `shot.png` | screenshot kartu Threads asli (dark, avatar + username + teks + counts) |
| `feed.png` | 1080x1080 (1:1), kartu di atas kanvas putih |
| `reel.mp4` | 1080x1920 H.264, kartu di atas kanvas putih + slow zoom |
| `caption.txt` | teks postingan + link + hashtag, siap copas |
| `meta.json` | metadata |

Hashtag dll diatur di `theme.json`.
