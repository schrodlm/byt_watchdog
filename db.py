import fcntl
import json
import logging
import os
import tempfile
from datetime import datetime, timezone, timedelta

log = logging.getLogger("byt_watchdog")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "seen.json")
LOCK_PATH = DB_PATH + ".lock"


def _lock_file():
    """Acquire an exclusive file lock."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    lock_fd = open(LOCK_PATH, "w")
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    return lock_fd


def _unlock_file(lock_fd):
    """Release the file lock."""
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
    lock_fd.close()


def _load() -> dict:
    if not os.path.exists(DB_PATH):
        return {}
    try:
        with open(DB_PATH, "r") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                log.warning("seen.json has unexpected format, resetting")
                return {}
            return data
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("seen.json is corrupt (%s), starting fresh", e)
        return {}


def _save(data: dict) -> None:
    """Atomic write: write to temp file, then os.replace()."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(DB_PATH), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, DB_PATH)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def is_seen(listing_id: str) -> bool:
    return listing_id in _load()


def filter_new(listing_ids: list[str]) -> list[str]:
    seen = _load()
    return [lid for lid in listing_ids if lid not in seen]


def get_seen() -> dict:
    """Return the full seen database."""
    return _load()


def mark_seen(listings: list) -> None:
    """Mark listings as seen. Accepts list of Listing objects or list of ID strings."""
    lock_fd = _lock_file()
    try:
        seen = _load()
        now = datetime.now(timezone.utc).isoformat()
        for item in listings:
            # Support both Listing objects and plain ID strings
            if isinstance(item, str):
                lid = item
                if lid not in seen:
                    seen[lid] = {"first_seen": now}
            else:
                lid = item.id
                entry = seen.get(lid, {})
                if isinstance(entry, str):
                    # Migrate old format (just a timestamp string)
                    entry = {"first_seen": entry}

                if lid not in seen:
                    entry["first_seen"] = now

                entry["last_seen"] = now
                entry["price"] = item.price
                entry["title"] = item.title
                entry["location"] = item.location
                entry["url"] = item.url
                entry["source"] = item.source
                entry["size_m2"] = item.size_m2
                entry["disposition"] = item.disposition
                if hasattr(item, "lat"):
                    entry["lat"] = item.lat
                    entry["lon"] = item.lon
                if hasattr(item, "charges"):
                    entry["charges"] = item.charges

                seen[lid] = entry
        _save(seen)
    finally:
        _unlock_file(lock_fd)


def update_prices(listings: list) -> list:
    """Check for price drops. Returns list of (listing, old_price) tuples for drops."""
    seen = _load()
    drops = []
    for listing in listings:
        entry = seen.get(listing.id)
        if entry and isinstance(entry, dict):
            old_price = entry.get("price")
            if old_price and old_price > listing.price:
                drops.append((listing, old_price))
    return drops


def get_disappeared(current_ids: set[str], max_age_days: int = 7) -> list[dict]:
    """Find listings in DB that are no longer in any scrape results.

    Only considers listings seen in the last max_age_days to avoid
    reporting very old listings.
    """
    seen = _load()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    disappeared = []
    for lid, entry in seen.items():
        if not isinstance(entry, dict):
            continue
        if lid in current_ids:
            continue
        first_seen = entry.get("first_seen", "")
        if first_seen >= cutoff and entry.get("title"):
            disappeared.append({"id": lid, **entry})
    return disappeared


def prune(max_age_days: int = 90) -> int:
    """Remove entries older than max_age_days. Returns count removed."""
    lock_fd = _lock_file()
    try:
        seen = _load()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        to_remove = []
        for lid, entry in seen.items():
            if isinstance(entry, dict):
                last = entry.get("last_seen", entry.get("first_seen", ""))
            else:
                last = entry  # Old format: just a timestamp string
            if last < cutoff:
                to_remove.append(lid)
        for lid in to_remove:
            del seen[lid]
        if to_remove:
            _save(seen)
            log.info("Pruned %d old entries from seen.json", len(to_remove))
        return len(to_remove)
    finally:
        _unlock_file(lock_fd)
