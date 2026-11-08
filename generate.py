#!/usr/bin/env python3
"""threads-to-other-socmed: screenshot Threads -> IG feed + Reels/TikTok.

Headless (no UI): Playwright Chromium jalan di background.

Usage:
    ./.venv/bin/python generate.py                 # process links.txt + manual/
    ./.venv/bin/python generate.py --limit 3       # hanya 3 link pertama
    ./.venv/bin/python generate.py --manual-only   # skip links.txt
    ./.venv/bin/python generate.py --links-only    # skip manual/

Inputs (folder root ini):
    links.txt        satu URL threads.com per baris.
                     Tambahkan " +comment" di belakang URL untuk mode
                     postingan + komentar (stacked).
    manual/*.txt     file teks manual (fallback render teks, tanpa screenshot);
                     baris pertama "@handle" opsional. Nama file = nama folder.

Output per konten di output/<slug>/:
    shot.png   screenshot kartu asli (avatar + username + teks + counts)
    feed.png   1080x1350 (IG feed)
    reel.mp4   1080x1920 (Reels/TikTok, slow zoom)
    caption.txt, meta.json selalu ada.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from t2s import compose as compose_mod
from t2s import render as render_mod
from t2s import shot as shot_mod
from t2s import video as video_mod

CFG = render_mod.CFG


def slugify(s: str, maxlen: int = 50) -> str:
    s = re.sub(r"^https?://(www\.)?threads\.com/", "", s).strip()
    s = re.sub(r"\?.*$", "", s)
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return (s[:maxlen] or "post").strip("-") or "post"


def unique_dir(base: Path) -> Path:
    if not base.exists():
        return base
    i = 2
    while (cand := base.parent / f"{base.name}-{i}").exists():
        i += 1
    return cand


def read_links() -> list[tuple[str, bool]]:
    """Return [(url, with_comment)]."""
    p = ROOT / "links.txt"
    if not p.exists():
        return []
    out = []
    for ln in p.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        with_comment = ln.endswith("+comment")
        url = ln[: -len("+comment")].strip() if with_comment else ln
        out.append((url, with_comment))
    return out


def read_manual() -> list[dict]:
    items = []
    d = ROOT / "manual"
    if not d.exists():
        return []
    for f in sorted(d.glob("*.txt")):
        raw = f.read_text().strip()
        if not raw:
            continue
        lines = raw.splitlines()
        author = "@threads"
        if lines and re.match(r"^@[\w.]+$", lines[0].strip()):
            author = lines[0].strip()
            raw = "\n".join(lines[1:]).strip()
        items.append({"author": author, "text": raw, "source": f.name})
    return items


def write_caption(out_dir: Path, quote: str, author: str, url: str = ""):
    tags = CFG.get("hashtags", "")
    quote = quote if len(quote) <= 2200 else quote[:2200].rsplit(" ", 1)[0] + "..."
    cap = f'-{author}\n\n"{quote}"\n{url}\n\n.\n.\n.\n{tags}\n'
    (out_dir / "caption.txt").write_text(cap)


def build_from_shot(out_dir: Path, shot_png: Path, quote: str,
                    author: str, url: str) -> dict:
    """shot.png -> feed.png + reel.mp4. Returns meta bits."""
    compose_mod.feed_from_shot(shot_png, out_dir / "feed.png")
    frame = compose_mod.reel_frame_from_shot(shot_png, out_dir / "_frame.png")
    try:
        from PIL import Image
        im = Image.open(shot_png)
        n_words = max(1, len(quote.split()))
        dur = min(CFG.get("video_max_sec", 15),
                  max(CFG.get("video_min_sec", 6),
                       n_words * CFG.get("video_secs_per_word", 0.12)))
        video_mod.build_reel(frame, out_dir / "reel.mp4", dur, CFG)
    finally:
        frame.unlink(missing_ok=True)
    write_caption(out_dir, quote, author, url)
    return {"feed": ["feed.png"], "reel": "reel.mp4",
            "reel_duration_sec": round(dur, 2)}


def process_manual(author: str, text: str, slug: str) -> Path:
    out_dir = unique_dir(ROOT / "output" / slug)
    out_dir.mkdir(parents=True)
    text = render_mod.clean_text(text)
    feed_paths = render_mod.render_feed(author, text, out_dir / "feed.png")
    frame = render_mod.render_reel_frame(author, text, out_dir / "_frame.png")
    dur = video_mod.frame_duration_sec(text, CFG)
    video_mod.build_reel(frame, out_dir / "reel.mp4", dur, CFG)
    frame.unlink(missing_ok=True)
    write_caption(out_dir, text, author)
    (out_dir / "meta.json").write_text(json.dumps({
        "author": author, "source": "manual",
        "feed": [p.name for p in feed_paths], "reel": "reel.mp4",
        "reel_duration_sec": round(dur, 2),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }, indent=2, ensure_ascii=False))
    return out_dir


def main() -> int:
    ap = argparse.ArgumentParser(description="Threads -> IG feed + Reels/TikTok")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--manual-only", action="store_true")
    ap.add_argument("--links-only", action="store_true")
    args = ap.parse_args()

    done, failed = 0, 0

    if not args.manual_only:
        jobs = read_links()
        if args.limit:
            jobs = jobs[: args.limit]
        if jobs:
            print(f"[shot] {len(jobs)} link (headless browser, background)...")
            outs = [(u, ROOT / "output" / f".tmp-{slugify(u)}" / "shot.png", c)
                    for u, c in jobs]
            for _, tmp, _ in outs:
                tmp.parent.mkdir(parents=True, exist_ok=True)
            ok = shot_mod.screenshot_many(
                [(u, o, c) for u, o, c in outs],
                card_width=int(CFG.get("card_width", 0) or 0))
            for (url, with_comment), (_, tmp, _) in zip(jobs, outs):
                slug = slugify(url) + ("-comment" if with_comment else "")
                res = ok.get(url, {})
                if not res.get("ok"):
                    print(f"  ! skip {slug}")
                    failed += 1
                    try:
                        tmp.parent.rmdir()
                    except OSError:
                        pass
                    continue
                out_dir = unique_dir(ROOT / "output" / slug)
                out_dir.mkdir(parents=True)
                shot_png = out_dir / "shot.png"
                tmp.rename(shot_png)
                try:
                    tmp.parent.rmdir()
                except OSError:
                    pass
                print(f"[build] {slug}")
                try:
                    quote = res.get("text") or shot_mod.shortcode_of(url) or ""
                    author = res.get("author") or "@threads"
                    meta = build_from_shot(out_dir, shot_png, quote,
                                            author, url)
                    (out_dir / "meta.json").write_text(json.dumps({
                        "source_url": url, "mode": "shot",
                        "with_comment": with_comment, **meta,
                        "created_at": datetime.now().isoformat(
                            timespec="seconds"),
                    }, indent=2, ensure_ascii=False))
                except Exception as e:  # noqa: BLE001
                    print(f"  ! gagal build: {e}")
                    failed += 1
                    continue
                print(f"  -> {out_dir.relative_to(ROOT)}")
                done += 1

    if not args.links_only:
        for m in read_manual():
            slug = slugify(Path(m["source"]).stem)
            print(f"[manual] {slug}")
            try:
                d = process_manual(m["author"], m["text"], slug)
            except Exception as e:  # noqa: BLE001
                print(f"  ! gagal render: {e}")
                failed += 1
                continue
            print(f"  -> {d.relative_to(ROOT)}")
            done += 1

    print(f"\nSelesai: {done} ok, {failed} gagal -> output/")
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
