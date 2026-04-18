from scrapers.sreality import SrealityScraper
from scrapers.bezrealitky import BezrealitkyScraper
from scrapers.remax import RemaxScraper
from scrapers.idnes import IdnesScraper

ALL_SCRAPERS = {
    "sreality": SrealityScraper,
    "bezrealitky": BezrealitkyScraper,
    "remax": RemaxScraper,
    "idnes": IdnesScraper,
}
