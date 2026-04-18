import re
import time
import requests
from scrapers.base import BaseScraper, Listing

# Disposition ID -> human-readable label
DISPOSITIONS = {
    2: "1+kk", 3: "1+1", 4: "2+kk", 5: "2+1",
    6: "3+kk", 7: "3+1", 8: "4+kk", 9: "4+1",
    10: "5+kk", 11: "5+1", 12: "6+", 16: "atypicky",
    47: "pokoj",
}

# House sub-type ID -> label
HOUSE_SUBTYPES = {
    37: "rodinny dum", 39: "vila", 43: "chalupa",
    44: "zemedelska usedlost", 54: "vicegeneracni dum",
}

API_URL = "https://www.sreality.cz/api/cs/v2/estates"


class SrealityScraper(BaseScraper):
    name = "sreality"

    def _build_params(self) -> dict:
        cfg = self.scraper_cfg
        params = {
            "category_main_cb": cfg.get("category_main_cb", 1),
            "category_type_cb": cfg.get("category_type_cb", 2),
            "locality_district_id": cfg.get("locality_district_id", 5007),
            "per_page": 500,
            "page": 1,
        }
        if self.max_price > 0:
            params["czk_price_summary_order2"] = f"{self.min_price}|{self.max_price}"
        sub_cb = cfg.get("category_sub_cb")
        if sub_cb:
            params["category_sub_cb"] = sub_cb
        min_land = self.profile.get("search", {}).get("min_land_m2", 0)
        if min_land > 0:
            params["estate_area"] = f"{min_land}|100000000"
        return params

    def scrape(self) -> list[Listing]:
        cfg = self.scraper_cfg
        if not cfg.get("enabled", True):
            return []

        # Sreality's API is load-balanced across servers with different indexes.
        # A single request may miss listings. We fetch 3 times and merge results
        # to get a complete picture.
        all_estates = {}  # hash_id -> estate dict
        params = self._build_params()

        for attempt in range(3):
            resp = requests.get(API_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            estates = data.get("_embedded", {}).get("estates", [])
            new_count = 0
            for e in estates:
                hid = e.get("hash_id")
                if hid and hid not in all_estates:
                    all_estates[hid] = e
                    new_count += 1
            if new_count == 0 and attempt > 0:
                break  # No new results, second server not different
            time.sleep(1)

        listings = []
        for e in all_estates.values():
            hash_id = e.get("hash_id")
            price = e.get("price", 0)
            if self.max_price > 0 and (price > self.max_price or price < self.min_price):
                continue

            seo = e.get("seo", {})
            try:
                sub_cb_val = int(seo.get("category_sub_cb", 0))
            except (ValueError, TypeError):
                sub_cb_val = 0
            try:
                main_cb = int(seo.get("category_main_cb", 1))
            except (ValueError, TypeError):
                main_cb = 1
            locality_seo = seo.get("locality", "")

            disp_label = DISPOSITIONS.get(sub_cb_val, None)
            if not disp_label and main_cb == 2:
                disp_label = HOUSE_SUBTYPES.get(sub_cb_val, None)

            images = e.get("_links", {}).get("images", [])
            image_url = images[0]["href"] if images else None

            name = e.get("name", "")

            size = None
            size_match = re.search(r"(\d+)\s*m[2²]", name)
            if size_match:
                size = int(size_match.group(1))

            land = None
            land_match = re.search(r"pozemek\s+([\d\s]+)\s*m[2²]", name, re.IGNORECASE)
            if land_match:
                land = int(land_match.group(1).replace(" ", "").replace("\xa0", ""))

            gps = e.get("gps", {})
            lat = gps.get("lat")
            lon = gps.get("lon")

            type_cb = cfg.get("category_type_cb", 2)
            offer = "pronajem" if type_cb == 2 else "prodej"
            cat_map = {1: "byt", 2: "dum", 3: "pozemek"}
            cat = cat_map.get(main_cb, "byt")
            disp_slug = (disp_label or str(sub_cb_val)).replace(" ", "-")
            detail_url = f"https://www.sreality.cz/detail/{offer}/{cat}/{disp_slug}/{locality_seo}/{hash_id}"

            listings.append(Listing(
                id=f"sreality:{hash_id}",
                source="sreality",
                title=name,
                price=price,
                location=e.get("locality", ""),
                url=detail_url,
                image_url=image_url,
                size_m2=size,
                disposition=disp_label,
                lat=lat,
                lon=lon,
                land_m2=land,
            ))

        return listings
