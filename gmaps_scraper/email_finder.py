"""Find email addresses on a business website.

Google Maps never exposes email, so it has to come from the listing's website:
fetch the homepage, then follow up to a few likely contact pages.
"""

import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, List, Set, Tuple

import requests
from bs4 import BeautifulSoup

EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,24}"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Ordered best-first: a real "contact" page beats an "about" page, which is why
# links are ranked by hint index rather than by where they sit in the DOM.
CONTACT_HINTS = (
    "contact",
    "kontakt",
    "impressum",
    "reach-us",
    "get-in-touch",
    "connect",
    "about",
)

# Retina image names (logo@2x.png) and tracking/CDN addresses match the email
# pattern but are never real contacts.
JUNK_DOMAINS = (
    "example.com",
    "sentry.io",
    "wixpress.com",
    "godaddy.com",
    "squarespace.com",
    "domain.com",
    "email.com",
    "yourdomain.com",
    "sentry-next.wixpress.com",
)
JUNK_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")


# Addresses that exist but are never worth writing to.
NO_REPLY_LOCALS = ("noreply", "no-reply", "donotreply", "do-not-reply", "mailer-daemon")


def _host(url: str) -> str:
    """Hostname without a leading www., so www.acme.com and acme.com match."""
    host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _is_real_email(email: str) -> bool:
    email = email.lower()
    if email.endswith(JUNK_EXTENSIONS):
        return False
    local, _, domain = email.partition("@")
    if not local or len(domain) < 4:
        return False
    # Match whole domains, so mydomain.com isn't mistaken for domain.com.
    if any(domain == junk or domain.endswith("." + junk) for junk in JUNK_DOMAINS):
        return False
    if local in NO_REPLY_LOCALS:
        return False
    # Long hex local parts are almost always tracking/build hashes.
    if re.fullmatch(r"[0-9a-f]{16,}", local):
        return False
    return True


def _decode_cfemail(encoded: str) -> str:
    """Undo Cloudflare's email obfuscation: hex bytes XORed with the first byte."""
    try:
        data = bytes.fromhex(encoded)
    except ValueError:
        return ""
    if len(data) < 2:
        return ""
    return bytes(b ^ data[0] for b in data[1:]).decode("utf-8", "ignore")


def _jsonld_emails(node, found: Set[str]) -> None:
    """Collect "email" values from schema.org structured data, at any depth."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key.lower() == "email" and isinstance(value, str):
                found.update(EMAIL_RE.findall(urllib.parse.unquote(value)))
            else:
                _jsonld_emails(value, found)
    elif isinstance(node, list):
        for item in node:
            _jsonld_emails(item, found)


def _extract(html: str) -> Set[str]:
    soup = BeautifulSoup(html, "html.parser")
    found = set()

    for a in soup.select('a[href^="mailto:"]'):
        raw = a.get("href", "")[7:].split("?")[0]
        for email in EMAIL_RE.findall(urllib.parse.unquote(raw)):
            found.add(email)

    # Cloudflare replaces every address on the page with an encoded blob, either
    # in a data-cfemail attribute or an /cdn-cgi/l/email-protection#<hex> link.
    for el in soup.select("[data-cfemail]"):
        found.update(EMAIL_RE.findall(_decode_cfemail(el.get("data-cfemail", ""))))
    for a in soup.select('a[href*="/cdn-cgi/l/email-protection#"]'):
        encoded = a.get("href", "").split("#", 1)[1]
        found.update(EMAIL_RE.findall(_decode_cfemail(encoded)))

    # Structured data is a script, so it has to be read before scripts go.
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            _jsonld_emails(json.loads(script.string or ""), found)
        except ValueError:
            continue

    for script in soup(["script", "style", "noscript"]):
        script.decompose()
    for email in EMAIL_RE.findall(soup.get_text(" ")):
        found.add(email)

    # Common lightweight obfuscation: "name (at) domain (dot) com", including
    # multi-part endings like "acme (dot) co (dot) uk".
    text = soup.get_text(" ")
    dot = r"\s*(?:\(dot\)|\[dot\]|\s+dot\s+)\s*"
    for m in re.finditer(
        r"([a-zA-Z0-9._%+\-]+)\s*(?:\(at\)|\[at\]|\s+at\s+)\s*"
        r"([a-zA-Z0-9\-]+(?:" + dot + r"[a-zA-Z0-9\-]+)*)" + dot + r"([a-zA-Z]{2,24})\b",
        text,
        re.IGNORECASE,
    ):
        domain = re.sub(dot, ".", m.group(2), flags=re.IGNORECASE)
        found.add("{}@{}.{}".format(m.group(1), domain, m.group(3)))

    return {e.lower().strip(".,;:") for e in found if _is_real_email(e)}


def _contact_links(html: str, base_url: str, limit: int) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_host = _host(base_url)
    scored = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        haystack = (href + " " + a.get_text(" ")).lower()
        rank = next(
            (i for i, hint in enumerate(CONTACT_HINTS) if hint in haystack), None
        )
        if rank is None:
            continue
        absolute = urllib.parse.urljoin(base_url, href).split("#")[0]
        if _host(absolute) != base_host:
            continue
        if absolute in seen or absolute.rstrip("/") == base_url.rstrip("/"):
            continue
        seen.add(absolute)
        # Shallower paths first within a rank: /contact beats /about/history.
        scored.append((rank, absolute.count("/"), len(scored), absolute))

    scored.sort()
    return [url for _, _, _, url in scored[:limit]]


# Status codes that mean "a browser would have got in, this client didn't".
BLOCKED_STATUSES = (401, 403, 405, 406, 429, 503)


def _fetch(url: str, timeout: float) -> Tuple[str, bool, str]:
    """Return (html, blocked, final_url).

    `blocked` marks pages worth a browser retry. `final_url` is where redirects
    landed, which is the right base for resolving the page's links.
    """
    try:
        response = requests.get(
            url, headers=HEADERS, timeout=timeout, allow_redirects=True
        )
    except requests.RequestException:
        return "", False, url

    if response.status_code in BLOCKED_STATUSES:
        return "", True, response.url
    if response.status_code != 200:
        return "", False, response.url
    if "html" not in response.headers.get("Content-Type", ""):
        return "", False, response.url
    return response.text, False, response.url


def _normalise(website: str) -> str:
    if not website.startswith(("http://", "https://")):
        return "https://" + website
    return website


def _rank(emails: Iterable[str], website: str) -> List[str]:
    """Best contact first: addresses on the business's own domain lead, so a
    web designer's footer address doesn't end up as the first email."""
    site = _host(website)

    def own_domain(email: str) -> bool:
        domain = email.partition("@")[2]
        return bool(site) and (
            domain == site or domain.endswith("." + site) or site.endswith("." + domain)
        )

    return sorted(set(emails), key=lambda e: (not own_domain(e), e))


def _scan(website: str, timeout: float, max_pages: int) -> Tuple[List[str], bool]:
    home, blocked, final_url = _fetch(website, timeout)
    if not home:
        return [], blocked

    emails = _extract(home)
    if not emails:
        # Only pay for extra requests when the homepage came up empty.
        for link in _contact_links(home, final_url, max_pages - 1):
            page, page_blocked, _ = _fetch(link, timeout)
            blocked = blocked or page_blocked
            emails |= _extract(page)
            if emails:
                break

    # A blocked contact page is worth a browser retry, same as a blocked home.
    return _rank(emails, final_url), blocked and not emails


def find_emails(website: str, timeout: float = 12.0, max_pages: int = 3) -> List[str]:
    """Return emails found on a website's homepage and its contact pages."""
    if not website:
        return []
    return _scan(_normalise(website), timeout, max_pages)[0]


