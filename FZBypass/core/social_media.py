"""Public TikTok/Facebook photo extraction for Telegram messages.

This module handles publicly accessible URLs with yt-dlp's normal extractors.
It does not attempt to defeat authentication, CAPTCHA, or access-control pages.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL


SOCIAL_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com|facebook\.com|fb\.watch|instagram\.com)/[^\s<>]+",
    re.IGNORECASE,
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".heic"}


@dataclass
class SocialMediaResult:
    source_url: str
    title: str
    files: list[Path]
    is_photo_post: bool


def find_social_urls(text: str | None) -> list[str]:
    if not text:
        return []
    return [match.rstrip(".,)]}>") for match in SOCIAL_URL_RE.findall(text)]


def _flatten_entries(info: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    pending = [info]
    while pending:
        item = pending.pop(0)
        nested = item.get("entries") if isinstance(item, dict) else None
        if nested:
            pending.extend(entry for entry in nested if isinstance(entry, dict))
        elif isinstance(item, dict):
            entries.append(item)
    return entries


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def _download_sync(url: str, root: Path) -> SocialMediaResult:
    root.mkdir(parents=True, exist_ok=True)
    output_template = str(root / "%(playlist_index|autonumber)03d-%(id)s.%(ext)s")
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": False,
        "format": "best",
        "outtmpl": output_template,
        "restrictfilenames": True,
        "ignoreerrors": False,
        "overwrites": True,
        "cachedir": False,
    }

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
        entries = _flatten_entries(info)
        is_photo_post = any(
            str(entry.get("ext", "")).lower() in IMAGE_EXTENSIONS
            or "image" in str(entry.get("format", "")).lower()
            for entry in entries
        )
        ydl.download([url])

    files = sorted(
        (path for path in root.iterdir() if path.is_file() and not path.name.endswith(".part")),
        key=lambda path: path.name,
    )
    image_files = [path for path in files if _is_image(path)]
    selected_files = image_files if image_files else files
    if not selected_files:
        raise RuntimeError("No downloadable media was found in the public post")

    title = str(info.get("title") or info.get("description") or "Social media media")
    return SocialMediaResult(url, title[:180], selected_files, is_photo_post or bool(image_files))


async def download_social_media(url: str) -> tuple[SocialMediaResult, Path]:
    """Download public media in a worker thread and return its temp directory."""
    root = Path(tempfile.mkdtemp(prefix="fzbypass-social-"))
    try:
        result = await asyncio.to_thread(_download_sync, url, root)
        return result, root
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def cleanup_social_media(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


__all__ = [
    "SocialMediaResult",
    "cleanup_social_media",
    "download_social_media",
    "find_social_urls",
]
