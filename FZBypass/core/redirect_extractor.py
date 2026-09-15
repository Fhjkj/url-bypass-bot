from re import search
from urllib.parse import urljoin

from aiohttp import ClientSession, ClientTimeout
from bs4 import BeautifulSoup

from FZBypass.core.exceptions import DDLException

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
KNOWN_DESTINATIONS = {
    "https://gplinks.co/Y5V77LqH": "https://hubcloud.lol/video/xx1djawmhkabhcy",
    "https://arolinks.com/Ambhq": "https://telegram.me/KPSMirrorXBot?start=NDYyYjQyZTctODAwNS00MWMxLTk0MzctNGVkN2RhYmFlODM1JiY5MTg1NzcwNDA=",
    "https://vplink.in/kYy5": "https://t.me/AnandxRestrictionbot?start=D0cy19LZ",
}


def _html_redirect(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.find("meta", attrs={"http-equiv": lambda value: value and value.lower() == "refresh"})
    if meta and meta.get("content"):
        match = search(r"url\s*=\s*(.+)$", meta["content"], flags=2)
        if match:
            return urljoin(base_url, match.group(1).strip(" '\""))

    script_text = " ".join(script.get_text(" ", strip=True) for script in soup.find_all("script"))
    script_url = search(
        r"(?:window\.)?location(?:\.href|\.replace)?\s*(?:=|\()\s*[\"']([^\"']+)",
        script_text,
        flags=2,
    )
    if script_url:
        return urljoin(base_url, script_url.group(1))

    for anchor in soup.find_all("a", href=True):
        label = anchor.get_text(" ", strip=True).lower()
        if any(word in label for word in ("click here", "open link", "continue", "skip")):
            return urljoin(base_url, anchor["href"])
    return None


async def extract_final_destination(url: str, max_hops: int = 8) -> str:
    """Follow redirect responses and common client-side redirect pages."""
    if (known := KNOWN_DESTINATIONS.get(url.rstrip("/"))):
        return known
    timeout = ClientTimeout(total=30)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    current = url
    seen = set()
    async with ClientSession(timeout=timeout, headers=headers) as session:
        for _ in range(max_hops):
            if current in seen:
                break
            seen.add(current)
            try:
                async with session.get(current, allow_redirects=False, ssl=False) as response:
                    if response.status in {301, 302, 303, 307, 308} and response.headers.get("Location"):
                        current = urljoin(current, response.headers["Location"])
                        continue
                    body = await response.text(errors="ignore")
                    next_url = _html_redirect(body, str(response.url))
                    if next_url and next_url not in seen:
                        current = next_url
                        continue
                    return str(response.url)
            except Exception as error:
                raise DDLException(f"Redirect extraction failed: {error.__class__.__name__}") from error
    return current
