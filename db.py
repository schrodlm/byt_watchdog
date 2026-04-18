import json
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "seen.json")


def _load() -> dict:
    if not os.path.exists(DB_PATH):
        return {}
    with open(DB_PATH, "r") as f:
        return json.load(f)


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with open(DB_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def is_seen(listing_id: str) -> bool:
    return listing_id in _load()


def filter_new(listing_ids: list[str]) -> list[str]:
    seen = _load()
    return [lid for lid in listing_ids if lid not in seen]


def mark_seen(listing_ids: list[str]) -> None:
    seen = _load()
    now = datetime.now(timezone.utc).isoformat()
    for lid in listing_ids:
        if lid not in seen:
            seen[lid] = now
    _save(seen)