def _render_scan(items, timeout: float, max_pages: int, log, should_stop) -> None:
    """Second pass for bot-blocked sites, using a real browser.

    Runs sequentially in one browser: these are the minority of sites, and a
    Playwright instance per worker thread would cost more than it saves.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return

    log("  {} sites blocked plain requests - retrying in a browser...".format(len(items)))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="en-US", user_agent=HEADERS["User-Agent"]
        )
        page = context.new_page()
        try:
            for biz in items:
                if should_stop():
                    break
                url = _normalise(biz.website)
                try:
                    page.goto(url, timeout=int(timeout * 1000), wait_until="domcontentloaded")
                    page.wait_for_timeout(700)
                    html = page.content()
                    url = page.url  # resolve links against where redirects landed
                except Exception:
                    continue

                emails = _extract(html)
                if not emails:
                    for link in _contact_links(html, url, max_pages - 1):
                        try:
                            page.goto(
                                link,
                                timeout=int(timeout * 1000),
                                wait_until="domcontentloaded",
                            )
                            page.wait_for_timeout(500)
                            emails |= _extract(page.content())
                        except Exception:
                            continue
                        if emails:
                            break

                if emails:
                    biz.emails = _rank(emails, url)
                    log("  {} -> {}".format(biz.name, ", ".join(biz.emails)))
        finally:
            context.close()
            browser.close()


def enrich(
    businesses: Iterable,
    workers: int = 8,
    log=print,
    render_blocked: bool = True,
    timeout: float = 12.0,
    max_pages: int = 3,
    should_stop=None,
) -> None:
    """Populate `.emails` on each business in parallel, in place.

    `should_stop` is checked before each site, so a cancel stops the lookup
    within one fetch per worker instead of after the whole list.
    """
    should_stop = should_stop or (lambda: False)
    items = [b for b in businesses if b.website and not b.emails]
    if not items:
        return

    log("Looking up emails for {} websites...".format(len(items)))
    blocked = []

    def work(biz):
        if should_stop():
            return biz, False
        emails, was_blocked = _scan(_normalise(biz.website), timeout, max_pages)
        biz.emails = emails
        return biz, was_blocked

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for biz, was_blocked in pool.map(work, items):
            if biz.emails:
                log("  {} -> {}".format(biz.name, ", ".join(biz.emails)))
            elif was_blocked:
                blocked.append(biz)

    if blocked and render_blocked and not should_stop():
        _render_scan(blocked, timeout, max_pages, log, should_stop)
