"""Fetch Threads post content from a threads.com URL.

Uses the Jina reader proxy (https://r.jina.ai/<url>) which renders the
JS-heavy Threads page server-side and returns markdown.

Returns a dict:
    {"author": "@handle", "text": "...", "avatar_url": "...",
     "media_urls": [...], "url": "..."}
or None if not found.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import requests

THREADS_POST_RE = re.compile(
    r"(?:https?://)?(?:www\.)?threads\.com/@([^/]+)/post/([A-Za-z0-9_-]+)"
)

READER = "https://r.jina.ai/"
TIMEOUT = 30
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def parse_threads_url(url: str) -> tuple[str, str] | None:
    """Return (handle, shortcode) from a threads.com post URL."""
    m = THREADS_POST_RE.search(url.strip())
    if not m:
        return None
    return m.group(1), m.group(2)


def _fetch_markdown(url: str) -> str | None:
    try:
        resp = requests.get(READER + url, timeout=TIMEOUT)
        if resp.status_code != 200:
            return None
        return resp.text
    except requests.RequestException:
        return None


def _images(md: str) -> list[tuple[str, str]]:
    return re.findall(r"!\[([^\]]*)\]\((https://[^)]+)\)", md)


def _clean_text_noise(text: str) -> str:
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\(.*?\)", r"\1", text).strip()
    return text


def _parse_block(lines: list[str], idx: int, handle: str) -> dict | None:
    author = handle or _guess_author(lines, idx)

    text_parts: list[str] = []
    for ln in lines[idx + 1 : idx + 15]:
        s = ln.strip()
        if not s:
            continue
        if re.fullmatch(r"[\d,.KkMm]+", s):  # engagement numbers -> end of text
            if text_parts:
                break
            continue
        if re.search(r"threads\.com", s):
            # keep lines that link to /media (tag text like "[tag](.../media)")
            if "/media" not in s:
                continue
            s = _clean_text_noise(s)
            if not s:
                continue
        elif "](" in s:
            continue  # other links / images / headers
        text_parts.append(s)
        if len(" ".join(text_parts)) > 2000:
            break

    text = _clean_text_noise(" ".join(text_parts))
    if not text:
        return None
    at = author if author.startswith("@") or not author else f"@{author}"
    return {"author": at, "text": text}


def _guess_author(lines: list[str], idx: int) -> str:
    for j in range(max(0, idx - 4), idx):
        m = re.search(r"\[@([^]]+)\]\(https://www\.threads\.com/@([^)/]+)\)",
                      lines[j])
        if m and "/post/" not in lines[j]:
            return m.group(1)
    return ""


def _find_post_idx(lines: list[str], handle: str, shortcode: str) -> int | None:
    wanted_link = f"/@{handle}/post/{shortcode}"
    for i, ln in enumerate(lines):
        if wanted_link in ln and "/media" not in ln:
            return i
    # fallback: first post link
    for i, ln in enumerate(lines):
        if re.search(r"/@[^/)]+/post/[A-Za-z0-9_-]+", ln) and "/media" not in ln:
            return i
    return None


def _avatar_for(md: str, handle: str) -> str | None:
    """Profile-picture URL of the post author."""
    bare = handle.lstrip("@")
    for alt, url in _images(md):
        if "profile picture" in alt and bare in alt:
            return url
    for alt, url in _images(md):
        if "profile picture" in alt:
            return url
    return None


def _media_for(md: str) -> list[str]:
    """Non-avatar image URLs on this page (post attachments)."""
    seen, out = set(), []
    for alt, url in _images(md):
        if "profile picture" in alt:
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def fetch_thread(url: str, sleep_sec: float = 1.0) -> dict | None:
    """Fetch one Threads URL -> full dict or None."""
    url = url.strip().rstrip("/")
    parsed = parse_threads_url(url)
    if not parsed:
        return None
    handle, shortcode = parsed

    md = _fetch_markdown(url)
    if sleep_sec:
        time.sleep(sleep_sec)
    if not md:
        return None
    lines = md.splitlines()
    idx = _find_post_idx(lines, handle, shortcode)
    if idx is None:
        return None
    got = _parse_block(lines, idx, handle)
    if not got:
        return None

    got["url"] = url
    got["avatar_url"] = _avatar_for(md, handle)
    media = _media_for(md)

    # post attachments live on the /media subpage — fetch it too
    md_media = _fetch_markdown(url + "/media")
    if sleep_sec:
        time.sleep(sleep_sec)
    if md_media:
        for u in _media_for(md_media):
            if u not in media:
                media.append(u)
    got["media_urls"] = media
    return got


def download(url: str, dest: Path, timeout: int = 60) -> Path | None:
    """Download an image/video URL to dest. Returns dest or None."""
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": UA,
                                  "Referer": "https://www.threads.com/"})
        if r.status_code != 200 or len(r.content) < 500:
            return None
        dest = Path(dest)
        dest.write_bytes(r.content)
        return dest
    except requests.RequestException:
        return None


if __name__ == "__main__":
    import sys

    for u in sys.argv[1:]:
        got = fetch_thread(u, sleep_sec=0)
        if not got:
            print(u, "-> FAILED")
            continue
        print(u)
        print("  author:", got["author"])
        print("  text:", got["text"][:150])
        print("  avatar:", (got["avatar_url"] or "")[:80])
        print("  media:", len(got["media_urls"]))
