import re
from dataclasses import dataclass
from html import unescape
from json import loads
from urllib.parse import urljoin, urlparse, urlunparse

from aiohttp import ClientSession, ClientTimeout
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

from FZBypass.core.exceptions import DDLException
from FZBypass.core.proxy_pool import configured_proxies


@dataclass
class ProviderFileResult:
    filename: str
    size: str
    links: list[tuple[str, str]]


async def _get_html(session, url: str, **kwargs):
    request_kwargs = dict(kwargs)
    request_kwargs.setdefault("timeout", ClientTimeout(total=30))
    async with session.get(url, **request_kwargs) as response:
        status = response.status
        html = await response.text(errors="ignore")
    if status == 403:
        last_status, last_html = status, html
        for proxy in configured_proxies():
            proxy_kwargs = dict(request_kwargs)
            proxy_kwargs["proxy"] = proxy
            proxy_kwargs["timeout"] = ClientTimeout(total=12)
            try:
                async with session.get(url, **proxy_kwargs) as response:
                    proxy_html = await response.text(errors="ignore")
                    if response.status != 403:
                        return response.status, proxy_html
                    last_status, last_html = response.status, proxy_html
            except Exception:
                continue
        return last_status, last_html
    return status, html


async def _get_gdflix_html(url: str, proxy: str | None = None):
    """Fetch GDFlix with a browser TLS fingerprint and an optional HTTP proxy."""
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": url,
    }
    async with AsyncSession(impersonate="chrome", timeout=12) as session:
        kwargs = {"allow_redirects": True, "headers": headers}
        if proxy:
            kwargs["proxies"] = {"http": proxy, "https": proxy}
        response = await session.get(url, **kwargs)
        return response.status_code, response.text


async def _get_browser_html(url: str, proxy: str | None = None):
    """Fetch an anti-bot-protected page with a Chrome-like TLS fingerprint."""
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": url,
    }
    async with AsyncSession(impersonate="chrome", timeout=12) as session:
        kwargs = {"allow_redirects": True, "headers": headers}
        if proxy:
            kwargs["proxies"] = {"http": proxy, "https": proxy}
        response = await session.get(url, **kwargs)
        return response.status_code, response.text


async def _get_filebee_api(base_url: str, file_id: str, proxy: str | None = None):
    """Read FileBee metadata from its public frontend API when accessible."""
    origin = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    endpoint = f"{origin}/api/file/video/{file_id}/"
    status, body = await _get_browser_html(endpoint, proxy=proxy)
    if status != 200:
        return status, None
    try:
        return status, loads(body)
    except ValueError:
        return status, None


