#!/usr/bin/env python3
"""RentCzecher - Multi-profile real estate monitor."""

import argparse
import logging
import os
import sys

import yaml

import db
from dedup import cross_source_dedup
from market import enrich_market_data
from metro import enrich_tram
from notifier import send_email
from scoring import compute_score
from scrapers import ALL_SCRAPERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("rentczecher")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
PID_PATH = os.path.join(BASE_DIR, "data", "watchdog.pid")


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        log.error("config.yaml not found. Copy config.example.yaml and fill in your settings.")
        sys.exit(1)
    with open(CONFIG_PATH, "r") as f:
        config = yaml.safe_load(f)
    errors = validate_config(config)
    if errors:
        for err in errors:
            log.error("Config error: %s", err)
        sys.exit(1)
    return config


def validate_config(config: dict) -> list[str]:
    """Validate config structure. Returns list of error messages."""
    errors = []
    email = config.get("email", {})
    for key in ("smtp_host", "smtp_port", "smtp_user", "smtp_password", "from"):
        if key not in email:
            errors.append(f"email.{key} is missing")
    profiles = config.get("profiles", {})
    if not profiles:
        errors.append("No profiles defined")
    for pid, profile in profiles.items():
        if not profile.get("to"):
            errors.append(f"profile '{pid}' has no 'to' recipients")
        if not profile.get("search"):
            errors.append(f"profile '{pid}' has no 'search' section")
        if not profile.get("scrapers"):
            errors.append(f"profile '{pid}' has no 'scrapers' section")
    return errors


