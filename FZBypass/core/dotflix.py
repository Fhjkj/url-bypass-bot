import re
from dataclasses import dataclass

from aiohttp import ClientSession, ClientTimeout

from FZBypass.core.exceptions import DDLException


@dataclass
class DotflixResult:
    filename: str
    size: str
    providers: list[tuple[str, str]]


def _value(html: str, key: str) -> str | None:
    pattern = rf'\\?"{re.escape(key)}\\?"\s*:\s*\\?"([^"\\]+)'
    match = re.search(pattern, html)
    return match.group(1).replace('\\/', '/') if match else None


def _number(html: str, key: str) -> int | None:
    pattern = rf'\\?"{re.escape(key)}\\?"\s*:\s*(\d+)'
    match = re.search(pattern, html)
    return int(match.group(1)) if match else None


async def dotflix(url: str) -> DotflixResult:
    """Extract provider links openly embedded in a public DotFlix share page."""
    timeout = ClientTimeout(total=30)
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml"}
    async with ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url, allow_redirects=True, ssl=False) as response:
            html = await response.text(errors="ignore")
            if response.status != 200:
                raise DDLException(f"DotFlix returned HTTP {response.status}")
            lowered = html.lower()
            if any(marker in lowered for marker in ("cloudflare", "captcha", "just a moment", "verify you are human")):
                raise DDLException("DotFlix Cloudflare/CAPTCHA challenge detected")

    filename = _value(html, "filename") or "Unknown file"
    size = _value(html, "formattedFileSize") or "Unknown size"
    provider_keys = (
        ("FSL Server", "cloudflareFileUrl"),
        ("10Gbps Server", "directUrl"),
        ("Transfer iT", "alternateTransferLink"),
        ("Pixeldrain", "pixeldrainLink"),
        ("VikingFile", "vikingfileLink"),
        ("Telegram Link", "telegramUrl"),
    )
    providers = []
    links = []
    for label, key in provider_keys:
        value = _value(html, key)
        if value and value.startswith(("http://", "https://")) and value not in links:
            links.append(value)
            providers.append((label, value))
    if not links:
        raise DDLException("DotFlix provider links were not exposed in the public share page")
    return DotflixResult(filename=filename, size=size, providers=providers)
