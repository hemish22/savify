"""
Web scraper for extracting article content from blog URLs.
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

# Timeout for HTTP requests (seconds)
REQUEST_TIMEOUT = 15

# Elements to remove before extracting text
UNWANTED_TAGS = [
    "nav", "footer", "header", "aside", "script", "style",
    "noscript", "iframe", "form", "button", "svg",
]

# CSS classes/IDs commonly associated with ads and non-content
UNWANTED_PATTERNS = [
    "sidebar", "advertisement", "ad-", "social-share", "comment",
    "related-post", "newsletter", "popup", "cookie", "banner",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def validate_url(url: str) -> str:
    """Validate and normalize the URL."""
    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    if not parsed.netloc or "." not in parsed.netloc:
        raise ValueError(f"Invalid URL: {url}")

    return url


def extract_domain(url: str) -> str:
    """Extract the domain name from a URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    return domain


def _remove_unwanted_elements(soup: BeautifulSoup) -> None:
    """Remove navigation, footer, ads, and other non-content elements."""
    # Remove unwanted tags
    for tag_name in UNWANTED_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Remove elements with ad/sidebar-related classes or IDs
    for pattern in UNWANTED_PATTERNS:
        for element in soup.find_all(
            attrs={"class": lambda c: c and pattern in str(c).lower()}
        ):
            element.decompose()
        for element in soup.find_all(
            attrs={"id": lambda i: i and pattern in str(i).lower()}
        ):
            element.decompose()


def _extract_article_text(soup: BeautifulSoup) -> str:
    """
    Extract main article text.
    Tries <article>, then <main>, then falls back to <body>.
    """
    # Try to find article content in order of specificity
    content = soup.find("article")
    if not content:
        content = soup.find("main")
    if not content:
        content = soup.find("div", {"role": "main"})
    if not content:
        content = soup.find("body")

    if not content:
        return ""

    # Get text with newline separators between blocks
    paragraphs = content.find_all(["p", "h1", "h2", "h3", "h4", "li"])
    text_parts = []
    for p in paragraphs:
        text = p.get_text(strip=True)
        if text and len(text) > 20:  # Skip very short fragments
            text_parts.append(text)

    return "\n\n".join(text_parts)


def scrape_article(url: str) -> dict:
    """
    Scrape a blog URL and return cleaned article content.

    Returns:
        dict with keys: 'text', 'domain', 'title'

    Raises:
        ValueError: If URL is invalid or article is empty.
        ConnectionError: If the URL cannot be reached.
        TimeoutError: If the request times out.
    """
    # Validate URL
    url = validate_url(url)
    domain = extract_domain(url)

    # Fetch the page
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise TimeoutError(f"Request timed out after {REQUEST_TIMEOUT}s: {url}")
    except requests.exceptions.ConnectionError:
        raise ConnectionError(f"Could not connect to: {url}")
    except requests.exceptions.HTTPError:
        raise ConnectionError(f"HTTP error {response.status_code}: {url}")

    # Parse HTML
    soup = BeautifulSoup(response.text, "html.parser")

    # Extract page title
    page_title = ""
    title_tag = soup.find("title")
    if title_tag:
        page_title = title_tag.get_text(strip=True)

    # Clean unwanted elements
    _remove_unwanted_elements(soup)

    # Extract article text
    text = _extract_article_text(soup)

    if not text or len(text) < 100:
        raise ValueError(
            "Could not extract enough article content from this URL. "
            "The page may not be a blog post, or the content may be "
            "loaded dynamically."
        )

    # Truncate very long articles to avoid API limits
    max_chars = 15000
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[Content truncated for summarization]"

    return {
        "text": text,
        "domain": domain,
        "title": page_title,
    }
