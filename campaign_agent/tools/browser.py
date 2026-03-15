"""Playwright browser lifecycle management (singleton, lazy-init)."""

import logging
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

_playwright = None
_browser: Optional[Browser] = None
_context: Optional[BrowserContext] = None


async def get_browser_context() -> BrowserContext:
    """Return a shared browser context, launching Chromium on first call."""
    global _playwright, _browser, _context

    if _context is not None:
        return _context

    logger.info("Launching Playwright Chromium (headless)…")
    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(headless=True)
    _context = await _browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        java_script_enabled=True,
    )
    return _context


async def fetch_page_html(url: str, wait_ms: int = 3000) -> str:
    """Fetch a URL with Playwright and return the rendered HTML.

    Args:
        url: Target URL.
        wait_ms: Extra time (ms) to wait after load for JS rendering.

    Returns:
        Rendered page HTML as a string.
    """
    ctx = await get_browser_context()
    page: Page = await ctx.new_page()
    try:
        logger.info("Playwright fetching: %s", url)
        await page.goto(url, wait_until="networkidle", timeout=30000)
        # Additional wait for late JS rendering
        await page.wait_for_timeout(wait_ms)
        html = await page.content()
        return html
    finally:
        await page.close()


async def close_browser() -> None:
    """Shut down the shared browser and Playwright instance."""
    global _playwright, _browser, _context

    if _context is not None:
        await _context.close()
        _context = None
    if _browser is not None:
        await _browser.close()
        _browser = None
    if _playwright is not None:
        await _playwright.stop()
        _playwright = None
        logger.info("Playwright browser closed.")
