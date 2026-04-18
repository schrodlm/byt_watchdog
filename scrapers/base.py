from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Listing:
    id: str                    # "{source}:{site_id}" e.g. "sreality:942891852"
    source: str                # "sreality" | "bezrealitky" | "remax"
    title: str
    price: int                 # Monthly rent in CZK
    location: str
    url: str                   # Detail page URL
    image_url: str | None = None
    size_m2: int | None = None
    disposition: str | None = None  # "2+kk", "1+1", etc.
    lat: float | None = None
    lon: float | None = None
    charges: int | None = None      # Additional monthly charges (poplatky)
    score: int = 0                  # Smart score 0-100
    price_drop_from: int | None = None  # Previous price if dropped
    metro_station: str | None = None
    metro_distance_m: int | None = None
    cross_source: list[str] = field(default_factory=list)  # Other sources with same flat


class BaseScraper(ABC):
    name: str = "base"

    def __init__(self, config: dict):
        self.config = config
        self.min_price = config.get("search", {}).get("min_price", 0)
        self.max_price = config.get("search", {}).get("max_price", 25000)

    @abstractmethod
    def scrape(self) -> list[Listing]:
        """Return all listings matching the search criteria."""
        ...
