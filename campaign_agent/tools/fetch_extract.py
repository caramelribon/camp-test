import re
import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Comment

from campaign_agent.retry import retry_async, retry_sync

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

REMOVE_TAGS = ["script", "style", "noscript", "iframe", "svg", "nav", "footer"]

# Campaign-related keywords
CAMPAIGN_KEYWORDS = [
    "キャンペーン",
    "還元",
    "ポイント",
    "エントリー",
    "対象店舗",
    "対象",
    "条件",
    "特典",
    "進呈",
    "応援",
    "抽選",
    "プレゼント",
    "キャッシュバック",
    "割引",
    "クーポン",
    "おトク",
    "お得",
    "増量",
    "上乗せ",
    "もれなく",
    "先着",
]

# Date patterns (Japanese)
DATE_PATTERN = re.compile(
    r"\d{4}年\d{1,2}月\d{1,2}日"
    r"|\d{1,2}月\d{1,2}日"
    r"|\d{4}/\d{1,2}/\d{1,2}"
    r"|\d{4}\.\d{1,2}\.\d{1,2}"
)

PERCENTAGE_PATTERN = re.compile(r"\d+\.?\d*\s*[%％]")
POINT_PATTERN = re.compile(
    r"\d[\d,]*\s*(?:ポイント|円相当|円分|pt|PT|P)", re.IGNORECASE
)

# Minimum main_text length to consider static fetch "sufficient"
_MIN_CONTENT_LENGTH = 200


def _extract_features_from_html(html: str, url: str) -> dict:
    """Parse HTML and return page features for classification.

    Pure extraction logic shared by both sync and async code paths.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove unwanted elements
    for tag_name in REMOVE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Title
    title = ""
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)

    # Meta description
    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if meta_tag:
        meta_desc = meta_tag.get("content", "")

    # H1
    h1 = ""
    h1_tag = soup.find("h1")
    if h1_tag:
        h1 = h1_tag.get_text(strip=True)

    # Headings (h2-h4)
    headings = []
    for level in ["h2", "h3", "h4"]:
        for tag in soup.find_all(level):
            text = tag.get_text(strip=True)
            if text:
                headings.append(text)

    # Main text
    body = soup.find("body")
    main_text = ""
    if body:
        main_text = body.get_text(separator="\n", strip=True)
        # Truncate to avoid overly long text
        if len(main_text) > 5000:
            main_text = main_text[:5000]

    # Button texts
    button_texts = []
    for btn in soup.find_all("button"):
        text = btn.get_text(strip=True)
        if text:
            button_texts.append(text)
    for inp in soup.find_all("input", attrs={"type": ["submit", "button"]}):
        val = inp.get("value", "")
        if val:
            button_texts.append(val)
    # Also check anchor tags styled as buttons
    for a_tag in soup.find_all("a", class_=re.compile(r"btn|button", re.IGNORECASE)):
        text = a_tag.get_text(strip=True)
        if text:
            button_texts.append(text)

    # Anchor texts
    anchor_texts = []
    domain = urlparse(url).netloc
    for a_tag in soup.find_all("a", href=True):
        parsed = urlparse(urljoin(url, a_tag["href"]))
        if parsed.netloc == domain:
            text = a_tag.get_text(strip=True)
            if text and len(text) < 200:
                anchor_texts.append(text)

    # Detected features
    combined_text = f"{title} {h1} {' '.join(headings)} {main_text}"

    dates = DATE_PATTERN.findall(combined_text)
    percentages = PERCENTAGE_PATTERN.findall(combined_text)
    point_mentions = POINT_PATTERN.findall(combined_text)

    campaign_keywords_found = [
        kw for kw in CAMPAIGN_KEYWORDS if kw in combined_text
    ]

    detected_features = {
        "dates": dates[:20],
        "percentages": percentages[:10],
        "point_mentions": point_mentions[:10],
        "campaign_keywords": campaign_keywords_found,
    }

    return {
        "url": url,
        "title": title,
        "meta_description": meta_desc,
        "h1": h1,
        "headings": headings[:30],
        "main_text": main_text,
        "button_texts": button_texts[:20],
        "anchor_texts": anchor_texts[:50],
        "detected_features": detected_features,
        "error": None,
    }


def fetch_and_extract(url: str) -> dict:
    """Fetch URL and extract page features for classification.

    Args:
        url: Target URL to fetch and analyze.

    Returns:
        dict with extracted features, or dict with 'error' key on failure.
    """
    try:
        def _fetch():
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp

        resp = retry_sync(_fetch)
    except requests.RequestException as e:
        logger.error("Failed to fetch %s after retries: %s", url, e)
        return {"url": url, "error": str(e)}

    return _extract_features_from_html(resp.text, url)


async def fetch_and_extract_async(url: str) -> dict:
    """Fetch URL, falling back to Playwright if static content is thin.

    1. Try requests (fast, no JS).
    2. If main_text shorter than _MIN_CONTENT_LENGTH, retry with Playwright.

    Returns:
        dict with extracted features, or dict with 'error' key on failure.
    """
    # --- static attempt (with retry: max 3) ---
    try:
        async def _static_fetch():
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text

        static_html = await retry_async(_static_fetch)
    except Exception as e:
        logger.error("Failed to fetch %s after retries: %s", url, e)
        static_html = None

    if static_html is not None:
        features = _extract_features_from_html(static_html, url)
        main_text = features.get("main_text", "")
        if len(main_text) >= _MIN_CONTENT_LENGTH:
            return features
        logger.info(
            "Static content too thin (%d chars) for %s — trying Playwright",
            len(main_text),
            url,
        )

    # --- Playwright fallback (with retry: max 3) ---
    try:
        from campaign_agent.tools.browser import fetch_page_html

        async def _playwright_fetch():
            return await fetch_page_html(url)

        rendered_html = await retry_async(_playwright_fetch)
        features = _extract_features_from_html(rendered_html, url)
        logger.info("Extracted features from %s via Playwright", url)
        return features
    except Exception as e:
        logger.error("Playwright fallback failed for %s after retries: %s", url, e)
        if static_html is not None:
            return _extract_features_from_html(static_html, url)
        return {"url": url, "error": str(e)}
