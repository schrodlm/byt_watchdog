from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@dataclass
class Listing:
    id: str                    # "{source}:{site_id}" e.g. "sreality:942891852"
    source: str                # "sreality" | "bezrealitky" | "remax" | "idnes"
    title: str
    price: int                 # Price in CZK (monthly rent or sale price)
    location: str
    url: str                   # Detail page URL
    image_url: str | None = None
    size_m2: int | None = None
    disposition: str | None = None  # "2+kk", "1+1", etc.
    lat: float | None = None
    lon: float | None = None
    charges: int | None = None      # Additional monthly charges (poplatky)
    land_m2: int | None = None      # Land/plot area for houses
    score: int = 0
    urgency: str = "normal"         # "hot" | "normal" | "low"
    price_drop_from: int | None = None
    nearest_stop: str | None = None
    stop_distance_m: int | None = None
    cross_source: list[str] = field(default_factory=list)


def get_http_session() -> requests.Session:
    """Create an HTTP session with automatic retry on transient errors."""
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    })
    return session


class BaseScraper(ABC):
    name: str = "base"

    def __init__(self, profile: dict):
        self.profile = profile
        search = profile.get("search", {})
        self.min_price = search.get("min_price", 0)
        self.max_price = search.get("max_price", 0)
        self.scraper_cfg = profile.get("scrapers", {}).get(self.name, {})
        self.session = get_http_session()

    @abstractmethod
    def scrape(self) -> list[Listing]:
        """Return all listings matching the search criteria."""
        ...