def _collect_filebee_values(value):
    """Collect metadata/link strings from the API response without guessing URLs."""
    values = []
    if isinstance(value, dict):
        for item in value.values():
            values.extend(_collect_filebee_values(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_collect_filebee_values(item))
    elif isinstance(value, str):
        values.append(value)
    return values


async def tmbcloud(url: str) -> ProviderFileResult:
    timeout = ClientTimeout(total=30)
    async with ClientSession(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as session:
        async with session.get(url, allow_redirects=True, ssl=False) as response:
            html = await response.text(errors="ignore")
            if response.status != 200:
                raise DDLException(f"TMBCloud returned HTTP {response.status}")
    soup = BeautifulSoup(html, "html.parser")
    description = soup.find("meta", attrs={"name": "description"})
    text = description.get("content", "") if description else ""
    match = re.search(r"Download (.+?) \(([^)]+)\) from", text)
    filename = match.group(1).strip() if match else (soup.title.get_text(strip=True) if soup.title else "TMBCloud file")
    size = match.group(2).strip() if match else "Unknown size"
    links = []
    for anchor in soup.find_all("a", href=True):
        label = anchor.get_text(" ", strip=True)
        href = unescape(anchor["href"])
        if href.startswith(("http://", "https://")) and any(word in label.lower() for word in ("download", "telegram", "drive", "instant")):
            if (label, href) not in links:
                links.append((label or "Download", href))
    if not links:
        raise DDLException("TMBCloud metadata found but no public download links were exposed")
    return ProviderFileResult(filename, size, links)


async def filebee(url: str) -> ProviderFileResult:
    file_id = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    api_responses = []
    try:
        api_responses.append(await _get_filebee_api(url, file_id))
        if api_responses[-1][0] != 200 or not api_responses[-1][1]:
            for proxy in configured_proxies():
                result = await _get_filebee_api(url, file_id, proxy=proxy)
                api_responses.append(result)
                if result[0] == 200 and result[1]:
                    break
    except Exception:
        pass
    for status, payload in api_responses:
        if status == 200 and payload:
            values = _collect_filebee_values(payload)
            links = []
            for item in values:
                if item.startswith(("http://", "https://")) and any(
                    word in item.lower() for word in ("telegram", "index", "download")
                ):
                    links.append(("Telegram" if "telegram" in item.lower() else "Index Download", item))
            name = next((x for x in values if re.search(r"\.(?:zip|rar|7z|mkv|mp4|pdf)(?:$|\?)", x, re.I)), "FileBee file")
            if links:
                return ProviderFileResult(name, "Unknown size", list(dict.fromkeys(links)))

    status, html = await _get_browser_html(url)
    if status != 200:
        for proxy in configured_proxies():
            try:
                status, html = await _get_browser_html(url, proxy=proxy)
                if status == 200:
                    break
            except Exception:
                continue
    if status != 200:
        raise DDLException(f"FileBee returned HTTP {status} after direct/proxy attempts")
    lowered = html.lower()
    if any(marker in lowered for marker in ("cf-chl-", "just a moment...", "captcha", "verify you are human")):
        raise DDLException("FileBee scraping stopped: Cloudflare/CAPTCHA challenge detected")
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("meta", attrs={"property": "og:title"}) or soup.find("title")
    description = soup.find("meta", attrs={"name": "description"})
    raw_title = title.get("content") if title and title.name == "meta" else title.get_text(" ", strip=True) if title else "FileBee file"
    raw_desc = description.get("content", "") if description else ""
    size_match = re.search(r"(?:size|\()\s*[:\-]?\s*([\d.]+\s*(?:KB|MB|GB|TB))", raw_desc, flags=re.I)
    links = []
    for anchor in soup.find_all("a", href=True):
        href = unescape(anchor["href"])
        label = anchor.get_text(" ", strip=True) or "Download"
        if href.startswith(("http://", "https://")) and any(word in label.lower() for word in ("download", "telegram", "index")):
            links.append((label, href))
    if not links:
        raise DDLException("FileBee metadata loaded but no public download links were exposed")
    return ProviderFileResult(raw_title or "FileBee file", size_match.group(1) if size_match else "Unknown size", links)


async def toonworld_redirect(url: str) -> str:
    timeout = ClientTimeout(total=30)
    async with ClientSession(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as session:
        async with session.get(url, allow_redirects=False, ssl=False) as response:
            html = await response.text(errors="ignore")
            if response.status in {301, 302, 303, 307, 308} and response.headers.get("Location"):
                return response.headers["Location"]
    props = re.search(r'window\.__PROPS__\s*=\s*(\{.*?\});', html, flags=re.S)
    if props:
        destination = re.search(r'"destination"\s*:\s*"(https?://[^"\\]+)', props.group(1))
        if destination:
            return destination.group(1)
    raise DDLException("ToonWorld redirect destination was not exposed")


async def gdflix(url: str) -> ProviderFileResult:
    timeout = ClientTimeout(total=30)
    candidates = [url]
    parsed = urlparse(url)
    if parsed.hostname in {"gdflix.dev", "www.gdflix.dev"}:
        candidates.append(urlunparse(parsed._replace(netloc="new4.gdflix.io")))
    status, html = 0, ""
    response_url = url
    for candidate in candidates:
        status, html = await _get_gdflix_html(candidate)
        if status == 200:
            response_url = candidate
            break
        for proxy in configured_proxies():
            status, html = await _get_gdflix_html(candidate, proxy=proxy)
            if status == 200:
                response_url = candidate
                break
        if status == 200:
            break
        if status != 200:
            raise DDLException(f"GDFlix returned HTTP {status} after direct/proxy/redirect-host attempts")
    soup = BeautifulSoup(html, "html.parser")
    title_meta = soup.find("meta", attrs={"property": "og:description"})
    raw = title_meta.get("content", "") if title_meta else ""
    match = re.match(r"Download (.+?) - ([\d.]+\s*(?:KB|MB|GB|TB))$", raw, flags=re.I)
    if match:
        filename, size = match.group(1).strip(), match.group(2).strip()
    else:
        title = soup.title.get_text(" ", strip=True) if soup.title else "GDFlix file"
        filename = re.sub(r"^GDFlix\s*\|\s*", "", title, flags=re.I)
        size = "Unknown size"
    links = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(response_url, anchor["href"])
        label = anchor.get_text(" ", strip=True)
        low = label.lower()
        if href.startswith(("http://", "https://")) and any(word in low for word in ("instant", "download", "gofile", "telegram", "fast cloud", "zipdisk")):
            if (label, href) not in links:
                links.append((label or "Download", href))
    if not links:
        raise DDLException("GDFlix metadata loaded but no public download links were exposed")
    return ProviderFileResult(filename, size, links)


async def hubcloud(url: str) -> ProviderFileResult:
    timeout = ClientTimeout(total=30)
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml"}
    async with ClientSession(timeout=timeout, headers=headers) as session:
        status, html = await _get_html(session, url, allow_redirects=True, ssl=False)
        if status != 200:
            raise DDLException(f"HubCloud returned HTTP {status}")
        generation = re.search(r"var\s+url\s*=\s*'([^']+)'", html)
        if not generation:
            generation = re.search(
                r'<a[^>]+href=["\'](https?://[^"\']+(?:hubcloud\.php|hubvid)[^"\']*)',
                html,
                flags=re.I,
            )
        if generation:
            async with session.get(generation.group(1), allow_redirects=True, ssl=False) as generated:
                generated_html = await generated.text(errors="ignore")
                if generated.status == 200:
                    html = generated_html
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else "HubCloud file"
    size_node = soup.find(id="size")
    size = size_node.get_text(" ", strip=True) if size_node else "Unknown size"
    links = []
    for anchor in soup.find_all("a", href=True):
        href = unescape(anchor["href"])
        label = anchor.get_text(" ", strip=True)
        low = label.lower()
        if not href.startswith(("http://", "https://")):
            continue
        if "hubcloudreport" in href.lower() or "report" in low:
            continue
        if "pixeldrain" in href.lower() or "pixel" in low:
            name = "Pixeldrain"
        elif "telegram" in href.lower() or "telegram" in low or "/tg/" in href.lower():
            name = "TG Link"
        elif any(word in low for word in ("download", "10gbps", "server")) and "tutorial" not in low:
            name = "DL Server" if "generate direct" in low else (label or "Download")
        else:
            continue
        if (name, href) not in links:
            links.append((name, href))
    if not links:
        raise DDLException("HubCloud metadata loaded but no public provider links were exposed")
    return ProviderFileResult(title, size, links)
