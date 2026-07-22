"""Shared data model for a scraped business listing."""

from dataclasses import dataclass, field, asdict
from typing import List, Optional

FIELDNAMES = [
    "name",
    "category",
    "address",
    "phone",
    "website",
    "emails",
    "rating",
    "reviews",
    "latitude",
    "longitude",
    "maps_url",
    "query",
]


@dataclass
class Business:
    name: str = ""
    category: str = ""
    address: str = ""
    phone: str = ""
    website: str = ""
    emails: List[str] = field(default_factory=list)
    rating: Optional[float] = None
    reviews: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    maps_url: str = ""
    query: str = ""

    def key(self) -> str:
        """Identity used for de-duplication across queries and sources."""
        if self.maps_url:
            return self.maps_url
        return "{}|{}".format(self.name.strip().lower(), self.address.strip().lower())

    def to_row(self) -> dict:
        row = asdict(self)
        row["emails"] = ", ".join(self.emails)
        return row
