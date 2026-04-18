import fcntl
import json
import logging
import os
import tempfile
from datetime import datetime, timezone, timedelta

log = logging.getLogger("rentczecher")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _db_path(profile_id: str) -> str:
    return os.path.join(DATA_DIR, f"seen-{profile_id}.json")


def _lock_path(profile_id: str) -> str:
    return os.path.join(DATA_DIR, f"seen-{profile_id}.json.lock")


def _lock_file(profile_id: str):
    os.makedirs(DATA_DIR, exist_ok=True)
    lock_fd = open(_lock_path(profile_id), "w")
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    return lock_fd


def _unlock_file(lock_fd):
    fcntl.flock(lock_fd, fcntl.LOCK_UN)
    lock_fd.close()


def _load(profile_id: str) -> dict:
    path = _db_path(profile_id)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                log.warning("seen-%s.json has unexpected format, resetting", profile_id)
                return {}
            return data
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("seen-%s.json is corrupt (%s), starting fresh", profile_id, e)
        return {}


def _save(profile_id: str, data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, _db_path(profile_id))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_seen(profile_id: str) -> dict:
    return _load(profile_id)


def mark_seen(profile_id: str, listings: list) -> None:
    lock_fd = _lock_file(profile_id)
    try:
        seen = _load(profile_id)
        now = datetime.now(timezone.utc).isoformat()
        for item in listings:
            if isinstance(item, str):
                lid = item
                if lid not in seen:
                    seen[lid] = {"first_seen": now}
            else:
                lid = item.id
                entry = seen.get(lid, {})
                if isinstance(entry, str):
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
                if item.lat is not None:
                    entry["lat"] = item.lat
                    entry["lon"] = item.lon
                if item.charges is not None:
                    entry["charges"] = item.charges
                if item.land_m2 is not None:
                    entry["land_m2"] = item.land_m2
                seen[lid] = entry
        _save(profile_id, seen)
    finally:
        _unlock_file(lock_fd)


def update_prices(profile_id: str, listings: list) -> list:
    seen = _load(profile_id)
    drops = []
    for listing in listings:
        entry = seen.get(listing.id)
        if entry and isinstance(entry, dict):
            old_price = entry.get("price")
            if old_price and listing.price and old_price > listing.price:
                drops.append((listing, old_price))
    return drops


def update_miss_counts(profile_id: str, current_ids: set[str]) -> None:
    """Increment miss_count for listings not in current scrape, reset for found ones."""
    lock_fd = _lock_file(profile_id)
    try:
        seen = _load(profile_id)
        changed = False
        for lid, entry in seen.items():
            if not isinstance(entry, dict):
                continue
            if lid in current_ids:
                if entry.get("miss_count", 0) > 0:
                    entry["miss_count"] = 0
                    changed = True
            else:
                entry["miss_count"] = entry.get("miss_count", 0) + 1
                changed = True
        if changed:
            _save(profile_id, seen)
    finally:
        _unlock_file(lock_fd)


def get_disappeared(profile_id: str, current_ids: set[str],
                    max_age_days: int = 7, min_misses: int = 3) -> list[dict]:
    """Find listings that have been missing for min_misses consecutive runs.

    This filters out API noise (e.g. Sreality returning inconsistent results).
    A listing must be absent from min_misses consecutive scrapes before being
    reported as disappeared.
    """
    seen = _load(profile_id)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    disappeared = []
    for lid, entry in seen.items():
        if not isinstance(entry, dict):
            continue
        if lid in current_ids:
            continue
        miss_count = entry.get("miss_count", 0)
        if miss_count < min_misses:
            continue
        first_seen = entry.get("first_seen", "")
        if first_seen >= cutoff and entry.get("title"):
            disappeared.append({"id": lid, **entry})
    return disappeared


def prune(profile_id: str, max_age_days: int = 90) -> int:
    lock_fd = _lock_file(profile_id)
    try:
        seen = _load(profile_id)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        to_remove = []
        for lid, entry in seen.items():
            if isinstance(entry, dict):
                last = entry.get("last_seen", entry.get("first_seen", ""))
            else:
                last = entry
            if last < cutoff:
                to_remove.append(lid)
        for lid in to_remove:
            del seen[lid]
        if to_remove:
            _save(profile_id, seen)
            log.info("Pruned %d old entries from seen-%s.json", len(to_remove), profile_id)
        return len(to_remove)
    finally:
        _unlock_file(lock_fd)
