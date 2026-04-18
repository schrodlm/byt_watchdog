#!/usr/bin/env python3
"""Byt Watchdog - Flat rental monitor for Praha 7."""

import logging
import os
import sys

import yaml

import db
from notifier import send_email
from scrapers import ALL_SCRAPERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("byt_watchdog")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        log.error("config.yaml not found. Copy config.example.yaml and fill in your settings.")
        sys.exit(1)
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def run():
    config = load_config()
    scraper_configs = config.get("scrapers", {})

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
            log.info("  %s: found %d listings", name, len(listings))
            all_listings.extend(listings)
        except Exception:
            log.exception("  %s: scraper failed", name)

    if not all_listings:
        log.info("No listings found across all scrapers")
        return

    # Deduplicate against seen DB
    new_listings = [l for l in all_listings if l.id not in db._load()]
    log.info("Total: %d listings, %d new", len(all_listings), len(new_listings))

    if not new_listings:
        log.info("No new listings to report")
        return

    # Mark as seen
    db.mark_seen([l.id for l in new_listings])

    # Send email
    try:
        send_email(new_listings, config)
        log.info("Email sent with %d new listings", len(new_listings))
    except Exception:
        log.exception("Failed to send email")
        # Still keep them marked as seen to avoid spam on retry


if __name__ == "__main__":
    run()
