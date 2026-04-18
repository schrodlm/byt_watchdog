from abc import ABC, abstractmethod
from dataclasses import dataclass


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


class BaseScraper(ABC):
    name: str = "base"

    def __init__(self, config: dict):
        self.config = config
        self.max_price = config.get("search", {}).get("max_price", 25000)

    @abstractmethod
    def scrape(self) -> list[Listing]:
        """Return all listings matching the search criteria."""
        ...
