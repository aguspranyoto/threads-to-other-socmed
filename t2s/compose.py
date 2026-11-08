"""Compose IG feed (1080x1080) and Reels/TikTok frame (1080x1920)
from a raw Threads card screenshot (dark card).

The card keeps its original dark look; the surrounding canvas is white.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

FEED_SIZE = (1080, 1080)
REEL_SIZE = (1080, 1920)
PAD_X = 50


def _fit_width(img: Image.Image, target_w: int) -> Image.Image:
    if img.width == target_w:
        return img
    h = round(img.height * target_w / img.width)
    return img.resize((target_w, h), Image.LANCZOS)


def _white_canvas(size: tuple[int, int]) -> Image.Image:
    return Image.new("RGB", size, (255, 255, 255))


def feed_from_shot(shot_path: str | Path, out_path: str | Path) -> Path:
    """Dark card centered on a 1080x1080 white canvas."""
    shot = Image.open(shot_path).convert("RGB")
    canvas = _white_canvas(FEED_SIZE)
    card = _fit_width(shot, FEED_SIZE[0] - PAD_X * 2)
    if card.height > FEED_SIZE[1] - PAD_X * 2:
        # very tall card -> fit by height instead
        h = FEED_SIZE[1] - PAD_X * 2
        w = round(shot.width * h / shot.height)
        card = shot.resize((w, h), Image.LANCZOS)
    canvas.paste(card, ((FEED_SIZE[0] - card.width) // 2,
                        (FEED_SIZE[1] - card.height) // 2))
    out_path = Path(out_path)
    canvas.save(out_path)
    return out_path


def reel_frame_from_shot(shot_path: str | Path,
                         out_path: str | Path) -> Path:
    """1080x1920 frame: dark card on white background."""
    shot = Image.open(shot_path).convert("RGB")
    bg = _white_canvas(REEL_SIZE)

    card = _fit_width(shot, REEL_SIZE[0] - PAD_X * 2)
    if card.height > REEL_SIZE[1] - 400:
        h = REEL_SIZE[1] - 400
        w = round(shot.width * h / shot.height)
        card = shot.resize((w, h), Image.LANCZOS)
    y = (REEL_SIZE[1] - card.height) // 2 - 120  # slightly above center
    y = max(PAD_X, y)
    bg.paste(card, ((REEL_SIZE[0] - card.width) // 2, y))
    out_path = Path(out_path)
    bg.save(out_path)
    return out_path
