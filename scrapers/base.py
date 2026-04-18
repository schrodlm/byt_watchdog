from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Listing:
    id: str                    # "{source}:{site_id}" e.g. "sreality:942891852"
    source: str                # "sreality" | "bezrealitky" | "remax"
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
    price_drop_from: int | None = None
    nearest_stop: str | None = None     # Nearest tram/bus stop with lines
    stop_distance_m: int | None = None
    cross_source: list[str] = field(default_factory=list)


class BaseScraper(ABC):
    name: str = "base"

    def __init__(self, profile: dict):
        self.profile = profile
        search = profile.get("search", {})
        self.min_price = search.get("min_price", 0)
        self.max_price = search.get("max_price", 25000)
        self.scraper_cfg = profile.get("scrapers", {}).get(self.name, {})

    @abstractmethod
    def scrape(self) -> list[Listing]:
        """Return all listings matching the search criteria."""
        ...
