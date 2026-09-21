"""Cloudflare Turnstile / Cloudflare challenge solver using Playwright.

This module launches (or reuses) a persistent Chromium profile, navigates to a
protected page, waits for the Turnstile widget to resolve, and returns the
resulting token or clearance cookies. It is used by the /solve and
/solve-challenge Flask endpoints.
"""
import asyncio
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

from FZBypass import LOGGER

PROFILE_DIR = os.getenv("CHROMIUM_PROFILE_DIR", "/tmp/chromium-profile")
DEFAULT_TIMEOUT_MS = int(os.getenv("SOLVE_TIMEOUT_MS", "45000"))
MAX_WAIT_MS = int(os.getenv("SOLVE_MAX_WAIT_MS", "90000"))

TURNSTILE_SELECTORS = (
    "input[name='cf-verified-token']",
    "input[name='cf_turnstile_token']",
    "input[name='cf-turnstile-response']",
    "textarea[name='cf-turnstile-response']",
    "input[name='token'][data-sitekey]",
    "input[type='hidden'][value*='token']",
)

CHALLENGE_MARKERS = (
    "cf-chl-",
    "cf-chl-status",
    "cloudflare",
    "verify you are human",
    "verify to continue",
    "checking your browser",
    "captcha",
    "recaptcha",
    "enable javascript and cookies",
    "just a moment",
    "turnstile",
    "iuam",
    "i am human",
    "click on the first link",
)


@dataclass
class SolveResult:
    success: bool
    url: str
    final_url: str
    token: Optional[str] = None
    cookies: Optional[list] = None
    clearance_cookie: Optional[str] = None
    html: Optional[str] = None
    error: Optional[str] = None
    elapsed_ms: int = 0


def _ensure_profile_dir() -> Path:
    path = Path(PROFILE_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


_browser_install_lock = threading.Lock()
_browser_install_attempted = False
_browser_install_error = ""


def _resolve_browser_executable() -> Optional[str]:
    configured = os.getenv("CHROMIUM_PATH")
    if configured and Path(configured).is_file() and os.access(configured, os.X_OK):
        return configured
    for name in ("chromium", "chromium-browser", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    # Playwright's installer does not add its downloaded browser to PATH. If
    # we install it into a writable Render directory, explicitly locate the
    # real Chromium binary instead of letting Playwright fall back to its
    # default cache (which may be /opt/render/.cache and may not exist).
    roots = []
    for value in (
        os.getenv("PLAYWRIGHT_BROWSERS_PATH"),
        os.getenv("PLAYWRIGHT_RUNTIME_BROWSERS_PATH"),
        "/tmp/playwright-browsers",
        "/ms-playwright",
        "/opt/render/.cache/ms-playwright",
        "/opt/render/project/src/.cache/ms-playwright",
    ):
        if value and value != "0":
            roots.append(Path(value))
    package_root = Path(__file__).resolve().parents[2]
    roots.extend((package_root / ".local-browsers", package_root / "node_modules" / "playwright-core"))
    for root in roots:
        if not root.is_dir():
            continue
        candidates = sorted(root.glob("**/chrome-linux/chrome"))
        candidates += sorted(root.glob("**/chrome-headless-shell-linux64/chrome-headless-shell"))
        candidates += sorted(root.glob("**/chrome"))
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def _ensure_playwright_browser() -> Optional[str]:
    """Ensure a writable Chromium install exists for native Render runtimes."""
    global _browser_install_attempted, _browser_install_error
    executable = _resolve_browser_executable()
    if executable:
        return executable
    with _browser_install_lock:
        executable = _resolve_browser_executable()
        if executable:
            return executable
        if _browser_install_attempted:
            return None
        _browser_install_attempted = True
        browser_path = Path(os.getenv("PLAYWRIGHT_RUNTIME_BROWSERS_PATH", "/tmp/playwright-browsers"))
        browser_path.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_path)
        # A previous boot may have left a marker after a partial download.
        # Make this path visible to the resolver before trusting that marker.
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_path)
        marker = browser_path / ".chromium-installed"
        try:
            installed_executable = _resolve_browser_executable()
            if not installed_executable:
                marker.unlink(missing_ok=True)
                env.pop("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", None)
                install_timeout = int(os.getenv("PLAYWRIGHT_INSTALL_TIMEOUT_SECONDS", "180"))
                install_logs = []
                for browser_name in ("chromium", "chromium-headless-shell"):
                    try:
                        completed = subprocess.run(
                            [sys.executable, "-m", "playwright", "install", browser_name],
                            check=True,
                            timeout=install_timeout,
                            env=env,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                        )
                        install_logs.append(f"{browser_name}: {completed.stdout[-1200:]}")
                    except Exception as exc:
                        output = getattr(exc, "stdout", "") or ""
                        install_logs.append(f"{browser_name}: {exc}; {output[-1200:]}")
                    installed_executable = _resolve_browser_executable()
                    if installed_executable:
                        break
                if not installed_executable:
                    _browser_install_error = " | ".join(install_logs)[-3000:]
                    LOGGER.error("Unable to install runtime Chromium: %s", _browser_install_error)
                    return None
                marker.touch()
        except Exception as exc:
            LOGGER.error("Unable to install runtime Chromium: %s", exc)
            return None
    executable = _resolve_browser_executable()
    if not executable:
        LOGGER.error("Playwright install completed without a discoverable Chromium executable")
    return executable


