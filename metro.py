"""Metro station distance enrichment for Praha 7 area."""

import math
from scrapers.base import Listing

# Praha metro stations near Praha 7 (and adjacent districts)
# Source: Prague public transport data
METRO_STATIONS = [
    # Line C (red)
    ("Nadrazi Holesovice", 50.1094, 14.4400),
    ("Vltavska", 50.1003, 14.4310),
    ("Florenc", 50.0902, 14.4400),
    # Line A (green)
    ("Hradcanska", 50.0946, 14.3941),
    ("Dejvicka", 50.1003, 14.3942),
    ("Malostranska", 50.0905, 14.4045),
    # Line B (yellow)
    ("Krizikova", 50.0926, 14.4527),
    ("Palmovka", 50.1018, 14.4743),
]


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Calculate distance in meters between two GPS points."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return round(2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def enrich_metro(listing: Listing) -> None:
    """Add nearest metro station and distance to a listing (mutates in place)."""
    if listing.lat is None or listing.lon is None:
        return

    best_name = None
    best_dist = float("inf")

    for name, lat, lon in METRO_STATIONS:
        dist = _haversine_m(listing.lat, listing.lon, lat, lon)
        if dist < best_dist:
            best_dist = dist
            best_name = name

    if best_name:
        listing.metro_station = best_name
        listing.metro_distance_m = best_dist
