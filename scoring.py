"""Smart scoring system for ranking listings."""

from scrapers.base import Listing


def compute_score(listing: Listing, config: dict) -> int:
    """Compute a 0-100 smart score for a listing based on config preferences."""
    scoring_cfg = config.get("scoring", {})
    if not scoring_cfg:
        return 0

    total = 0.0

    # Price per m2 component
    w_price = scoring_cfg.get("price_per_m2_weight", 40)
    if w_price and listing.size_m2 and listing.size_m2 > 0:
        price_per_m2 = listing.price / listing.size_m2
        # 300 Kc/m2 = perfect (100), 550+ = 0
        score = max(0.0, min(100.0, (550 - price_per_m2) / 2.5))
        total += score * w_price / 100

    # Disposition component
    w_disp = scoring_cfg.get("disposition_weight", 30)
    preferred = scoring_cfg.get("preferred_dispositions", [])
    if w_disp and listing.disposition:
        disp_lower = listing.disposition.lower()
        preferred_lower = [d.lower() for d in preferred]
        if disp_lower in preferred_lower:
            idx = preferred_lower.index(disp_lower)
            score = max(20.0, 100.0 - idx * 20)
        else:
            score = 10.0
        total += score * w_disp / 100

    # Size component
    w_size = scoring_cfg.get("size_weight", 15)
    ideal = scoring_cfg.get("ideal_size_m2", 55)
    if w_size and listing.size_m2 and ideal > 0:
        score = min(100.0, (listing.size_m2 / ideal) * 100)
        total += score * w_size / 100

    # Neighborhood component
    w_hood = scoring_cfg.get("neighborhood_weight", 15)
    preferred_hoods = scoring_cfg.get("preferred_neighborhoods", [])
    if w_hood and listing.location and preferred_hoods:
        loc_lower = listing.location.lower()
        score = 20.0  # Default for no match
        for i, hood in enumerate(preferred_hoods):
            if hood.lower() in loc_lower:
                score = max(20.0, 100.0 - i * 20)
                break
        total += score * w_hood / 100

    return round(total)
