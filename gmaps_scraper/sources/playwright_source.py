"""Scrape Google Maps search results by driving a real browser.

No API key or quota, but it depends on Google's DOM. Every selector below has a
fallback, and anything unparseable is left blank rather than aborting the run.
"""

import math
import re
import urllib.parse
from typing import Iterator, List, Optional, Tuple

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


def _open_feed(page, url: str, log) -> bool:
    """Load a search URL and wait for the results panel. False if there is none."""
    page.goto(url, timeout=60000)
    _dismiss_consent(page)
    try:
        page.wait_for_selector(FEED, timeout=20000)
        return True
    except Exception:
        return False


def _scroll_collect(page, urls, seen, limit: int, log, should_stop) -> int:
    """Scroll the open results panel, appending new place URLs. Returns how many."""
    added_total = 0
    stagnant = 0

    while len(urls) < limit and stagnant < 5 and not should_stop():
        before = len(urls)
        for href in page.locator(CARD).evaluate_all("els => els.map(e => e.href)"):
            if href not in seen:
                seen.add(href)
                urls.append(href)
        added_total += len(urls) - before

        if len(urls) >= limit:
            break

        try:
            if END_OF_LIST in page.locator(FEED).inner_text():
                break
        except Exception:
            pass

        # The results panel is the only progress signal until detail parsing
        # starts, so report it rather than leaving the UI on "0 found".
        log("  scrolling results... {} listings so far".format(len(urls)))
        page.locator(FEED).evaluate("el => el.scrollBy(0, el.scrollHeight)")
        page.wait_for_timeout(2000)

        stagnant = stagnant + 1 if len(urls) == before else 0

    return added_total


def _collect_place_urls(
    page, query: str, max_results: int, log, should_stop
) -> List[str]:
    if not _open_feed(page, SEARCH_URL.format(query=urllib.parse.quote(query)), log):
        # A query with one strong match lands straight on a place page.
        if "/maps/place/" in page.url:
            return [page.url]
        log("  no results panel for {!r}".format(query))
        return []

    urls: List[str] = []
    _scroll_collect(page, urls, set(), max_results, log, should_stop)
    return urls[:max_results]


# ---------------------------------------------------------------- area search

VIEWPORT_URL = (
    "https://www.google.com/maps/search/{query}/@{lat},{lng},{zoom}z?hl=en&gl=us"
)

KM_PER_DEG_LAT = 110.574
VIEWPORT_PX = 1440  # matches the browser context width set in scrape()


def _distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance, good enough for an area sanity check."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlam = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))


def _map_centre(page, location: str, log) -> Optional[Tuple[float, float]]:
    """Find the map centre Google uses for a place name."""
    page.goto(SEARCH_URL.format(query=urllib.parse.quote(location)), timeout=60000)
    _dismiss_consent(page)

    # Google rewrites the URL to the matched place a few seconds after load, so
    # poll for the coordinates instead of guessing a sleep long enough.
    for _ in range(20):
        m = re.search(r"/@(-?\d+\.\d+),(-?\d+\.\d+)", page.url)
        if m:
            return float(m.group(1)), float(m.group(2))
        page.wait_for_timeout(750)

    log("  could not locate {!r} on the map".format(location))
    return None


def _zoom_for(step_km: float, lat: float) -> float:
    """Zoom at which the viewport roughly covers one grid cell."""
    metres_per_px = (step_km * 1000.0) / VIEWPORT_PX
    zoom = math.log(
        156543.03392 * math.cos(math.radians(lat)) / metres_per_px, 2
    )
    # Too far out and tiles just repeat the city-wide result; too far in and
    # each tile returns a handful of places.
    return round(max(11.0, min(16.0, zoom)), 1)


def _grid_centres(lat: float, lng: float, radius_km: float, n: int):
    """n x n centres covering a square of side 2*radius_km."""
    if n <= 1:
        return [(lat, lng)], radius_km * 2
    step_km = (2.0 * radius_km) / n
    half = (n - 1) / 2.0
    km_per_deg_lng = 111.320 * math.cos(math.radians(lat)) or 1e-6
    centres = []
    for row in range(n):
        for col in range(n):
            centres.append(
                (
                    lat + ((row - half) * step_km) / KM_PER_DEG_LAT,
                    lng + ((col - half) * step_km) / km_per_deg_lng,
                )
            )
    return centres, step_km


def scrape_area(
    term: str,
    location: str,
    max_results: int = 200,
    grid: int = 3,
    radius_km: float = 10.0,
    headless: bool = True,
    log=print,
    should_stop=None,
) -> Iterator[Business]:
    """Sweep a term across a grid of map viewports around `location`.

    A single Google search stops near 100 listings no matter how far you scroll.
    Each map viewport, though, gets its own ~100, so tiling an area and merging
    the results is the way past that ceiling. The term must be bare ("dentists",
    not "dentists in Denver") - naming a city makes Google re-run the text search
    and return the same listings for every tile.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover
        raise SystemExit(
            "Playwright is not installed. Run:\n"
            "  pip install playwright && playwright install chromium"
        )

    should_stop = should_stop or (lambda: False)
    label = "{} near {}".format(term, location)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            locale="en-US",
            viewport={"width": VIEWPORT_PX, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        try:
            centre = _map_centre(page, location, log)
            if not centre:
                return

            centres, step_km = _grid_centres(centre[0], centre[1], radius_km, grid)
            zoom = _zoom_for(step_km, centre[0])
            log(
                "  {} tiles across ~{:.0f}km, {:.1f}km apart (zoom {})".format(
                    len(centres), radius_km * 2, step_km, zoom
                )
            )

            urls: List[str] = []
            seen = set()
            for i, (lat, lng) in enumerate(centres, 1):
                if should_stop() or len(urls) >= max_results:
                    break
                url = VIEWPORT_URL.format(
                    query=urllib.parse.quote(term), lat=lat, lng=lng, zoom=zoom
                )
                if not _open_feed(page, url, log):
                    continue
                added = _scroll_collect(page, urls, seen, max_results, log, should_stop)
                log(
                    "  tile {}/{}: +{} new (total {})".format(
                        i, len(centres), added, len(urls)
                    )
                )

            # Google sometimes mixes in listings from the machine's own region
            # when a viewport is sparse. Card URLs carry !3d/!4d coordinates, so
            # strays can be dropped before we pay to open them.
            bound_km = radius_km * 1.5
            in_area, strays = [], 0
            for url in urls:
                lat, lng = _latlng_from_url(url)
                if lat is None or _distance_km(centre[0], centre[1], lat, lng) <= bound_km:
                    in_area.append(url)
                else:
                    strays += 1
            if strays:
                log("  dropped {} listings outside the search area".format(strays))

            urls = in_area[:max_results]
            log("  {} unique listings, opening each for details".format(len(urls)))
            for i, url in enumerate(urls, 1):
                if should_stop():
                    break
                try:
                    biz = _parse_place(page, url, label)
                except Exception as exc:
                    log("  [{}/{}] failed: {}".format(i, len(urls), exc))
                    continue
                if biz:
                    log("  [{}/{}] {}".format(i, len(urls), biz.name))
                    yield biz
        finally:
            context.close()
            browser.close()


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
