"""Public Instagram/TikTok/Facebook media extraction for Telegram messages.

This module handles publicly accessible media with yt-dlp and a metadata
fallback for TikTok photo posts. It does not defeat authentication, CAPTCHA,
Turnstile, or other access-control pages. Proxies are read only from runtime
environment variables and are used as normal transport fallbacks.
"""
from __future__ import annotations

import asyncio
import html
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from yt_dlp import YoutubeDL

from FZBypass.core.proxy_pool import configured_proxies


SOCIAL_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:tiktok\.com|vt\.tiktok\.com|vm\.tiktok\.com|facebook\.com|fb\.watch|instagram\.com)/[^\s<>]+",
    re.IGNORECASE,
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".heic"}
EMBEDDED_URL_RE = re.compile(r"https?://[^\s\"'<>\\]+", re.IGNORECASE)
CHALLENGE_MARKERS = (
    "captcha",
    "turnstile",
    "verify you are human",
    "checking your browser",
    "just a moment",
    "enable javascript and cookies",
)


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


def _proxy_options(proxy: str | None) -> dict[str, str] | None:
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def _candidate_proxies() -> list[str | None]:
    configured = configured_proxies()
    proxy_only = os.getenv("SOCIAL_PROXY_ONLY", "true").lower() in {"1", "true", "yes", "on"}
    if proxy_only:
        if not configured:
            raise RuntimeError("SOCIAL_PROXY_ONLY is enabled but no BYPASS_PROXY_POOL/BYPASS_PROXY_URL is configured")
        return configured
    # Direct access is the default; configured runtime proxies are fallbacks.
    return [None, *configured]


def _yt_dlp_download(url: str, root: Path, proxy: str | None, progress: dict[str, float] | None = None) -> SocialMediaResult:
    output_template = str(root / "%(autonumber)03d-%(id)s.%(ext)s")
    is_instagram = "instagram.com" in url.lower()

    def progress_hook(status: dict[str, Any]) -> None:
        if progress is None:
            return
        if status.get("status") == "downloading":
            downloaded = status.get("downloaded_bytes") or 0
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            if total:
                progress["percent"] = max(0.0, min(99.0, downloaded * 100.0 / total))
        elif status.get("status") == "finished":
            progress["percent"] = max(progress.get("percent", 0.0), 99.0)

    options = {
        "quiet": True,
        "no_warnings": True,
        # A Reel/post URL must produce one video, not a playlist/archive.
        "noplaylist": is_instagram,
        "format": "bestvideo*+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "restrictfilenames": True,
        "ignoreerrors": False,
        "overwrites": True,
        "cachedir": False,
        "socket_timeout": int(os.getenv("SOCIAL_SOCKET_TIMEOUT_SECONDS", "20")),
        "retries": 1,
        "fragment_retries": 1,
        "progress_hooks": [progress_hook],
    }
    if proxy:
        options["proxy"] = proxy

    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
        entries = _flatten_entries(info)
        is_photo_post = any(
            str(entry.get("ext", "")).lower() in IMAGE_EXTENSIONS
            or "image" in str(entry.get("format", "")).lower()
            for entry in entries
        )
        ydl.download([url])

    if progress is not None:
        progress["percent"] = 100.0
    return _result_from_files(url, root, info, is_photo_post)


def _result_from_files(url: str, root: Path, info: dict[str, Any], is_photo_post: bool) -> SocialMediaResult:
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


def _normalise_embedded_text(body: str) -> str:
    return html.unescape(body).replace("\\/", "/").replace("\\u002F", "/").replace("\\u0026", "&")


def _embedded_image_urls(body: str) -> list[str]:
    text = _normalise_embedded_text(body)
    urls: list[str] = []
    seen: set[str] = set()
    for match in EMBEDDED_URL_RE.findall(text):
        candidate = match.replace("\\u003F", "?").replace("\\u003D", "=").replace("\\u0026", "&")
        parsed = urlparse(candidate)
        host = parsed.netloc.lower()
        path = parsed.path.lower()
        is_image_cdn = any(
            marker in host or marker in path
            for marker in ("tiktokcdn", "muscdn", "ibytedtos", "instagram", "fbcdn", "photo", "image")
        )
        if not is_image_cdn:
            continue
        if candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    return urls


def _extension_from_response(response: requests.Response, image_url: str) -> str:
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    by_type = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/avif": ".avif"}
    if content_type in by_type:
        return by_type[content_type]
    suffix = Path(urlparse(image_url).path).suffix.lower()
    return suffix if suffix in IMAGE_EXTENSIONS else ".jpg"


def _metadata_photo_download(url: str, root: Path, proxy: str | None, progress: dict[str, float] | None = None) -> SocialMediaResult:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }
    response = requests.get(url, headers=headers, proxies=_proxy_options(proxy), timeout=30, allow_redirects=True)
    body = response.text
    lowered = body.lower()
    if response.status_code in {401, 403, 429} or any(marker in lowered for marker in CHALLENGE_MARKERS):
        raise RuntimeError("The public page requires verification or is blocked")
    response.raise_for_status()

    image_urls = _embedded_image_urls(body)
    if not image_urls:
        raise RuntimeError("No public image metadata was found in the post")

    root.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    image_candidates = image_urls[:50]
    for index, image_url in enumerate(image_candidates, start=1):
        image_response = requests.get(
            image_url,
            headers={"User-Agent": headers["User-Agent"], "Referer": response.url},
            proxies=_proxy_options(proxy),
            timeout=30,
        )
        if image_response.status_code != 200 or not image_response.content:
            continue
        destination = root / f"{index:03d}-photo{_extension_from_response(image_response, image_url)}"
        destination.write_bytes(image_response.content)
        downloaded.append(destination)
        if progress is not None:
            progress["percent"] = min(99.0, index * 100.0 / max(1, len(image_candidates)))

    if not downloaded:
        raise RuntimeError("The public page exposed no downloadable images")
    if progress is not None:
        progress["percent"] = 100.0
    return SocialMediaResult(response.url, "Social media photos", downloaded, True)


def _download_sync(url: str, root: Path, progress: dict[str, float] | None = None) -> SocialMediaResult:
    last_error: Exception | None = None
    is_tiktok = "tiktok.com" in url.lower()
    for proxy in _candidate_proxies():
        try:
            if not is_tiktok:
                return _yt_dlp_download(url, root, proxy, progress)
            try:
                return _yt_dlp_download(url, root, proxy, progress)
            except Exception as error:
                last_error = error
                return _metadata_photo_download(url, root, proxy, progress)
        except Exception as error:
            last_error = error
            for path in root.iterdir():
                if path.is_file():
                    path.unlink(missing_ok=True)
    raise RuntimeError(str(last_error) if last_error else "No downloadable media was found")


async def download_social_media(url: str, progress: dict[str, float] | None = None) -> tuple[SocialMediaResult, Path]:
    root = Path(tempfile.mkdtemp(prefix="fzbypass-social-"))
    try:
        result = await asyncio.to_thread(_download_sync, url, root, progress)
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
