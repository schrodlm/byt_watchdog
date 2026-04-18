"""Cross-source deduplication - detect same flat listed on multiple sites."""

from scrapers.base import Listing


def _normalize_location(loc: str) -> str:
    """Normalize location for comparison."""
    return loc.lower().replace(",", "").replace("-", " ").replace("  ", " ").strip()


def _locations_overlap(loc1: str, loc2: str) -> bool:
    """Check if two locations likely refer to the same place."""
    n1 = _normalize_location(loc1)
    n2 = _normalize_location(loc2)
    if not n1 or not n2:
        return False

    # Extract meaningful tokens (skip common words)
    skip = {"praha", "prague", "7", "pronajem", "bytu", "byt"}
    tokens1 = {t for t in n1.split() if t not in skip and len(t) > 2}
    tokens2 = {t for t in n2.split() if t not in skip and len(t) > 2}

    if not tokens1 or not tokens2:
        return False

    # Check if any meaningful tokens overlap
    overlap = tokens1 & tokens2
    return len(overlap) > 0


def cross_source_dedup(listings: list[Listing]) -> list[Listing]:
    """Mark listings that appear on multiple sources.

    Uses fuzzy matching: same disposition + similar price + overlapping location.
    Does NOT remove duplicates - just marks them with cross_source field.
    Returns deduplicated list (keeps the listing with most data).
    """
    if len(listings) < 2:
        return listings

    # Group by (disposition, approximate price, approximate size)
    groups: list[list[int]] = []  # groups of indices
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

            # Price within 10%
            if li.price and lj.price:
                price_diff = abs(li.price - lj.price) / max(li.price, lj.price)
                if price_diff > 0.10:
                    continue
            else:
                continue

            # Same disposition (if both known)
            if li.disposition and lj.disposition:
                if li.disposition.lower() != lj.disposition.lower():
                    continue

            # Size within 5 m2 (if both known)
            if li.size_m2 and lj.size_m2:
                if abs(li.size_m2 - lj.size_m2) > 5:
                    continue

            # Location overlap
            if not _locations_overlap(li.location, lj.location):
                continue

            group.append(j)
            used.add(j)

        if len(group) > 1:
            groups.append(group)

    # Mark cross-source matches
    remove_indices = set()
    for group in groups:
        # Pick the "best" listing (most data) to keep
        group_listings = [(idx, listings[idx]) for idx in group]
        group_listings.sort(key=lambda x: (
            x[1].lat is not None,       # prefer with GPS
            x[1].charges is not None,   # prefer with charges
            x[1].size_m2 is not None,   # prefer with size
        ), reverse=True)

        keeper_idx, keeper = group_listings[0]
        other_sources = [listings[idx].source for idx, _ in group_listings[1:]]
        keeper.cross_source = other_sources

        for idx, _ in group_listings[1:]:
            remove_indices.add(idx)

    # Return filtered list
    return [l for i, l in enumerate(listings) if i not in remove_indices]
