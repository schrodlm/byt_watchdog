import re
import time
import requests
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper, Listing


class RemaxScraper(BaseScraper):
    name = "remax"

    def _build_url(self) -> str:
        """Build search URL from profile config or use custom search_url."""
        cfg = self.scraper_cfg
        custom_url = cfg.get("search_url")
        if custom_url:
            return custom_url.format(
                min_price=self.min_price,
                max_price=self.max_price,
            )
        # Fallback: should not happen if config is correct
        return "https://www.remax-czech.cz/reality/vyhledavani/?hledani=1"

    def scrape(self) -> list[Listing]:
        cfg = self.scraper_cfg
        if not cfg.get("enabled", True):
            return []

        listings = []
        page = 1

        while True:
            url = self._build_url()
            if page > 1:
                url += f"&stranka={page}"

            resp = requests.get(url, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
            })
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            # Find listing cards
            cards = soup.select("div.pl-items__item, article.property-card, div.card-property")
            if not cards:
                cards = self._find_listing_blocks(soup)
            if not cards:
                break

            page_had_listings = False
            for card in cards:
                listing = self._parse_card(card)
                if listing:
                    page_had_listings = True
                    listings.append(listing)

            if not page_had_listings:
                break

            next_link = soup.select_one('a[rel="next"], a.pagination__next, li.next a')
            if not next_link:
                break

            page += 1
            time.sleep(1.5)

        return listings

    def _find_listing_blocks(self, soup: BeautifulSoup) -> list:
        blocks = []
        seen_links = set()
        for link in soup.find_all("a", href=re.compile(r"/reality/detail/\d+")):
            href = link.get("href", "")
            if href in seen_links:
                continue
            seen_links.add(href)
            parent = link.parent
            for _ in range(5):
                if parent and parent.name in ("div", "article", "li") and parent not in blocks:
                    text = parent.get_text()
                    if "Kc" in text or "Kč" in text or re.search(r"\d[\d\s]+Kc", text):
                        blocks.append(parent)
                        break
                if parent:
                    parent = parent.parent
        return blocks

    def _parse_card(self, card) -> Listing | None:
        link = card.find("a", href=re.compile(r"/reality/detail/\d+"))
        if not link:
            return None

        href = link.get("href", "")
        detail_url = href if href.startswith("http") else f"https://www.remax-czech.cz{href}"

        id_match = re.search(r"/detail/(\d+)", href)
        if not id_match:
            return None
        listing_id = id_match.group(1)

        # Prefer data-* attributes
        data_price = card.get("data-price")
        data_title = card.get("data-title")
        data_address = card.get("data-display-address")

        # Title
        title = ""
        if data_title:
            title = data_title
        else:
            title_el = card.find(["h2", "h3", "h4"]) or link
            if title_el:
                title = title_el.get_text(strip=True)
            title = re.sub(r"\s*\(ID\s+[^)]+\)\s*$", "", title)

        # Price
        price = 0
        if data_price:
            try:
                price = int(data_price)
            except ValueError:
                pass

        if not price:
            card_text = card.get_text()
            price_match = re.search(r"(\d[\d\s\xa0]*\d)\s*(?:Kc|Kč)", card_text)
            if not price_match:
                price_match = re.search(r"(\d)\s*(?:Kc|Kč)", card_text)
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

        card_text = card.get_text()

        # Location
        location = ""
        if data_address:
            location = data_address
        else:
            loc_match = re.search(r"(?:Praha\s*\d+\s*[-–]\s*\w+|[A-Z][a-záčďéěíňóřšťúůýž]+\s*[-–]\s*\w+)", card_text)
            if loc_match:
                location = loc_match.group(0)

        # Image
        image_url = None
        img = card.find("img")
        if img:
            image_url = img.get("src") or img.get("data-src")
            if image_url and not image_url.startswith("http"):
                image_url = f"https://www.remax-czech.cz{image_url}"

        # Size
        size = None
        size_match = re.search(r"(\d+)\s*m[2²]", card_text)
        if size_match:
            size = int(size_match.group(1))

        # Land area - "pozemek X m2" or "X m² pozemek"
        land = None
        land_match = re.search(r"pozemek\s+([\d\s]+)\s*m[2²]", card_text, re.IGNORECASE)
        if land_match:
            land = int(land_match.group(1).replace(" ", "").replace("\xa0", ""))

        # Disposition
        disposition = None
        disp_match = re.search(r"(\d\+(?:kk|1|\d))", card_text, re.IGNORECASE)
        if disp_match:
            disposition = disp_match.group(1)

        return Listing(
            id=f"remax:{listing_id}",
            source="remax",
            title=title or f"RE/MAX - {disposition or ''} {location}".strip(),
            price=price,
            location=location,
            url=detail_url,
            image_url=image_url,
            size_m2=size,
            disposition=disposition,
            land_m2=land,
        )
