"""Find email addresses on a business website.

Google Maps never exposes email, so it has to come from the listing's website:
fetch the homepage, then follow up to a few likely contact pages.
"""

import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, List, Set

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

CONTACT_HINTS = ("contact", "about", "impressum", "kontakt", "reach-us", "connect")

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


def _is_real_email(email: str) -> bool:
    email = email.lower()
    if email.endswith(JUNK_EXTENSIONS):
        return False
    if any(domain in email for domain in JUNK_DOMAINS):
        return False
    local, _, domain = email.partition("@")
    if not local or len(domain) < 4:
        return False
    # 32-hex local parts are almost always tracking/build hashes.
    if re.fullmatch(r"[0-9a-f]{16,}", local):
        return False
    return True


def _extract(html: str) -> Set[str]:
    soup = BeautifulSoup(html, "html.parser")
    found = set()

    for a in soup.select('a[href^="mailto:"]'):
        raw = a.get("href", "")[7:].split("?")[0]
        for email in EMAIL_RE.findall(urllib.parse.unquote(raw)):
            found.add(email)

    for script in soup(["script", "style", "noscript"]):
        script.decompose()
    for email in EMAIL_RE.findall(soup.get_text(" ")):
        found.add(email)

    # Common lightweight obfuscation: "name (at) domain (dot) com".
    text = soup.get_text(" ")
    for m in re.finditer(
        r"([a-zA-Z0-9._%+\-]+)\s*(?:\(at\)|\[at\]|\s+at\s+)\s*"
        r"([a-zA-Z0-9.\-]+)\s*(?:\(dot\)|\[dot\]|\s+dot\s+)\s*([a-zA-Z]{2,24})",
        text,
        re.IGNORECASE,
    ):
        found.add("{}@{}.{}".format(m.group(1), m.group(2), m.group(3)))

    return {e.lower().strip(".,;:") for e in found if _is_real_email(e)}


def _contact_links(html: str, base_url: str, limit: int) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_host = urllib.parse.urlparse(base_url).netloc
    links: List[str] = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        haystack = (href + " " + a.get_text(" ")).lower()
        if not any(hint in haystack for hint in CONTACT_HINTS):
            continue
        absolute = urllib.parse.urljoin(base_url, href).split("#")[0]
        if urllib.parse.urlparse(absolute).netloc != base_host:
            continue
        if absolute in seen or absolute.rstrip("/") == base_url.rstrip("/"):
            continue
        seen.add(absolute)
        links.append(absolute)
        if len(links) >= limit:
            break

    return links


def _fetch(url: str, timeout: float) -> str:
    try:
        response = requests.get(
            url, headers=HEADERS, timeout=timeout, allow_redirects=True
        )
        content_type = response.headers.get("Content-Type", "")
        if response.status_code != 200 or "html" not in content_type:
            return ""
        return response.text
    except requests.RequestException:
        return ""


def find_emails(website: str, timeout: float = 12.0, max_pages: int = 3) -> List[str]:
    """Return emails found on a website's homepage and its contact pages."""
    if not website:
        return []
    if not website.startswith(("http://", "https://")):
        website = "https://" + website

    home = _fetch(website, timeout)
    if not home:
        return []

    emails = _extract(home)
    if not emails:
        # Only pay for extra requests when the homepage came up empty.
        for link in _contact_links(home, website, max_pages - 1):
            emails |= _extract(_fetch(link, timeout))
            if emails:
                break

    return sorted(emails)


def enrich(businesses: Iterable, workers: int = 8, log=print, **kwargs) -> None:
    """Populate `.emails` on each business in parallel, in place."""
    items = [b for b in businesses if b.website and not b.emails]
    if not items:
        return

    log("Looking up emails for {} websites...".format(len(items)))

    def work(biz):
        biz.emails = find_emails(biz.website, **kwargs)
        return biz

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for biz in pool.map(work, items):
            if biz.emails:
                log("  {} -> {}".format(biz.name, ", ".join(biz.emails)))