async def _detect_turnstile_token(page) -> Optional[str]:
    """Try to extract a Turnstile token from the page DOM."""
    for selector in TURNSTILE_SELECTORS:
        try:
            element = page.locator(selector).first
            if await element.count() == 0:
                continue
            if not await element.is_visible():
                value = await element.get_attribute("value")
                if value:
                    return value
        except Exception:
            continue

    # Fallback: look for the token in any script or hidden input text.
    try:
        token = await page.evaluate("""() => {
            const inputs = Array.from(document.querySelectorAll('input'));
            for (const input of inputs) {
                if (input.type === 'hidden' && input.value && /token/i.test(input.name)) {
                    return input.value;
                }
            }
            const scripts = Array.from(document.querySelectorAll('script'));
            for (const script of scripts) {
                const match = script.textContent?.match(/"token":"([A-Za-z0-9_.-]+)/);
                if (match) return match[1];
            }
            return null;
        }""")
        return token or None
    except Exception:
        return None


async def _extract_clearance_cookie(context) -> Optional[str]:
    """Return the cf_clearance cookie value if present."""
    try:
        cookies = await context.cookies()
        for cookie in cookies:
            if cookie.get("name") == "cf_clearance":
                return cookie.get("value")
    except Exception:
        pass
    return None


async def _has_challenge(page) -> bool:
    """Check whether the page is still presenting a Cloudflare challenge."""
    try:
        title = (await page.title() or "").lower()
    except Exception:
        title = ""
    try:
        body_text = (await page.locator("body").inner_text(timeout=2000)).lower()
    except Exception:
        body_text = ""
    combined = f"{title}\n{body_text}"
    return any(marker in combined for marker in CHALLENGE_MARKERS)


async def solve_turnstile(
    url: str,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    headless: bool = True,
) -> SolveResult:
    """Navigate to `url` and wait for the Cloudflare challenge to clear."""
    start = time.time()
    result = SolveResult(success=False, url=url, final_url="", elapsed_ms=0)
    profile_dir = _ensure_profile_dir()
    executable = _ensure_playwright_browser()
    if not executable:
        result.error = (
            "Chromium executable unavailable after checking CHROMIUM_PATH, system PATH, "
            "and all configured Playwright browser directories"
            + (f". Installer detail: {_browser_install_error}" if _browser_install_error else "")
        )
        result.elapsed_ms = int((time.time() - start) * 1000)
        return result

    try:
        async with async_playwright() as playwright:
            launch_options = {
                "user_data_dir": str(profile_dir),
                "headless": headless,
                "channel": "chromium",
                "args": [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--headless=new",
                    "--disable-blink-features=AutomationControlled",
                ],
                "viewport": {"width": 1280, "height": 720},
            }
            if executable:
                launch_options["executable_path"] = executable
            context = await playwright.chromium.launch_persistent_context(**launch_options)
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                except PlaywrightTimeoutError:
                    result.error = "Navigation timed out before page loaded"
                    return result

                # Wait for the challenge to resolve or timeout.
                deadline = time.time() + (MAX_WAIT_MS / 1000)
                resolved = False
                token_detected = None
                form_submitted = False
                while time.time() < deadline:
                    token_detected = await _detect_turnstile_token(page)
                    if token_detected:
                        resolved = True
                        break
                    if not await _has_challenge(page):
                        resolved = True
                        break
                    # Cloudflare Turnstile renders inside an iframe; interact with it.
                    try:
                        iframe = page.locator("iframe[src*='challenges.cloudflare.com']").first
                        if await iframe.count() and await iframe.is_visible(timeout=500):
                            # Click the Turnstile checkbox inside the iframe.
                            await iframe.click(timeout=2000)
                            await page.wait_for_timeout(2000)
                    except Exception:
                        pass
                    # Some ad gates require clicking a link ("Click on the first link").
                    try:
                        body_text = (await page.locator("body").inner_text(timeout=2000)).lower()
                        if "click on the first link" in body_text or "click the first link" in body_text:
                            link = page.locator("a[href^='http']").first
                            if await link.count() and await link.is_visible(timeout=500):
                                await link.click(timeout=2000)
                                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass
                    try:
                        await page.wait_for_timeout(1000)
                    except Exception:
                        break

                # After the loop, try submitting the form if a Turnstile token exists
                # or the challenge appears cleared (Jobsheel auto-submits via callback).
                try:
                    form = page.locator("form").first
                    if await form.count():
                        token = await _detect_turnstile_token(page)
                        challenge_cleared = not await _has_challenge(page)
                        if token or challenge_cleared:
                            await form.evaluate("form => form.requestSubmit ? form.requestSubmit() : form.submit()")
                            form_submitted = True
                            try:
                                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                            except Exception:
                                pass
                            await page.wait_for_timeout(5000)
                except Exception as exc:
                    LOGGER.debug("Turnstile form submission fallback: %s", exc)

                cookies = await context.cookies()
                result.cookies = cookies
                result.clearance_cookie = await _extract_clearance_cookie(context)
                result.final_url = page.url
                challenge_present = await _has_challenge(page)
                try:
                    result.html = await page.content()
                except Exception:
                    pass

                if not challenge_present or token or result.clearance_cookie:
                    result.success = True
                else:
                    result.error = "Cloudflare challenge not resolved within timeout"
            finally:
                try:
                    await context.close()
                except Exception:
                    pass
    except PlaywrightError as exc:
        result.error = f"Playwright error: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.error("Turnstile solve failed: %s", exc)
        result.error = f"Unexpected error: {exc}"
    finally:
        result.elapsed_ms = int((time.time() - start) * 1000)
    return result


async def solve_challenge(url: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> SolveResult:
    """Alias used by /solve-challenge endpoint."""
    return await solve_turnstile(url, timeout_ms=timeout_ms)


def solve_sync(url: str, timeout_ms: int = DEFAULT_TIMEOUT_MS, headless: bool = True) -> SolveResult:
    """Synchronous wrapper for use inside Flask handlers."""
    return asyncio.run(solve_turnstile(url, timeout_ms=timeout_ms, headless=headless))
