"""Cross-source deduplication - detect same property listed on multiple sites."""

import math
from scrapers.base import Listing

# Common words to skip when comparing locations (Czech real estate terms)
SKIP_WORDS = {
    "praha", "prague", "pronajem", "pronájem", "prodej",
    "bytu", "byt", "domu", "dum", "dům", "chalupy", "chalupa",
    "okres", "kraj", "obec", "mesto", "město",
}


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Distance in meters between two GPS points."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return round(2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def _normalize_location(loc: str) -> str:
    return loc.lower().replace(",", "").replace("-", " ").replace("  ", " ").strip()


def _locations_overlap(loc1: str, loc2: str) -> bool:
    n1 = _normalize_location(loc1)
    n2 = _normalize_location(loc2)
    if not n1 or not n2:
        return False

    tokens1 = {t for t in n1.split() if t not in SKIP_WORDS and len(t) > 2}
    tokens2 = {t for t in n2.split() if t not in SKIP_WORDS and len(t) > 2}

    if not tokens1 or not tokens2:
        return False

    overlap = tokens1 & tokens2
    return len(overlap) > 0


def _are_same_property(li: Listing, lj: Listing) -> bool:
    """Determine if two listings from different sources are the same property."""
    # Price within 10%
    if not li.price or not lj.price:
        return False
    price_diff = abs(li.price - lj.price) / max(li.price, lj.price)
    if price_diff > 0.10:
        return False

    # Same disposition (if both known)
    if li.disposition and lj.disposition:
        if li.disposition.lower() != lj.disposition.lower():
            return False

    # Size within 5 m2 (if both known)
    if li.size_m2 and lj.size_m2:
        if abs(li.size_m2 - lj.size_m2) > 5:
            return False

    # GPS proximity check (strongest signal - if both have coords)
    if li.lat is not None and lj.lat is not None:
        dist = _haversine_m(li.lat, li.lon, lj.lat, lj.lon)
        if dist < 200:
            return True  # Within 200m + similar price = very likely same
        if dist > 1000:
            return False  # More than 1km apart = definitely different
        # 200-1000m: fall through to location text check

    # Location text overlap (fallback when no GPS or medium distance)
    if not _locations_overlap(li.location, lj.location):
        return False

    return True


def cross_source_dedup(listings: list[Listing]) -> list[Listing]:
    """Mark listings that appear on multiple sources.

    Uses fuzzy matching: GPS proximity + price similarity + disposition/size.
    Returns deduplicated list (keeps the listing with most data).
    """
    if len(listings) < 2:
        return listings

    groups: list[list[int]] = []
    used = set()

    for i in range(len(listings)):
        if i in used:
            continue
        group = [i]
        used.add(i)
        li = listings[i]

        for j in range(i + 1, len(listings)):
            if j in used:
                continue
            lj = listings[j]

            # Must be from different sources
            if li.source == lj.source:
                continue

            if _are_same_property(li, lj):
                group.append(j)
                used.add(j)

        if len(group) > 1:
            groups.append(group)

    # Mark cross-source matches
    remove_indices = set()
    for group in groups:
        group_listings = [(idx, listings[idx]) for idx in group]
        group_listings.sort(key=lambda x: (
            x[1].lat is not None,
            x[1].charges is not None,
            x[1].land_m2 is not None,
            x[1].size_m2 is not None,
        ), reverse=True)

        keeper_idx, keeper = group_listings[0]
        other_sources = [listings[idx].source for idx, _ in group_listings[1:]]
        keeper.cross_source = other_sources

        for idx, _ in group_listings[1:]:
            remove_indices.add(idx)

    return [l for i, l in enumerate(listings) if i not in remove_indices]
