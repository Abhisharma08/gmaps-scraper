"""Fetch listings from the official Google Places API (New).

Stable and fast, but billed per request and capped at 60 results per text query.
Set GOOGLE_MAPS_API_KEY (or pass --api-key).
"""

import os
import time
from typing import Iterator, Optional

import requests

from ..models import Business

ENDPOINT = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = ",".join(
    [
        "places.displayName",
        "places.formattedAddress",
        "places.internationalPhoneNumber",
        "places.nationalPhoneNumber",
        "places.websiteUri",
        "places.rating",
        "places.userRatingCount",
        "places.location",
        "places.primaryTypeDisplayName",
        "places.googleMapsUri",
        "nextPageToken",
    ]
)

PAGE_SIZE = 20  # API maximum


def _to_business(place: dict, query: str) -> Business:
    location = place.get("location") or {}
    return Business(
        name=(place.get("displayName") or {}).get("text", ""),
        category=(place.get("primaryTypeDisplayName") or {}).get("text", ""),
        address=place.get("formattedAddress", ""),
        phone=place.get("internationalPhoneNumber")
        or place.get("nationalPhoneNumber")
        or "",
        website=place.get("websiteUri", ""),
        rating=place.get("rating"),
        reviews=place.get("userRatingCount"),
        latitude=location.get("latitude"),
        longitude=location.get("longitude"),
        maps_url=place.get("googleMapsUri", ""),
        query=query,
    )


def scrape(
    query: str,
    max_results: int = 50,
    api_key: Optional[str] = None,
    log=print,
    should_stop=None,
) -> Iterator[Business]:
    should_stop = should_stop or (lambda: False)
    key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not key:
        raise SystemExit(
            "No API key. Set GOOGLE_MAPS_API_KEY in your environment or .env, "
            "or pass --api-key."
        )

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    page_token = None
    yielded = 0

    while yielded < max_results and not should_stop():
        body = {"textQuery": query, "pageSize": min(PAGE_SIZE, max_results - yielded)}
        if page_token:
            body["pageToken"] = page_token

        response = requests.post(ENDPOINT, headers=headers, json=body, timeout=30)
        if response.status_code != 200:
            raise SystemExit(
                "Places API error {}: {}".format(response.status_code, response.text)
            )
        data = response.json()

        places = data.get("places") or []
        if not places:
            break

        for place in places:
            biz = _to_business(place, query)
            log("  [{}] {}".format(yielded + 1, biz.name))
            yield biz
            yielded += 1
            if yielded >= max_results:
                return

        page_token = data.get("nextPageToken")
        if not page_token:
            break
        # Google needs a moment before a fresh page token becomes valid.
        time.sleep(2)
