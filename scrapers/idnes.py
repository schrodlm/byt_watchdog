import re
import time
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper, Listing

BASE_URL = "https://reality.idnes.cz"


class IdnesScraper(BaseScraper):
    name = "idnes"

    def _build_url(self) -> str:
        """Build search URL from profile scraper config."""
        cfg = self.scraper_cfg
        # Config provides the base search path, e.g. "/s/pronajem/byty/praha-7/"
        search_path = cfg.get("search_path", "/s/pronajem/byty/praha-7/")
        url = f"{BASE_URL}{search_path}"

        # Add price filters
        params = []
        if self.min_price > 0:
            params.append(f"s-qc%5BpriceMin%5D={self.min_price}")
        if self.max_price > 0:
            params.append(f"s-qc%5BpriceMax%5D={self.max_price}")

        # Add any extra params from config
        extra = cfg.get("extra_params", "")
        if extra:
            params.append(extra)

        if params:
            url += "?" + "&".join(params)
        return url

    def scrape(self) -> list[Listing]:
        cfg = self.scraper_cfg
        if not cfg.get("enabled", False):
            return []

        listings = []
        seen_ids = set()
        page = 0  # idnes uses 0-indexed pagination (page 1 = no param, page 2 = ?page=1)

        while True:
            url = self._build_url()
            if page > 0:
                sep = "&" if "?" in url else "?"
                url += f"{sep}page={page}"

            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            # Find listing cards (skip ad items)
            cards = soup.select("div.c-products__item")
            cards = [c for c in cards if "c-products__item-advertisment" not in c.get("class", [])]

            if not cards:
                break

            page_had_listings = False
            for card in cards:
                listing = self._parse_card(card)
                if listing and listing.id not in seen_ids:
                    seen_ids.add(listing.id)
                    page_had_listings = True
                    listings.append(listing)

            if not page_had_listings:
                break

            # Check for next page
            next_link = soup.select_one("a.paging__item.next")
            if not next_link:
                break

            page += 1
            time.sleep(1.5)

        return listings

    def _parse_card(self, card) -> Listing | None:
        """Extract listing data from an Idnes card element."""
        # Find the main link
        link = card.select_one("a.c-products__link")
        if not link:
            return None

        href = link.get("href", "")
        if not href.startswith("http"):
            href = f"{BASE_URL}{href}"

        # Extract estate ID from snippet ID
        snippet = card.select_one("[id^='snippet-s-result-article-']")
        estate_id = ""
        if snippet:
            estate_id = snippet.get("id", "").replace("snippet-s-result-article-", "")
        if not estate_id:
            # Fallback: extract from URL
            id_match = re.search(r"/([a-f0-9]{20,})/", href)
            if id_match:
                estate_id = id_match.group(1)
        if not estate_id:
            return None

        # Title
        title_el = card.select_one("h2.c-products__title")
        title = title_el.get_text(strip=True) if title_el else ""

        # Price
        price = 0
        price_el = card.select_one("p.c-products__price strong")
        if price_el:
            price_text = price_el.get_text(strip=True)
            price_match = re.search(r"([\d\s\xa0]+)", price_text)
            if price_match:
                price_str = price_match.group(1).replace(" ", "").replace("\xa0", "")
                try:
                    price = int(price_str)
                except ValueError:
                    pass

        if self.max_price > 0 and price > self.max_price:
            return None
        if price < self.min_price or price == 0:
            return None

        # Location
        location = ""
        info_el = card.select_one("p.c-products__info")
        if info_el:
            location = info_el.get_text(strip=True)

        # Image
        image_url = None
        img = card.select_one("img.image-preloading")
        if img:
            image_url = img.get("data-src") or img.get("src")

        # Size from title: "pronajem bytu 2+1 60 m2"
        size = None
        size_match = re.search(r"(\d+)\s*m[2²]", title, re.IGNORECASE)
        if size_match:
            size = int(size_match.group(1))

        # Land area from title: "s pozemkem 212 m2" or "pozemek 1 200 m2"
        land = None
        land_match = re.search(r"(?:pozemek|pozemkem)\s+([\d\s]+)\s*m[2²]", title, re.IGNORECASE)
        if land_match:
            land = int(land_match.group(1).replace(" ", "").replace("\xa0", ""))

        # Disposition from title
        disposition = None
        disp_match = re.search(r"(\d\+(?:kk|1|\d))", title, re.IGNORECASE)
        if disp_match:
            disposition = disp_match.group(1).lower()

        # Agency name
        agency = link.get("data-brand", "")

        return Listing(
            id=f"idnes:{estate_id}",
            source="idnes",
            title=title,
            price=price,
            location=location,
            url=href,
            image_url=image_url,
            size_m2=size,
            disposition=disposition,
            land_m2=land,
        )
