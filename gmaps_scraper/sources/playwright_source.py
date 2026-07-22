"""Scrape Google Maps search results by driving a real browser.

No API key or quota, but it depends on Google's DOM. Every selector below has a
fallback, and anything unparseable is left blank rather than aborting the run.
"""

import re
import urllib.parse
from typing import Iterator, List, Optional

from ..models import Business

SEARCH_URL = "https://www.google.com/maps/search/{query}/?hl=en&gl=us"

# The results list. Google keeps the role, even when class names churn.
FEED = 'div[role="feed"]'
CARD = 'div[role="feed"] a[href*="/maps/place/"]'
END_OF_LIST = "You've reached the end of the list"

CONSENT_BUTTONS = [
    'button[aria-label*="Accept all"]',
    'button[aria-label*="Reject all"]',
    'form[action*="consent"] button',
]


def _clean(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _strip_label(text: str) -> str:
    """Turn 'Phone: +1 512-555-0100' into '+1 512-555-0100'."""
    return _clean(text.split(":", 1)[1]) if ":" in text else _clean(text)


def _latlng_from_url(url: str):
    # Place URLs embed the true pin as !3d<lat>!4d<lng>; the /@lat,lng is only
    # the viewport centre, so prefer the former.
    m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url)
    if not m:
        m = re.search(r"/@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2))


def _dismiss_consent(page) -> None:
    for selector in CONSENT_BUTTONS:
        try:
            button = page.locator(selector).first
            if button.count() and button.is_visible():
                button.click(timeout=3000)
                page.wait_for_timeout(1500)
                return
        except Exception:
            continue


def _collect_place_urls(
    page, query: str, max_results: int, log, should_stop
) -> List[str]:
    page.goto(SEARCH_URL.format(query=urllib.parse.quote(query)), timeout=60000)
    _dismiss_consent(page)

    try:
        page.wait_for_selector(FEED, timeout=20000)
    except Exception:
        # A query with one strong match lands straight on a place page.
        if "/maps/place/" in page.url:
            return [page.url]
        log("  no results panel for {!r}".format(query))
        return []

    urls: List[str] = []
    seen = set()
    stagnant = 0

    while len(urls) < max_results and stagnant < 5 and not should_stop():
        for href in page.locator(CARD).evaluate_all(
            "els => els.map(e => e.href)"
        ):
            if href not in seen:
                seen.add(href)
                urls.append(href)

        if len(urls) >= max_results:
            break

        before = len(urls)
        # The results panel is the only progress signal until detail parsing
        # starts, so report it rather than leaving the UI on "0 found".
        log("  scrolling results... {} listings so far".format(len(urls)))
        page.locator(FEED).evaluate("el => el.scrollBy(0, el.scrollHeight)")
        page.wait_for_timeout(2000)

        if END_OF_LIST in page.locator(FEED).inner_text():
            log("  reached end of list ({} places)".format(len(urls)))
            break

        # Re-read after the scroll so we notice cards that just loaded.
        for href in page.locator(CARD).evaluate_all("els => els.map(e => e.href)"):
            if href not in seen:
                seen.add(href)
                urls.append(href)

        stagnant = stagnant + 1 if len(urls) == before else 0

    return urls[:max_results]


def _parse_place(page, url: str, query: str) -> Optional[Business]:
    page.goto(url, timeout=60000)
    try:
        page.wait_for_selector("h1", timeout=15000)
    except Exception:
        return None
    page.wait_for_timeout(400)

    biz = Business(query=query, maps_url=page.url)
    biz.name = _clean(page.locator("h1").first.inner_text())
    if not biz.name:
        return None

    def attr(selector: str, name: str) -> str:
        try:
            loc = page.locator(selector).first
            if loc.count():
                return _clean(loc.get_attribute(name))
        except Exception:
            pass
        return ""

    def text(selector: str) -> str:
        try:
            loc = page.locator(selector).first
            if loc.count():
                return _clean(loc.inner_text())
        except Exception:
            pass
        return ""

    address = attr('button[data-item-id="address"]', "aria-label")
    biz.address = _strip_label(address) if address else text(
        'button[data-item-id="address"] div.fontBodyMedium'
    )

    phone = attr('button[data-item-id^="phone:tel:"]', "aria-label")
    biz.phone = _strip_label(phone)

    biz.website = attr('a[data-item-id="authority"]', "href")
    biz.category = text('button[jsaction*="category"]')

    rating = attr('div.F7nice span[aria-hidden="true"]', "textContent") or text(
        'div.F7nice span[aria-hidden="true"]'
    )
    try:
        biz.rating = float(rating.replace(",", "."))
    except (TypeError, ValueError):
        biz.rating = None

    reviews = attr('div.F7nice span[aria-label*="review"]', "aria-label")
    m = re.search(r"([\d,\.]+)", reviews)
    if m:
        try:
            biz.reviews = int(m.group(1).replace(",", "").replace(".", ""))
        except ValueError:
            biz.reviews = None

    biz.latitude, biz.longitude = _latlng_from_url(page.url)
    return biz


def scrape(
    query: str,
    max_results: int = 50,
    headless: bool = True,
    log=print,
    should_stop=None,
) -> Iterator[Business]:
    """Yield businesses for a Google Maps search query.

    `should_stop` is polled during the (slow) scrolling phase as well as between
    listings, so a cancel from the UI takes effect promptly.
    """
    should_stop = should_stop or (lambda: False)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover
        raise SystemExit(
            "Playwright is not installed. Run:\n"
            "  pip install playwright && playwright install chromium"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            locale="en-US",
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        try:
            urls = _collect_place_urls(page, query, max_results, log, should_stop)
            log("  found {} listings, opening each for details".format(len(urls)))
            for i, url in enumerate(urls, 1):
                if should_stop():
                    break
                try:
                    biz = _parse_place(page, url, query)
                except Exception as exc:
                    log("  [{}/{}] failed: {}".format(i, len(urls), exc))
                    continue
                if biz:
                    log("  [{}/{}] {}".format(i, len(urls), biz.name))
                    yield biz
        finally:
            context.close()
            browser.close()
