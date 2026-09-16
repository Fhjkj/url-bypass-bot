from re import search
from urllib.parse import urljoin, urlparse

from aiohttp import ClientSession, ClientTimeout, ClientError
from bs4 import BeautifulSoup

from FZBypass.core.exceptions import DDLException
from FZBypass.core.destination_cache import get_cached, save_verified
from FZBypass.core.proxy_pool import next_proxy

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
CHALLENGE_MARKERS = (
    "just a moment",
    "cf-chl-",
    "cf-ray",
    "cloudflare",
    "captcha",
    "recaptcha",
    "verify you are human",
    "enable javascript and cookies",
    "checking your browser",
    "iuam",
)
INTERMEDIARY_MARKERS = ("hittracks.in.net", "skrresults.com", "insurance.", "study.", "google.com/httpservice")


def _challenge(html: str, title: str = "") -> bool:
    haystack = f"{title}\n{html[:20000]}".lower()
    return any(marker in haystack for marker in CHALLENGE_MARKERS)


def _form(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    if not form:
        return None
    action = urljoin(base_url, form.get("action") or base_url)
    fields = {}
    for item in form.find_all("input"):
        name = item.get("name")
        if name:
            fields[name] = item.get("value", "")
    return action, fields


def _location(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.find("meta", attrs={"http-equiv": lambda value: value and value.lower() == "refresh"})
    if meta and meta.get("content"):
        found = search(r"url\s*=\s*(.+)$", meta["content"], flags=2)
        if found:
            return urljoin(base_url, found.group(1).strip(" '\""))
    script = " ".join(node.get_text(" ", strip=True) for node in soup.find_all("script"))
    found = search(r"(?:window\.)?location(?:\.href|\.replace)?\s*(?:=|\()\s*[\"']([^\"']+)", script, flags=2)
    return urljoin(base_url, found.group(1)) if found else None


def _valid_final(candidate: str, source: str) -> bool:
    if not candidate or candidate == source:
        return False
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = (parsed.hostname or "").lower()
    return not any(marker in host for marker in INTERMEDIARY_MARKERS)


async def resolve_publisher_chain(url: str, max_hops: int = 8) -> str:
    """Follow ordinary redirects/forms using direct access and an authorized proxy.

    Set BYPASS_PROXY_URL only to a proxy you own or are authorized to use.
    This intentionally stops on Cloudflare/CAPTCHA pages and does not forge tokens.
    """
    if cached := get_cached(url):
        return cached
    proxy = next_proxy()
    attempts = [None] + ([proxy] if proxy else [])
    errors = []
    for selected_proxy in attempts:
        try:
            timeout = ClientTimeout(total=30)
            async with ClientSession(timeout=timeout, headers={"User-Agent": USER_AGENT}, cookie_jar=None) as session:
                current = url
                seen = set()
                for _ in range(max_hops):
                    if current in seen:
                        break
                    seen.add(current)
                    async with session.get(current, allow_redirects=False, proxy=selected_proxy, ssl=False) as response:
                        if response.status in {301, 302, 303, 307, 308} and response.headers.get("Location"):
                            current = urljoin(current, response.headers["Location"])
                            continue
                        body = await response.text(errors="ignore")
                        if _challenge(body, response.headers.get("title", "")):
                            raise DDLException("Cloudflare/CAPTCHA challenge detected; authorized browser/API required")
                        location = _location(body, str(response.url))
                        if location and location not in seen:
                            current = location
                            continue
                        form = _form(body, str(response.url))
                        if form:
                            action, fields = form
                            if not fields or not any(key.lower() in {"token", "signature", "sign", "_token", "key"} for key in fields):
                                raise DDLException(f"Publisher chain stopped before the signed destination form at {current}")
                            async with session.post(action, data=fields, allow_redirects=False, proxy=selected_proxy, ssl=False, headers={"Referer": current, "X-Requested-With": "XMLHttpRequest"}) as submitted:
                                if submitted.headers.get("Location"):
                                    candidate = urljoin(action, submitted.headers["Location"])
                                    if _valid_final(candidate, url):
                                        save_verified(url, candidate, "publisher-form")
                                        return candidate
                                payload = await submitted.text(errors="ignore")
                                found = search(r"(?:[\"']url[\"']|Location)\s*[:=]\s*[\"'](https?://[^\"']+)", payload, flags=2)
                                if found and _valid_final(found.group(1), url):
                                    save_verified(url, found.group(1), "publisher-form-json")
                                    return found.group(1)
                            raise DDLException(f"Publisher chain stopped before the signed destination form at {current}")
                        if _valid_final(str(response.url), url):
                            final_url = str(response.url)
                            save_verified(url, final_url, "publisher-redirect")
                            return final_url
                        raise DDLException(f"Publisher chain stopped before the signed destination form at {current}")
        except (DDLException, ClientError, TimeoutError) as error:
            errors.append(str(error))
            continue
    raise DDLException(errors[-1] if errors else "Publisher chain did not reach a final destination")
