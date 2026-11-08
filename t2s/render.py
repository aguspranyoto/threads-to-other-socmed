"""Render Threads text into IG-feed PNG (1080x1350) and Reels/TikTok frames.

Dark cinematic card style. Auto-fit font so long threads still fit.
Header shows the author's circular avatar + username.
"""
from __future__ import annotations

import re
import textwrap
import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

THIS_DIR = Path(__file__).resolve().parent
ROOT = THIS_DIR.parent


def load_cfg() -> dict:
    import json

    return json.loads((ROOT / "theme.json").read_text())


CFG = load_cfg()
AVATAR_D = int(CFG.get("avatar_diameter", 132))

EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001faff"
    "☀-➿"
    "⬀-⯿"
    "⌀-⏿"
    "️"
    "‍"
    "]+",
    flags=re.UNICODE,
)


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "")
    if CFG.get("strip_emoji"):
        text = EMOJI_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _font(path_candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in path_candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _gradient_bg(w: int, h: int) -> Image.Image:
    top = Image.new("RGB", (w, h), tuple(CFG["bg_top"]))
    bottom = Image.new("RGB", (w, h), tuple(CFG["bg_bottom"]))
    mask = Image.new("L", (1, h))
    md = ImageDraw.Draw(mask)
    for y in range(h):
        md.point((0, y), fill=int(255 * y / max(h - 1, 1)))
    return Image.composite(bottom, top, mask.resize((w, h)))


def _load_avatar(path: str | Path | None, diameter: int) -> Image.Image | None:
    """Load image file -> circular RGBA avatar. None if unreadable."""
    if not path:
        return None
    try:
        img = Image.open(path).convert("RGB")
    except Exception:
        return None
    big = diameter * 4
    img = ImageOps.fit(img, (big, big), Image.LANCZOS, centering=(0.5, 0.5))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big, big), fill=255)
    img = img.resize((diameter, diameter), Image.LANCZOS)
    mask = mask.resize((diameter, diameter), Image.LANCZOS)
    out = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        if not para.strip():
            out.append("")
            continue
        words, line = para.split(), ""
        for wd in words:
            trial = (line + " " + wd).strip()
            if draw.textlength(trial, font=font) <= max_w:
                line = trial
            else:
                if line:
                    out.append(line)
                # hard-break single too-long word
                while draw.textlength(wd, font=font) > max_w and len(wd) > 1:
                    cut = len(wd) // 2
                    while cut > 1 and draw.textlength(wd[:cut], font=font) > max_w:
                        cut -= 1
                    out.append(wd[:cut])
                    wd = wd[cut:]
                line = wd
        if line:
            out.append(line)
    return out


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_w: int,
              max_h: int) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    size = CFG["font_start_size"]
    while size >= CFG["font_min_size"]:
        font = _font(CFG["font_regular_candidates"], size)
        lines = _wrap(draw, text, font, max_w)
        lh = int(size * 1.45)
        if lh * len(lines) <= max_h or size == CFG["font_min_size"]:
            return font, lines
        size -= 4
    font = _font(CFG["font_regular_candidates"], CFG["font_min_size"])
    return font, _wrap(draw, text, font, max_w)


