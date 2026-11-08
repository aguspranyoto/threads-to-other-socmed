"""Build 1080x1920 MP4 (Reels/TikTok) from a rendered frame via slow zoompan."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def frame_duration_sec(text: str, cfg: dict) -> float:
    n_words = max(1, len(text.split()))
    secs = n_words * cfg.get("video_secs_per_word", 0.12)
    return min(cfg.get("video_max_sec", 15),
               max(cfg.get("video_min_sec", 6), secs))


def build_reel(frame_png: Path, out_mp4: Path, duration: float,
               cfg: dict) -> Path:
    """Slow zoom-in on the frame, H.264 + yuv420p for max compatibility."""
    if not _have_ffmpeg():
        raise RuntimeError("ffmpeg not found in PATH")
    fps = cfg.get("video_fps", 30)
    zoom = cfg.get("video_zoom", 0.08)
    frames = max(1, int(duration * fps))
    vf = (
        f"scale=2160:3840,"
        f"zoompan=z='min(zoom+{zoom / frames:.6f},1+{zoom})':"
        f"d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={fps}"
    )
    out_mp4 = Path(out_mp4)
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", str(frame_png),
        "-vf", vf, "-t", f"{duration:.2f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "medium", "-crf", "20",
        str(out_mp4),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{proc.stderr[-2000:]}")
    return out_mp4
