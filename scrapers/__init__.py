from scrapers.sreality import SrealityScraper
from scrapers.bezrealitky import BezrealitkyScraper
from scrapers.remax import RemaxScraper

ALL_SCRAPERS = {
    "sreality": SrealityScraper,
    "bezrealitky": BezrealitkyScraper,
    "remax": RemaxScraper,
}
