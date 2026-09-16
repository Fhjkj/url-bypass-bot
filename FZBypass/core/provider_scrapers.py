import re
from dataclasses import dataclass
from html import unescape

from aiohttp import ClientSession, ClientTimeout
from bs4 import BeautifulSoup

from FZBypass.core.exceptions import DDLException


@dataclass
class ProviderFileResult:
    filename: str
    size: str
    links: list[tuple[str, str]]


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
    timeout = ClientTimeout(total=30)
    async with ClientSession(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as session:
        async with session.get(url, allow_redirects=True, ssl=False) as response:
            html = await response.text(errors="ignore")
            if response.status != 200:
                raise DDLException(f"FileBee returned HTTP {response.status}")
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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": url,
    }
    async with ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url, allow_redirects=True, ssl=False) as response:
            html = await response.text(errors="ignore")
            if response.status != 200:
                raise DDLException(f"GDFlix returned HTTP {response.status}")
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
        href = anchor["href"]
        label = anchor.get_text(" ", strip=True)
        if href.startswith(("http://", "https://")) and any(word in label.lower() for word in ("instant", "download", "gofile", "telegram")):
            if (label, href) not in links:
                links.append((label or "Download", href))
    if not links:
        raise DDLException("GDFlix metadata loaded but no public download links were exposed")
    return ProviderFileResult(filename, size, links)


async def hubcloud(url: str) -> ProviderFileResult:
    timeout = ClientTimeout(total=30)
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml"}
    async with ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url, allow_redirects=True, ssl=False) as response:
            html = await response.text(errors="ignore")
            if response.status != 200:
                raise DDLException(f"HubCloud returned HTTP {response.status}")
        generation = re.search(r"var\s+url\s*=\s*'([^']+)'", html)
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
            name = label or "Download"
        else:
            continue
        if (name, href) not in links:
            links.append((name, href))
    if not links:
        raise DDLException("HubCloud metadata loaded but no public provider links were exposed")
    return ProviderFileResult(title, size, links)
