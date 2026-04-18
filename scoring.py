"""Smart scoring system for ranking listings."""

from scrapers.base import Listing


def compute_score(listing: Listing, profile: dict) -> int:
    """Compute a 0-100 smart score for a listing based on profile scoring config."""
    scoring_cfg = profile.get("scoring", {})
    if not scoring_cfg:
        return 0

    total = 0.0

    # Price per m2 component (for flats/rentals)
    w_price_m2 = scoring_cfg.get("price_per_m2_weight", 0)
    if w_price_m2 and listing.size_m2 and listing.size_m2 > 0:
        price_per_m2 = listing.price / listing.size_m2
        score = max(0.0, min(100.0, (550 - price_per_m2) / 2.5))
        total += score * w_price_m2 / 100

    # Disposition component
    w_disp = scoring_cfg.get("disposition_weight", 0)
    preferred = scoring_cfg.get("preferred_dispositions", [])
    if w_disp and listing.disposition and preferred:
        disp_lower = listing.disposition.lower()
        preferred_lower = [d.lower() for d in preferred]
        if disp_lower in preferred_lower:
            idx = preferred_lower.index(disp_lower)
            score = max(20.0, 100.0 - idx * 20)
        else:
            score = 10.0
        total += score * w_disp / 100

    # Size component (building/usable area)
    w_size = scoring_cfg.get("size_weight", 0)
    ideal = scoring_cfg.get("ideal_size_m2", 55)
    if w_size and listing.size_m2 and ideal > 0:
        score = min(100.0, (listing.size_m2 / ideal) * 100)
        total += score * w_size / 100

    # Neighborhood component
    w_hood = scoring_cfg.get("neighborhood_weight", 0)
    preferred_hoods = scoring_cfg.get("preferred_neighborhoods", [])
    if w_hood and listing.location and preferred_hoods:
        loc_lower = listing.location.lower()
        score = 20.0
        for i, hood in enumerate(preferred_hoods):
            if hood.lower() in loc_lower:
                score = max(20.0, 100.0 - i * 20)
                break
        total += score * w_hood / 100

    # Land area component (for houses/cottages)
    w_land = scoring_cfg.get("land_weight", 0)
    ideal_land = scoring_cfg.get("ideal_land_m2", 2000)
    if w_land and listing.land_m2 and ideal_land > 0:
        score = min(100.0, (listing.land_m2 / ideal_land) * 100)
        total += score * w_land / 100

    # Total price component (for sale listings - lower price = better)
    w_total_price = scoring_cfg.get("price_weight", 0)
    max_good = scoring_cfg.get("max_good_price", 3000000)
    if w_total_price and listing.price and max_good > 0:
        # At max_good_price or below = 100, at 2x max_good = 0
        ratio = listing.price / max_good
        score = max(0.0, min(100.0, (2.0 - ratio) * 100))
        total += score * w_total_price / 100

    return round(total)
