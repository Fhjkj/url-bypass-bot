"""
Educational example: Web automation with Playwright (async).

Demonstrates:
- Launching a browser
- Navigating and waiting for content
- Extracting data from the DOM
- Network request interception
"""

import asyncio
from playwright.async_api import async_playwright


class PlaywrightScraper:
    """Example scraper using Playwright."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser = None
        self.context = None
        self.page = None

    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        return self

    async def __aexit__(self, *args):
        await self.browser.close()
        await self.playwright.stop()

    async def extract_video_src(self, url: str) -> str | None:
        """Navigate and extract video src after page loads."""
        try:
            await self.page.goto(url, wait_until="networkidle")
            
            # Wait for video element
            video = await self.page.wait_for_selector("video", state="attached")
            if video:
                src = await video.get_attribute("src")
                if not src:
                    source = await video.query_selector("source")
                    if source:
                        src = await source.get_attribute("src")
                return src
        except Exception as e:
            print(f"Error: {e}")
        return None

    async def intercept_network_requests(self, url_pattern: str) -> list[str]:
        """Intercept network requests matching a pattern."""
        urls = []
        
        async def handle_request(request):
            if url_pattern in request.url:
                urls.append(request.url)
        
        self.page.on("request", handle_request)
        await self.page.goto(url_pattern)
        await self.page.wait_for_timeout(2000)  # Wait for requests
        
        return urls

    async def extract_text(self, url: str, selector: str) -> str | None:
        """Extract text content from an element."""
        await self.page.goto(url, wait_until="networkidle")
        element = await self.page.query_selector(selector)
        if element:
            return await element.inner_text()
        return None


# Example usage
async def main():
    async with PlaywrightScraper(headless=True) as scraper:
        # Replace with your own test URL
        # result = await scraper.extract_video_src("https://example.com")
        # print(f"Video URL: {result}")
        pass


if __name__ == "__main__":
    asyncio.run(main())