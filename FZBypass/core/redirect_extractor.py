from re import search
from urllib.parse import urljoin

from aiohttp import ClientSession, ClientTimeout
from bs4 import BeautifulSoup

from FZBypass.core.exceptions import DDLException

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
INTERMEDIARY_HOST_MARKERS = (
    "hittracks.in.net",
    "skrresults.com",
    "insurance.",
    "study.",
)


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
                    challenge_markers = (
                        "cf-chl-",
                        "cloudflare",
                        "captcha",
                        "recaptcha",
                        "enable javascript and cookies",
                    )
                    if any(marker in body.lower() for marker in challenge_markers):
                        from FZBypass.core.headless_extractor import extract_headless_destination

                        return await extract_headless_destination(current)
                    next_url = _html_redirect(body, str(response.url))
                    if next_url and next_url not in seen:
                        current = next_url
                        continue
                    final_url = str(response.url)
                    hostname = (response.url.host or "").lower()
                    if any(marker in hostname for marker in INTERMEDIARY_HOST_MARKERS):
                        raise DDLException(
                            "Final destination not exposed; shortener ended at an advertisement"
                        )
                    return final_url
            except DDLException:
                raise
            except Exception as error:
                raise DDLException(f"Redirect extraction failed: {error.__class__.__name__}") from error
    hostname = (urljoin(current, "/").split("/")[2] or "").lower()
    if any(marker in hostname for marker in INTERMEDIARY_HOST_MARKERS):
        raise DDLException("Final destination not exposed; redirect chain ended at an advertisement")
    return current
