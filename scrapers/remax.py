import re
import time
import requests
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper, Listing

SEARCH_URL = (
    "https://www.remax-czech.cz/reality/vyhledavani/"
    "?hledani=2"
    "&price_to={max_price}"
    "&regions%5B19%5D%5B78%5D=on"
    "&types%5B4%5D=on"
)


class RemaxScraper(BaseScraper):
    name = "remax"

    def scrape(self) -> list[Listing]:
        listings = []
        page = 1

        while True:
            url = SEARCH_URL.format(max_price=self.max_price)
            if page > 1:
                url += f"&stranka={page}"

            resp = requests.get(url, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
            })
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            # Find listing cards - RE/MAX uses pl-items or similar listing containers
            cards = soup.select("div.pl-items__item, article.property-card, div.card-property")

            # Fallback: look for links to /reality/detail/
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

            # Check if there's a next page
            next_link = soup.select_one('a[rel="next"], a.pagination__next, li.next a')
            if not next_link:
                # Also check if we got fewer results than expected
                break

            page += 1
            time.sleep(1.5)

        return listings

    def _find_listing_blocks(self, soup: BeautifulSoup) -> list:
        """Find listing blocks by looking for detail links."""
        blocks = []
        for link in soup.find_all("a", href=re.compile(r"/reality/detail/\d+")):
            # Walk up to find a reasonable container
            parent = link.parent
            for _ in range(5):
                if parent and parent.name in ("div", "article", "li") and parent not in blocks:
                    # Check if this container has price-like text
                    text = parent.get_text()
                    if "Kc" in text or "Kč" in text or re.search(r"\d[\d\s]+Kc", text):
                        blocks.append(parent)
                        break
                if parent:
                    parent = parent.parent
        return blocks

    def _parse_card(self, card) -> Listing | None:
        """Extract listing data from a card element."""
        # Find detail link
        link = card.find("a", href=re.compile(r"/reality/detail/\d+"))
        if not link:
            return None

        href = link.get("href", "")
        detail_url = href if href.startswith("http") else f"https://www.remax-czech.cz{href}"

        # Extract listing ID from URL
        id_match = re.search(r"/detail/(\d+)/", href)
        if not id_match:
            return None
        listing_id = id_match.group(1)

        # Title
        title = ""
        title_el = card.find(["h2", "h3", "h4"]) or link
        if title_el:
            title = title_el.get_text(strip=True)

        # Price - look for numbers followed by Kc/Kč
        price = 0
        card_text = card.get_text()
        price_match = re.search(r"([\d\s]+)\s*(?:Kc|Kč)", card_text)
        if price_match:
            price_str = price_match.group(1).replace(" ", "").replace("\xa0", "")
            try:
                price = int(price_str)
            except ValueError:
                pass

        if price > self.max_price or price == 0:
            return None

        # Location - try to find Praha 7 reference
        location = ""
        loc_match = re.search(r"Praha\s*\d+\s*[-–]\s*\w+", card_text)
        if loc_match:
            location = loc_match.group(0)
        elif "Praha" in card_text:
            location = "Praha"

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
        )
