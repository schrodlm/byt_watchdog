"""Cross-source deduplication - detect same property listed on multiple sites."""

import math
import re
from scrapers.base import Listing

SKIP_WORDS = {
    "praha", "prague", "pronajem", "pronájem", "prodej",
    "bytu", "byt", "domu", "dum", "dům", "chalupy", "chalupa",
    "okres", "kraj", "obec", "mesto", "město",
}


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return round(2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def _normalize_location(loc: str) -> str:
    return re.sub(r"\s+", " ", loc.lower().replace(",", "").replace("-", " ")).strip()


def _locations_overlap(loc1: str, loc2: str) -> bool:
    n1 = _normalize_location(loc1)
    n2 = _normalize_location(loc2)
    if not n1 or not n2:
        return False
    tokens1 = {t for t in n1.split() if t not in SKIP_WORDS and len(t) > 2}
    tokens2 = {t for t in n2.split() if t not in SKIP_WORDS and len(t) > 2}
    if not tokens1 or not tokens2:
        return False
    return len(tokens1 & tokens2) > 0


def _are_same_property(li: Listing, lj: Listing) -> bool:
    """Determine if two listings from different sources are the same property."""
    if not li.price or not lj.price:
        return False
    price_diff = abs(li.price - lj.price) / max(li.price, lj.price)
    if price_diff > 0.10:
        return False

    if li.disposition and lj.disposition:
        if li.disposition.lower() != lj.disposition.lower():
            return False

    if li.size_m2 and lj.size_m2:
        if abs(li.size_m2 - lj.size_m2) > 5:
            return False

    # GPS proximity (strongest signal)
    if li.lat is not None and lj.lat is not None:
        dist = _haversine_m(li.lat, li.lon, lj.lat, lj.lon)
        if dist < 200:
            return True
        if dist > 1000:
            return False

    if not _locations_overlap(li.location, lj.location):
        return False

    return True


def cross_source_dedup(listings: list[Listing]) -> list[Listing]:
    """Detect same property listed on multiple sites.

    Uses strict pairwise matching (no transitive grouping).
    For each cross-source pair found, keeps the listing with more data
    and annotates it with the other source.
    """
    if len(listings) < 2:
        return listings

    # For each listing, track which other listing it's a duplicate of
    # Key: index to remove -> Value: index of the keeper
    remove_to_keeper: dict[int, int] = {}

    for i in range(len(listings)):
        if i in remove_to_keeper:
            continue
        for j in range(i + 1, len(listings)):
            if j in remove_to_keeper:
                continue
            if listings[i].source == listings[j].source:
                continue
            if not _are_same_property(listings[i], listings[j]):
                continue

            # Determine which to keep (more data = better)
            li, lj = listings[i], listings[j]
            i_score = sum([
                li.lat is not None,
                li.charges is not None,
                li.land_m2 is not None,
                li.size_m2 is not None,
                bool(li.image_url),
            ])
            j_score = sum([
                lj.lat is not None,
                lj.charges is not None,
                lj.land_m2 is not None,
                lj.size_m2 is not None,
                bool(lj.image_url),
            ])

            if i_score >= j_score:
                keeper_idx, remove_idx = i, j
            else:
                keeper_idx, remove_idx = j, i

            remove_to_keeper[remove_idx] = keeper_idx

    # Build cross_source annotations
    for remove_idx, keeper_idx in remove_to_keeper.items():
        keeper = listings[keeper_idx]
        removed = listings[remove_idx]
        # Only add if source is different from keeper's source
        if removed.source != keeper.source and removed.source not in keeper.cross_source:
            keeper.cross_source.append(removed.source)

    return [l for i, l in enumerate(listings) if i not in remove_to_keeper]
