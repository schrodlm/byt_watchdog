#!/usr/bin/env python3
"""Byt Watchdog - Flat rental monitor for Praha 7."""

import argparse
import logging
import os
import sys

import yaml

import db
from dedup import cross_source_dedup
from metro import enrich_metro
from notifier import send_email
from scoring import compute_score
from scrapers import ALL_SCRAPERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("byt_watchdog")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
PID_PATH = os.path.join(BASE_DIR, "data", "watchdog.pid")


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        log.error("config.yaml not found. Copy config.example.yaml and fill in your settings.")
        sys.exit(1)
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def _acquire_pidlock() -> bool:
    """Prevent concurrent runs. Returns True if lock acquired."""
    os.makedirs(os.path.dirname(PID_PATH), exist_ok=True)
    if os.path.exists(PID_PATH):
        try:
            with open(PID_PATH, "r") as f:
                old_pid = int(f.read().strip())
            # Check if process is still running
            os.kill(old_pid, 0)
            return False  # Process still alive
        except (ValueError, ProcessLookupError, PermissionError):
            pass  # Stale pidfile, safe to continue
    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))
    return True


def _release_pidlock():
    try:
        os.unlink(PID_PATH)
    except OSError:
        pass


def _apply_filters(listings: list, config: dict) -> list:
    """Apply disposition and size filters from config."""
    search = config.get("search", {})
    dispositions = search.get("dispositions", [])
    min_size = search.get("min_size_m2", 0)

    result = listings
    if dispositions:
        disp_lower = {d.lower() for d in dispositions}
        result = [
            l for l in result
            if l.disposition is None or l.disposition.lower() in disp_lower
        ]

    if min_size > 0:
        result = [
            l for l in result
            if l.size_m2 is None or l.size_m2 >= min_size
        ]

    return result


def run(dry_run: bool = False):
    config = load_config()
    scraper_configs = config.get("scrapers", {})

    if not _acquire_pidlock():
        log.warning("Another instance is already running, exiting")
        return
    try:
        _run_inner(config, scraper_configs, dry_run)
    finally:
        _release_pidlock()


def _run_inner(config: dict, scraper_configs: dict, dry_run: bool):
    if dry_run:
        log.info("DRY RUN - no emails will be sent, seen.json will not be updated")

    # Scrape all sources
    all_listings = []
    for name, scraper_cls in ALL_SCRAPERS.items():
        scraper_cfg = scraper_configs.get(name, {})
        if not scraper_cfg.get("enabled", True):
            log.info("Scraper %s is disabled, skipping", name)
            continue

        log.info("Running scraper: %s", name)
        try:
            scraper = scraper_cls(config)
            listings = scraper.scrape()
            if len(listings) == 0:
                log.warning("  %s: returned 0 results - site structure may have changed!", name)
            else:
                log.info("  %s: found %d listings", name, len(listings))
            all_listings.extend(listings)
        except Exception:
            log.exception("  %s: scraper failed", name)

    if not all_listings:
        log.info("No listings found across all scrapers")
        return

    # Apply filters (disposition, min_size)
    filtered = _apply_filters(all_listings, config)
    if len(filtered) < len(all_listings):
        log.info("Filtered: %d -> %d listings", len(all_listings), len(filtered))
    all_listings = filtered

    # Enrich with metro distance
    for listing in all_listings:
        enrich_metro(listing)

    # Cross-source dedup
    pre_dedup = len(all_listings)
    all_listings = cross_source_dedup(all_listings)
    if pre_dedup > len(all_listings):
        log.info("Cross-source dedup: %d -> %d listings", pre_dedup, len(all_listings))

    # Compute scores
    for listing in all_listings:
        listing.score = compute_score(listing, config)

    # Check for price drops BEFORE updating DB
    price_drops = db.update_prices(all_listings)
    for listing, old_price in price_drops:
        listing.price_drop_from = old_price
        log.info("  PRICE DROP: %s | %d -> %d Kc", listing.title[:50], old_price, listing.price)

    # Find new listings BEFORE updating DB
    seen = db.get_seen()
    new_listings = [l for l in all_listings if l.id not in seen]

    # Price drops on existing (not new) listings
    price_drop_listings = [l for l, _ in price_drops if l.id not in {n.id for n in new_listings}]

    # Detect disappeared listings
    current_ids = {l.id for l in all_listings}
    disappeared = db.get_disappeared(current_ids)
    if disappeared:
        log.info("Disappeared: %d listings no longer found", len(disappeared))

    notable = new_listings + price_drop_listings
    log.info("Total: %d listings, %d new, %d price drops, %d disappeared",
             len(all_listings), len(new_listings), len(price_drops), len(disappeared))

    if not notable and not disappeared:
        # Still update DB with last_seen timestamps
        if not dry_run:
            db.mark_seen(all_listings)
        log.info("No new listings or changes to report")
        return

    if dry_run:
        for l in new_listings:
            log.info("  [NEW] score=%d | %s | %d Kc | %s | %s",
                     l.score, l.disposition or "?", l.price, l.location, l.url)
        for l in price_drop_listings:
            log.info("  [DROP] %d -> %d Kc | %s | %s",
                     l.price_drop_from, l.price, l.title[:50], l.url)
        for d in disappeared[:5]:
            log.info("  [GONE] %s | %d Kc | %s", d.get("title", "?")[:50], d.get("price", 0), d.get("url", ""))
        log.info("DRY RUN complete")
        return

    # Send email FIRST (before marking seen - if email fails, retry next run)
    try:
        send_email(notable, config, disappeared=disappeared)
        log.info("Email sent with %d new + %d price drops", len(new_listings), len(price_drop_listings))
    except Exception:
        log.exception("Failed to send email - listings will be retried next run")
        return  # Don't mark as seen so they get retried

    # Only mark as seen AFTER successful email
    db.mark_seen(all_listings)

    # Prune old entries periodically
    db.prune(max_age_days=90)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Byt Watchdog - Flat rental monitor")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scrape and show results without sending email or updating seen.json")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
