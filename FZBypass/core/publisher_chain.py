from base64 import b64decode
from re import findall, search
from urllib.parse import urljoin, urlparse

from aiohttp import ClientSession, ClientTimeout, ClientError
from bs4 import BeautifulSoup

from FZBypass.core.exceptions import DDLException
from FZBypass.core.destination_cache import get_cached, save_verified
from FZBypass.core.proxy_pool import configured_proxies

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
CHALLENGE_MARKERS = (
    "just a moment",
    "cf-chl-",
    "cf-ray",
    "recaptcha",
    "verify you are human",
    "enable javascript and cookies",
    "checking your browser",
    "iuam",
)
INTERMEDIARY_MARKERS = ("hittracks.in.net", "insurance.", "study.", "skrresults.com", "google.com/httpservice", "softurl.in", "aadilahmadshah.in")
SOFTURL_HOST_MARKERS = ("softurl.in", "aadilahmadshah.in")


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
    if found:
        return urljoin(base_url, found.group(1))
    for node in soup.find_all(attrs={"onclick": True}):
        found = search(r"window\.open\(\s*[\"']([^\"']+)", node.get("onclick", ""), flags=2)
        if found:
            return urljoin(base_url, found.group(1))
    return None


def _embedded_telegram(html: str, source: str) -> str | None:
    """Return a Telegram URL explicitly present in page or obfuscated ad markup."""
    candidates = [html]
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(attrs={"data-code": True}):
        raw = node.get("data-code", "")
        try:
            candidates.append(b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "ignore"))
        except Exception:
            pass
    for node in soup.find_all(attrs={"data-fallback-code": True}):
        raw = node.get("data-fallback-code", "")
        try:
            candidates.append(b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "ignore"))
        except Exception:
            pass
    for text in candidates:
        for candidate in findall(r"https?://(?:t\.me|telegram\.me)/[^\s\"'<>]+", text, flags=2):
            candidate = candidate.rstrip(".,);]")
            if _valid_final(candidate, source):
                return candidate
    return None


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
    attempts = [None, *configured_proxies()]
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
                        embedded = _embedded_telegram(body, url)
                        if embedded:
                            save_verified(url, embedded, "embedded-telegram")
                            return embedded
                        location = _location(body, str(response.url))
                        if location and location not in seen:
                            current = location
                            continue
                        if _valid_final(str(response.url), url):
                            final_url = str(response.url)
                            save_verified(url, final_url, "publisher-redirect")
                            return final_url
                        form = _form(body, str(response.url))
                        if form:
                            action, fields = form
                            host = (urlparse(str(response.url)).hostname or "").lower()
                            signed = any(key.lower() in {"token", "signature", "sign", "_token", "key"} for key in fields)
                            softurl_form = any(marker in host for marker in SOFTURL_HOST_MARKERS) and any(
                                key.lower() in {"go", "humanverification", "newwpsafelink"} for key in fields
                            )
                            if not fields or not (signed or softurl_form):
                                raise DDLException(f"Publisher chain stopped before the signed destination form at {current}")
                            async with session.post(action, data=fields, allow_redirects=False, proxy=selected_proxy, ssl=False, headers={"Referer": current, "X-Requested-With": "XMLHttpRequest"}) as submitted:
                                if submitted.headers.get("Location"):
                                    candidate = urljoin(action, submitted.headers["Location"])
                                    if _valid_final(candidate, url):
                                        save_verified(url, candidate, "publisher-form")
                                        return candidate
                                payload = await submitted.text(errors="ignore")
                                next_location = _location(payload, action)
                                if next_location and next_location not in seen:
                                    current = next_location
                                    continue
                                next_form = _form(payload, action)
                                if next_form:
                                    next_action, next_fields = next_form
                                    async with session.post(next_action, data=next_fields, allow_redirects=False, proxy=selected_proxy, ssl=False, headers={"Referer": action, "X-Requested-With": "XMLHttpRequest"}) as second_submitted:
                                        if second_submitted.headers.get("Location"):
                                            current = urljoin(next_action, second_submitted.headers["Location"])
                                            continue
                                        second_payload = await second_submitted.text(errors="ignore")
                                        second_telegram = _embedded_telegram(second_payload, url)
                                        if second_telegram:
                                            save_verified(url, second_telegram, "publisher-form-telegram")
                                            return second_telegram
                                        second_location = _location(second_payload, next_action)
                                        if second_location and second_location not in seen:
                                            current = second_location
                                            continue
                                found = search(r"(?:[\"']url[\"']|Location)\s*[:=]\s*[\"'](https?://[^\"']+)", payload, flags=2)
                                if found and _valid_final(found.group(1), url):
                                    save_verified(url, found.group(1), "publisher-form-json")
                                    return found.group(1)
                            raise DDLException(f"Publisher chain stopped before the signed destination form at {current}")
                        if any(marker in (urlparse(str(response.url)).hostname or "").lower() for marker in INTERMEDIARY_MARKERS):
                            raise DDLException(f"Publisher chain reached an intermediary article without exposing the final destination at {current}")
                        raise DDLException(f"Publisher chain stopped before the signed destination form at {current}")
        except (DDLException, ClientError, TimeoutError) as error:
            errors.append(str(error))
            continue
    if any(marker in (urlparse(url).hostname or "").lower() for marker in SOFTURL_HOST_MARKERS):
        browser_result = await _resolve_softurl_browser(url, configured_proxies())
        if browser_result:
            save_verified(url, browser_result, "softurl-playwright")
            return browser_result
    raise DDLException(errors[-1] if errors else "Publisher chain did not reach a final destination")


async def _resolve_softurl_browser(url: str, proxies: list[str]) -> str | None:
    """Resolve SoftURL with Chromium, JavaScript, cookies, timers, and authorized proxies."""
    if not proxies:
        return None
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None
    for proxy in proxies:
        browser = None
        try:
            parsed_proxy = urlparse(proxy)
            proxy_config = {"server": f"{parsed_proxy.scheme}://{parsed_proxy.hostname}:{parsed_proxy.port}"}
            if parsed_proxy.username:
                proxy_config["username"] = parsed_proxy.username
            if parsed_proxy.password:
                proxy_config["password"] = parsed_proxy.password
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    headless=True,
                    proxy=proxy_config,
                )
                context = await browser.new_context(user_agent=USER_AGENT)
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until="commit", timeout=20000)
                except Exception:
                    if not page.url or page.url == "about:blank":
                        raise
                for _ in range(60):
                    pages = list(context.pages)
                    for candidate_page in pages:
                        candidate_url = candidate_page.url
                        if re_match := search(r"https?://(?:t\.me|telegram\.me)/[^\s\"'<>]+", candidate_url, flags=2):
                            return re_match.group(0).rstrip(".,);]")
                        try:
                            html = await candidate_page.content()
                        except Exception:
                            continue
                        found = _embedded_telegram(html, url)
                        if found:
                            return found
                        for selector in ("#wpsafelinkhuman", "#image3", "#wpsafelink-landing button", "#wpsafelink-landing input[type=submit]"):
                            try:
                                control = candidate_page.locator(selector).first
                                if await control.is_visible(timeout=100):
                                    await control.click(timeout=1000)
                                    break
                            except Exception:
                                continue
                    await page.wait_for_timeout(1000)
        except Exception:
            continue
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
    return None
