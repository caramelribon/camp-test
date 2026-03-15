import re
import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from campaign_agent.retry import retry_async, retry_sync

logger = logging.getLogger(__name__)

EXCLUDE_PATTERNS = [
    r"/login",
    r"/signup",
    r"/register",
    r"/cart",
    r"/mypage",
    r"/contact",
    r"/privacy",
    r"/terms",
    r"/faq",
    r"/help",
    r"/about",
    r"/company",
    r"/sitemap",
    r"/feed",
    r"/rss",
    r"\.pdf$",
    r"\.zip$",
    r"\.xml$",
    r"#$",
    r"javascript:",
    r"mailto:",
    r"tel:",
]

# Campaign-related keywords to match against the full URL or anchor text
CAMPAIGN_URL_KEYWORDS = [
    "campaign", "event", "promotion", "promo", "offer",
    "キャンペーン", "cp", "special", "bonus", "coupon",
]

CAMPAIGN_ANCHOR_KEYWORDS = [
    "キャンペーン", "還元", "ポイント", "特典", "割引",
    "クーポン", "プレゼント", "抽選", "おトク", "お得",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

_MIN_URLS_THRESHOLD = 3


def _extract_urls_from_html(html: str, seed_url: str) -> list[str]:
    """Parse HTML and return candidate campaign URLs.

    Judges by URL content and anchor text — no domain restriction.
    """
    soup = BeautifulSoup(html, "html.parser")

    seen: set[str] = set()
    urls: list[str] = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        absolute_url = urljoin(seed_url, href)

        # Remove fragment
        parsed = urlparse(absolute_url)
        clean_url = parsed._replace(fragment="").geturl()

        # Only http(s)
        if parsed.scheme not in ("http", "https"):
            continue

        # Exclude patterns
        if any(re.search(pat, clean_url, re.IGNORECASE) for pat in EXCLUDE_PATTERNS):
            continue

        # Skip the seed URL itself
        if clean_url.rstrip("/") == seed_url.rstrip("/"):
            continue

        # Check full URL for campaign keywords
        url_lower = clean_url.lower()
        has_campaign_url = any(kw in url_lower for kw in CAMPAIGN_URL_KEYWORDS)

        # Check anchor text for campaign keywords
        anchor_text = a_tag.get_text(strip=True)
        has_campaign_anchor = any(
            kw in anchor_text for kw in CAMPAIGN_ANCHOR_KEYWORDS
        ) if anchor_text else False

        if not (has_campaign_url or has_campaign_anchor):
            continue

        # Deduplicate
        if clean_url in seen:
            continue
        seen.add(clean_url)
        urls.append(clean_url)

    return urls


def collect_seed_urls(seed_url: str) -> dict:
    """Fetch seed URL and extract candidate campaign URLs.

    Args:
        seed_url: The campaign list page URL to crawl.

    Returns:
        dict with 'urls' (list of candidate URLs) and 'error' (if any).
    """
    try:
        def _fetch():
            resp = requests.get(seed_url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp

        resp = retry_sync(_fetch)
    except requests.RequestException as e:
        logger.error("Failed to fetch seed URL %s after retries: %s", seed_url, e)
        return {"urls": [], "error": str(e)}

    urls = _extract_urls_from_html(resp.text, seed_url)
    logger.info("Collected %d candidate URLs from %s", len(urls), seed_url)
    return {"urls": urls, "error": None}


async def collect_seed_urls_async(seed_url: str) -> dict:
    """Fetch seed URL, falling back to Playwright if static fetch yields few results.

    1. Try requests (fast, no JS).
    2. If fewer than _MIN_URLS_THRESHOLD URLs found, retry with Playwright.

    Returns:
        dict with 'urls' and 'error'.
    """
    # --- static attempt (with retry: max 3) ---
    try:
        async def _static_fetch():
            resp = requests.get(seed_url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text

        static_html = await retry_async(_static_fetch)
    except Exception as e:
        logger.error("Failed to fetch seed URL %s after retries: %s", seed_url, e)
        static_html = None

    if static_html is not None:
        urls = _extract_urls_from_html(static_html, seed_url)
        if len(urls) >= _MIN_URLS_THRESHOLD:
            logger.info(
                "Collected %d candidate URLs from %s (static)", len(urls), seed_url
            )
            return {"urls": urls, "error": None}
        logger.info(
            "Static fetch returned only %d URLs for %s — trying Playwright",
            len(urls),
            seed_url,
        )

    # --- Playwright fallback (with retry: max 3) ---
    try:
        from campaign_agent.tools.browser import fetch_page_html

        async def _playwright_fetch():
            return await fetch_page_html(seed_url)

        rendered_html = await retry_async(_playwright_fetch)
        urls = _extract_urls_from_html(rendered_html, seed_url)
        logger.info(
            "Collected %d candidate URLs from %s (Playwright)", len(urls), seed_url
        )
        return {"urls": urls, "error": None}
    except Exception as e:
        logger.error("Playwright fallback failed for %s after retries: %s", seed_url, e)
        # If we had partial static results, return those
        if static_html is not None:
            partial = _extract_urls_from_html(static_html, seed_url)
            return {"urls": partial, "error": None}
        return {"urls": [], "error": str(e)}