def _initials_avatar(handle: str, diameter: int) -> Image.Image:
    """Fallback avatar: circle with handle initial."""
    big = diameter * 4
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, big, big), fill=(58, 58, 66, 255))
    ch = (handle.lstrip("@")[:1] or "T").upper()
    f = _font(CFG["font_bold_candidates"], big // 2)
    d.text((big // 2, big // 2), ch, font=f, anchor="mm",
           fill=(235, 235, 240, 255))
    return img.resize((diameter, diameter), Image.LANCZOS)


def _draw_header(img: Image.Image, draw: ImageDraw.ImageDraw, w: int, y: int,
                 author: str, avatar_path: str | Path | None = None) -> int:
    cx = w // 2
    handle = author if author.startswith("@") else f"@{author}"
    fm = _font(CFG["font_regular_candidates"], 34)
    fb = _font(CFG["font_bold_candidates"], 46)
    draw.text((cx, y), "THREADS", font=fm, anchor="ma",
              fill=tuple(CFG["muted_color"]))
    y += 58
    av = _load_avatar(avatar_path, AVATAR_D)
    if av is None:
        av = _initials_avatar(handle, AVATAR_D)
    ax = cx - AVATAR_D // 2
    draw.ellipse((ax - 5, y - 5, ax + AVATAR_D + 5, y + AVATAR_D + 5),
                 outline=(255, 255, 255), width=3)
    img.paste(av, (ax, y), av)
    y += AVATAR_D + 26
    draw.text((cx, y), handle, font=fb, anchor="ma",
              fill=tuple(CFG["accent_color"]))
    y += 86
    return y


def _draw_footer(draw: ImageDraw.ImageDraw, w: int, h: int, page: str = ""):
    fm = _font(CFG["font_regular_candidates"], 30)
    draw.text((w // 2, h - 90), "@threads  →  repost", font=fm,
              anchor="ma", fill=tuple(CFG["muted_color"]))
    if page:
        draw.text((w - 60, h - 90), page, font=fm, anchor="ra",
                  fill=tuple(CFG["muted_color"]))


def render_feed(author: str, text: str, out_path: Path,
                max_chars_per_card: int = 1100,
                avatar_path: str | Path | None = None) -> list[Path]:
    """Render one or more feed PNGs (carousel pages if text is long).

    Returns list of PNG paths written.
    """
    text = clean_text(text)
    w, h = CFG["canvas_feed"]
    chunks = textwrap.wrap(text, max_chars_per_card,
                           break_long_words=False,
                           break_on_hyphens=False) or [""]

    paths: list[Path] = []
    base = out_path.with_suffix("")
    for i, chunk in enumerate(chunks, start=1):
        img = _gradient_bg(w, h)
        draw = ImageDraw.Draw(img)
        y = _draw_header(img, draw, w, 110, author, avatar_path)
        max_w, max_text_h = w - 160, h - y - 210
        font, lines = _fit_font(draw, chunk, max_w, max_text_h)
        lh = int(font.size * 1.45)
        total = lh * len(lines)
        yy = y + max(0, (max_text_h - total) // 2)
        for ln in lines:
            if ln == "":
                yy += lh // 2
                continue
            draw.text((w // 2, yy), ln, font=font, anchor="ma",
                      fill=tuple(CFG["text_color"]))
            yy += lh
        _draw_footer(draw, w, h,
                     page=f"{i}/{len(chunks)}" if len(chunks) > 1 else "")
        p = Path(f"{base}_p{i}.png" if len(chunks) > 1 else f"{base}.png")
        img.save(p)
        paths.append(p)
    return paths


def render_reel_frame(author: str, text: str, out_path: Path,
                      avatar_path: str | Path | None = None) -> Path:
    """Render single 1080x1920 frame used as base for the reel video."""
    text = clean_text(text)
    w, h = CFG["canvas_reel"]
    img = _gradient_bg(w, h)
    draw = ImageDraw.Draw(img)
    y = _draw_header(img, draw, w, 250, author, avatar_path)
    max_w, max_text_h = w - 160, h - y - 400
    font, lines = _fit_font(draw, text, max_w, max_text_h)
    # cap lines to keep reel readable; head + ellipsis
    lh = int(font.size * 1.45)
    max_lines = max_text_h // lh
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max(0, len(lines[-1]) - 3)] + "..."
    total = lh * len(lines)
    yy = y + max(0, (max_text_h - total) // 2)
    for ln in lines:
        if ln == "":
            yy += lh // 2
            continue
        draw.text((w // 2, yy), ln, font=font, anchor="ma",
                  fill=tuple(CFG["text_color"]))
        yy += lh
    _draw_footer(draw, w, h)
    out_path = Path(out_path)
    img.save(out_path)
    return out_path


def render_media_page(media_path: str | Path, out_path: Path,
                      canvas: tuple[int, int]) -> Path | None:
    """Cover-crop a downloaded media image onto a canvas (feed/reel size).

    Returns out_path or None if the file isn't a readable image.
    """
    try:
        img = Image.open(media_path).convert("RGB")
    except Exception:
        return None
    w, h = canvas
    img = ImageOps.fit(img, (w, h), Image.LANCZOS, centering=(0.5, 0.5))
    out_path = Path(out_path)
    img.save(out_path)
    return out_path
