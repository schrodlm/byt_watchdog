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

API_URL = "https://www.sreality.cz/api/cs/v2/estates"


class SrealityScraper(BaseScraper):
    name = "sreality"

    def scrape(self) -> list[Listing]:
        listings = []
        page = 1
        per_page = 60

        while True:
            params = {
                "category_main_cb": 1,          # byty
                "category_type_cb": 2,          # pronajem
                "locality_district_id": 5007,   # Praha 7
                "per_page": per_page,
                "page": page,
                "czk_price_summary_order2": f"{self.min_price}|{self.max_price}",
            }

            resp = requests.get(API_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            estates = data.get("_embedded", {}).get("estates", [])
            if not estates:
                break

            for e in estates:
                hash_id = e.get("hash_id")
                if not hash_id:
                    continue

                price = e.get("price", 0)
                if price > self.max_price or price < self.min_price:
                    continue

                seo = e.get("seo", {})
                sub_cb = seo.get("category_sub_cb", "")
                locality_seo = seo.get("locality", "")
                disp_label = DISPOSITIONS.get(sub_cb, str(sub_cb))

                images = e.get("_links", {}).get("images", [])
                image_url = images[0]["href"] if images else None

                # Extract size from name like "Pronajem bytu 2+kk 45 m2"
                name = e.get("name", "")
                size = None
                size_match = re.search(r"(\d+)\s*m[2²]", name)
                if size_match:
                    size = int(size_match.group(1))

                # Extract GPS
                gps = e.get("gps", {})
                lat = gps.get("lat")
                lon = gps.get("lon")

                detail_url = f"https://www.sreality.cz/detail/pronajem/byt/{disp_label}/{locality_seo}/{hash_id}"

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
                ))

            total = data.get("result_size", 0)
            if page * per_page >= total:
                break
            page += 1
            time.sleep(1)

        return listings
