"""
Educational example: Web automation with Selenium.

This demonstrates common patterns for:
- Waiting for JavaScript-rendered content
- Extracting data from the DOM
- Handling dynamic pages

For legitimate use cases only (own sites, testing, public APIs).
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


class VideoScraper:
    """Example scraper demonstrating Selenium patterns."""

    def __init__(self, headless: bool = True):
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 10)

    def extract_video_src(self, url: str) -> str | None:
        """
        Navigate to a page and extract the video src attribute.
        
        Demonstrates:
        - Waiting for dynamic content
        - DOM element interaction
        - Attribute extraction
        """
        try:
            self.driver.get(url)
            
            # Wait for video element to appear in DOM
            video = self.wait.until(
                EC.presence_of_element_located((By.TAG_NAME, "video"))
            )
            
            # Extract src attribute
            src = video.get_attribute("src")
            
            # Also check for source elements inside video
            if not src:
                source = video.find_element(By.TAG_NAME, "source")
                src = source.get_attribute("src")
            
            return src
            
        except TimeoutException:
            print(f"Timeout waiting for video element on {url}")
            return None
        except Exception as e:
            print(f"Error extracting video: {e}")
            return None

    def extract_with_selector(self, url: str, selector: str) -> str | None:
        """Extract content using a CSS selector."""
        try:
            self.driver.get(url)
            element = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            return element.get_attribute("src") or element.text
        except Exception as e:
            print(f"Error: {e}")
            return None

    def close(self):
        self.driver.quit()


# Example usage
if __name__ == "__main__":
    scraper = VideoScraper(headless=True)
    
    # Replace with your own test URL
    # test_url = "https://example.com"
    # result = scraper.extract_video_src(test_url)
    # print(f"Video URL: {result}")
    
    scraper.close()