import os

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from FZBypass.core.exceptions import DDLException
from FZBypass.core.turnstile_solver import solve_turnstile

INTERMEDIARY_HOST_MARKERS = (
    "hittracks.in.net",
    "skrresults.com",
    "insurance.",
    "study.",
)
CHALLENGE_MARKERS = (
    "cf-chl-",
    "cloudflare",
    "verify you are human",
    "checking your browser",
    "please verify to continue",
    "turnstile",
    "captcha",
    "recaptcha",
    "enable javascript and cookies",
    "just a moment",
)


async def extract_headless_destination(url: str, timeout_ms: int = 30000) -> str:
    """Resolve ordinary browser redirects, solving Cloudflare challenges when present.

    When a Turnstile/Cloudflare challenge is detected, the persistent Chromium
    profile is used to clear it and the resulting final URL is returned.
    """
    executable = os.getenv("CHROMIUM_PATH", "/usr/bin/chromium")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            executable_path=executable,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                await page.wait_for_timeout(1500)
            except PlaywrightTimeoutError:
                raise DDLException("Headless resolver timed out before exposing a destination")

            title = (await page.title()).lower()
            body = (await page.locator("body").inner_text(timeout=5000)).lower()
            current = page.url
            combined = f"{title}\n{body}"[:20000]
            if any(marker in combined for marker in CHALLENGE_MARKERS):
                # Solve the challenge using the persistent profile, then return
                # the final URL the challenge cleared to.
                result = await solve_turnstile(current)
                if result.success and result.final_url:
                    return result.final_url
                raise DDLException(
                    "Cloudflare/CAPTCHA challenge detected; manual verification or an authorized API is required"
                )
            hostname = (page.url.split("/", 3)[2] if "://" in page.url else "").lower()
            if any(marker in hostname for marker in INTERMEDIARY_HOST_MARKERS):
                raise DDLException(
                    "Final destination not exposed; headless page ended at an advertisement"
                )
            return current
        finally:
            await browser.close()