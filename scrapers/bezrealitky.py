import json
import re
import time
import requests
from scrapers.base import BaseScraper, Listing

SEARCH_URL = (
    "https://www.bezrealitky.cz/vyhledat"
    "?currency=CZK"
    "&estateType=BYT"
    "&offerType=PRONAJEM"
    "&osm_value=Praha+7%2C+obvod+Praha+7%2C+Hlavn%C3%AD+m%C4%9Bsto+Praha%2C+Praha%2C+%C4%8Cesko"
    "&priceFrom={min_price}"
    "&priceTo={max_price}"
    "&regionOsmIds=R20000064250"
    "&location=exact"
)

# Disposition enum -> human-readable
DISPOSITIONS = {
    "DISP_1_KK": "1+kk", "DISP_1_1": "1+1",
    "DISP_2_KK": "2+kk", "DISP_2_1": "2+1",
    "DISP_3_KK": "3+kk", "DISP_3_1": "3+1",
    "DISP_4_KK": "4+kk", "DISP_4_1": "4+1",
    "DISP_5_KK": "5+kk", "DISP_5_1": "5+1",
    "DISP_6": "6+", "DISP_OTHER": "atypicky",
}

DETAIL_BASE = "https://www.bezrealitky.cz/nemovitosti-byty-domy"


def _apollo_get(obj: dict, prefix: str):
    """Get value from Apollo cache key that may have parenthesized params."""
    for key, val in obj.items():
        if key == prefix or key.startswith(prefix + "("):
            return val
    return None


class BezrealitkyScraper(BaseScraper):
    name = "bezrealitky"

    def scrape(self) -> list[Listing]:
        listings = []
        page = 1

        while True:
            url = SEARCH_URL.format(min_price=self.min_price, max_price=self.max_price)
            if page > 1:
                url += f"&page={page}"

            resp = requests.get(url, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
            })
            resp.raise_for_status()

            # Extract __NEXT_DATA__ JSON
            match = re.search(
                r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
                resp.text, re.DOTALL
            )
            if not match:
                break

            next_data = json.loads(match.group(1))
            cache = next_data.get("props", {}).get("pageProps", {}).get("apolloCache", {})
            if not cache:
                break

            # Find the listAdverts result to get total count and refs
            advert_list = None
            total_count = 0
            for key, val in cache.items():
                if key.startswith("listAdverts(") or (isinstance(val, dict) and val.get("__typename") == "AdvertList"):
                    if isinstance(val, dict) and "list" in val:
                        advert_list = val
                        total_count = val.get("totalCount", 0)
                        break

            # Also check ROOT_QUERY for nested listAdverts
            root = cache.get("ROOT_QUERY", {})
            if not advert_list:
                for key, val in root.items():
                    if key.startswith("listAdverts(") and isinstance(val, dict):
                        advert_list = val
                        total_count = val.get("totalCount", 0)
                        break

            if not advert_list:
                break

            # Resolve advert refs
            refs = advert_list.get("list", [])
            page_had_listings = False

            for ref in refs:
                ref_key = ref.get("__ref", "") if isinstance(ref, dict) else ""
                advert = cache.get(ref_key, {})
                if not advert:
                    continue

                page_had_listings = True
                advert_id = advert.get("id", "")
                uri = advert.get("uri", "")
                price = advert.get("price", 0)

                if price > self.max_price or price < self.min_price:
                    continue
                if advert.get("reserved", False):
                    continue

                address = _apollo_get(advert, "address") or ""
                # Guard against address being a dict (Apollo ref)
                if isinstance(address, dict):
                    address = ""
                disposition_raw = advert.get("disposition", "")
                disposition = DISPOSITIONS.get(disposition_raw, disposition_raw)
                surface = advert.get("surface")
                charges = advert.get("charges")

                # Extract GPS (bezrealitky uses "lng" not "lon")
                gps = advert.get("gps", {})
                lat = None
                lon = None
                if isinstance(gps, dict):
                    lat = gps.get("lat")
                    lon = gps.get("lng")

                # Resolve main image
                image_url = None
                main_img_ref = advert.get("mainImage", {})
                if isinstance(main_img_ref, dict) and "__ref" in main_img_ref:
                    img_obj = cache.get(main_img_ref["__ref"], {})
                    image_url = _apollo_get(img_obj, "url")

                title_parts = ["Pronajem"]
                if disposition:
                    title_parts.append(disposition)
                if surface:
                    title_parts.append(f"{surface} m2")
                if address:
                    title_parts.append(address)
                title = " - ".join(title_parts)

                listings.append(Listing(
                    id=f"bezrealitky:{advert_id}",
                    source="bezrealitky",
                    title=title,
                    price=price,
                    location=address,
                    url=f"{DETAIL_BASE}/{uri}",
                    image_url=image_url,
                    size_m2=int(surface) if surface else None,
                    disposition=disposition,
                    lat=lat,
                    lon=lon,
                    charges=int(charges) if charges else None,
                ))

            if not page_had_listings or page * 15 >= total_count:
                break
            page += 1
            time.sleep(1.5)

        return listings
