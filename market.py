"""Market intelligence - price analysis and positioning relative to historical data."""

import logging
from scrapers.base import Listing

log = logging.getLogger("byt_watchdog")


def compute_price_position(listing: Listing, all_seen: dict) -> dict | None:
    """Compute how a listing's price compares to the market.

    Returns dict with percentile and comparable stats, or None if insufficient data.
    """
    if not listing.price or not listing.disposition:
        return None

    # Find comparable listings: same disposition, with price and size
    comparables = []
    for lid, entry in all_seen.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("disposition") != listing.disposition:
            continue
        price = entry.get("price", 0)
        if price > 0:
            comparables.append(price)

    if len(comparables) < 5:
        return None  # Not enough data for meaningful comparison

    comparables.sort()
    n = len(comparables)

    # Percentile: what fraction of comparables is this listing cheaper than?
    cheaper_count = sum(1 for p in comparables if p > listing.price)
    percentile = round(cheaper_count / n * 100)

    median = comparables[n // 2]
    avg = round(sum(comparables) / n)

    return {
        "percentile": percentile,  # "cheaper than X% of similar listings"
        "median": median,
        "avg": avg,
        "sample_size": n,
        "diff_from_median": listing.price - median,
        "diff_pct": round((listing.price - median) / median * 100) if median else 0,
    }


def compute_avg_time_on_market(all_seen: dict) -> float | None:
    """Compute average days a listing stays on the market before disappearing.

    Uses listings that have both first_seen and miss_count >= 3 (confirmed gone).
    """
    from datetime import datetime, timezone

    durations = []
    for lid, entry in all_seen.items():
        if not isinstance(entry, dict):
            continue
        miss_count = entry.get("miss_count", 0)
        if miss_count < 3:
            continue
        first_seen = entry.get("first_seen", "")
        last_seen = entry.get("last_seen", "")
        if not first_seen or not last_seen:
            continue
        try:
            fs = datetime.fromisoformat(first_seen)
            ls = datetime.fromisoformat(last_seen)
            days = (ls - fs).total_seconds() / 86400
            if days >= 0:
                durations.append(days)
        except (ValueError, TypeError):
            continue

    if len(durations) < 3:
        return None
    return round(sum(durations) / len(durations), 1)


def enrich_market_data(listings: list[Listing], all_seen: dict) -> None:
    """Add market position data to listings (modifies in place via score adjustment)."""
    for listing in listings:
        position = compute_price_position(listing, all_seen)
        if position and position["percentile"] >= 75:
            # This listing is cheaper than 75%+ of similar listings - boost urgency
            if listing.urgency != "hot" and listing.score >= 50:
                listing.urgency = "hot"