def _acquire_pidlock() -> bool:
    """Acquire PID lock using atomic file creation."""
    import fcntl
    os.makedirs(os.path.dirname(PID_PATH), exist_ok=True)
    try:
        fd = os.open(PID_PATH, os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False  # Another process holds the lock
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        # Keep fd open (lock is held until process exits or fd is closed)
        # Store fd so _release_pidlock can close it
        _acquire_pidlock._fd = fd
        return True
    except OSError:
        return False


def _release_pidlock():
    try:
        fd = getattr(_acquire_pidlock, '_fd', None)
        if fd is not None:
            os.close(fd)
            _acquire_pidlock._fd = None
        os.unlink(PID_PATH)
    except OSError:
        pass


def _apply_filters(listings: list, profile: dict) -> list:
    search = profile.get("search", {})
    dispositions = search.get("dispositions", [])
    min_size = search.get("min_size_m2", 0)
    min_land = search.get("min_land_m2", 0)

    result = listings
    if dispositions:
        disp_lower = {d.lower() for d in dispositions}
        result = [
            l for l in result
            if l.disposition is None or l.disposition.lower() in disp_lower
        ]

    if min_size > 0:
        result = [l for l in result if l.size_m2 is None or l.size_m2 >= min_size]

    if min_land > 0:
        result = [l for l in result if l.land_m2 is None or l.land_m2 >= min_land]

    return result


def run_profile(profile_id: str, profile: dict, email_cfg: dict, dry_run: bool = False):
    """Run a single profile: scrape, filter, score, notify."""
    profile_name = profile.get("name", profile_id)
    log.info("=== Profile: %s ===", profile_name)

    # Scrape all sources for this profile
    all_listings = []
    scraper_configs = profile.get("scrapers", {})
    enabled_count = sum(1 for n in ALL_SCRAPERS if scraper_configs.get(n, {}).get("enabled", False))
    if enabled_count == 0:
        log.warning("Profile %s has no enabled scrapers", profile_id)
        return

    for name, scraper_cls in ALL_SCRAPERS.items():
        scraper_cfg = scraper_configs.get(name, {})
        if not scraper_cfg.get("enabled", False):
            continue

        log.info("Running scraper: %s", name)
        try:
            scraper = scraper_cls(profile)
            listings = scraper.scrape()
            if len(listings) == 0:
                log.warning("  %s: returned 0 results - site structure may have changed!", name)
            else:
                log.info("  %s: found %d listings", name, len(listings))
            all_listings.extend(listings)
        except Exception:
            log.exception("  %s: scraper failed", name)

    if not all_listings:
        log.info("No listings found for profile %s", profile_id)
        return

    # Apply filters
    filtered = _apply_filters(all_listings, profile)
    if len(filtered) < len(all_listings):
        log.info("Filtered: %d -> %d listings", len(all_listings), len(filtered))
    all_listings = filtered

    # Enrich with tram distances (only for Prague profiles)
    if profile.get("tram_enrichment", False):
        for listing in all_listings:
            enrich_tram(listing)

    # Cross-source dedup
    pre_dedup = len(all_listings)
    all_listings = cross_source_dedup(all_listings)
    if pre_dedup > len(all_listings):
        log.info("Cross-source dedup: %d -> %d listings", pre_dedup, len(all_listings))

    # Compute scores and urgency
    urgency_cfg = profile.get("urgency", {})
    hot_threshold = urgency_cfg.get("hot_threshold", 75)
    low_threshold = urgency_cfg.get("low_threshold", 30)
    for listing in all_listings:
        listing.score = compute_score(listing, profile)
        if listing.score >= hot_threshold:
            listing.urgency = "hot"
        elif listing.score < low_threshold:
            listing.urgency = "low"

    # Check for price drops (always mark as hot urgency)
    price_drops = db.update_prices(profile_id, all_listings)
    for listing, old_price in price_drops:
        listing.price_drop_from = old_price
        listing.urgency = "hot"
        log.info("  PRICE DROP: %s | %d -> %d Kc", listing.title[:50], old_price, listing.price)

    # Market intelligence: boost urgency for listings below market price
    seen = db.get_seen(profile_id)
    enrich_market_data(all_listings, seen)

    # Find new listings BEFORE updating DB
    new_listings = [l for l in all_listings if l.id not in seen]
    price_drop_listings = [l for l, _ in price_drops if l.id not in {n.id for n in new_listings}]

    # Detect disappeared (requires 3+ consecutive misses to filter API noise)
    current_ids = {l.id for l in all_listings}
    db.update_miss_counts(profile_id, current_ids)
    disappeared = db.get_disappeared(profile_id, current_ids)
    if disappeared:
        log.info("Disappeared: %d listings confirmed gone (3+ misses)", len(disappeared))

    notable = new_listings + price_drop_listings
    log.info("Total: %d listings, %d new, %d price drops, %d disappeared",
             len(all_listings), len(new_listings), len(price_drops), len(disappeared))

    if not notable:
        if not dry_run:
            db.mark_seen(profile_id, all_listings)
        if disappeared:
            log.info("Only disappeared listings (%d) - no email sent", len(disappeared))
        else:
            log.info("No new listings or changes to report")
        return

    if dry_run:
        for l in new_listings:
            extra = f" | land={l.land_m2}m2" if l.land_m2 else ""
            log.info("  [NEW] score=%d | %s | %d Kc | %s%s | %s",
                     l.score, l.disposition or "?", l.price, l.location, extra, l.url)
        for l in price_drop_listings:
            log.info("  [DROP] %d -> %d Kc | %s", l.price_drop_from, l.price, l.title[:50])
        for d in disappeared[:5]:
            log.info("  [GONE] %s | %d Kc", d.get("title", "?")[:50], d.get("price", 0))
        log.info("DRY RUN complete for %s", profile_id)
        return

    # Determine recipients - profile-level "to" overrides global
    recipients = profile.get("to", [])
    if isinstance(recipients, str):
        recipients = [recipients]

    if not recipients:
        log.error("Profile %s has no 'to' recipients configured - skipping email", profile_id)
        db.mark_seen(profile_id, all_listings)
        return

    # Send email FIRST
    try:
        merged_email_cfg = {**email_cfg, "to": recipients}
        send_email(notable, merged_email_cfg, profile=profile, disappeared=disappeared, all_seen=seen)
        log.info("Email sent to %s with %d new + %d price drops",
                 ", ".join(recipients), len(new_listings), len(price_drop_listings))
    except Exception:
        log.exception("Failed to send email for %s - will retry next run", profile_id)
        return

    # Mark as seen AFTER successful email
    db.mark_seen(profile_id, all_listings)
    db.prune(profile_id, max_age_days=90)


def run(dry_run: bool = False, profile_filter: str | None = None):
    config = load_config()

    if not _acquire_pidlock():
        log.warning("Another instance is already running, exiting")
        return
    try:
        email_cfg = config.get("email", {})
        profiles = config.get("profiles", {})

        if not profiles:
            log.error("No profiles defined in config.yaml")
            return

        for profile_id, profile in profiles.items():
            if profile_filter and profile_id != profile_filter:
                continue
            if not profile.get("enabled", True):
                log.info("Profile %s is disabled, skipping", profile_id)
                continue

            if dry_run:
                log.info("DRY RUN - no emails, no DB updates")

            try:
                run_profile(profile_id, profile, email_cfg, dry_run)
            except Exception:
                log.exception("Profile %s failed", profile_id)
    finally:
        _release_pidlock()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RentCzecher - Real estate monitor")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scrape and show results without sending email or updating DB")
    parser.add_argument("--profile", type=str, default=None,
                        help="Run only a specific profile (by ID)")
    args = parser.parse_args()
    run(dry_run=args.dry_run, profile_filter=args.profile)
