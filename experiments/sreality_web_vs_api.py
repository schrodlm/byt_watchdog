#!/usr/bin/env python3
"""Compare what a browser user sees vs what the API returns.

The Sreality website is a SPA that calls the same API.
But maybe the frontend makes multiple calls or uses different params.
Let's also check if cookies/session affect which shard you hit.
"""

import requests
import time
import json
from collections import Counter

API_URL = "https://www.sreality.cz/api/cs/v2/estates"

# Same search: Praha 7, rent, 17k-25k
PARAMS = {
    "category_main_cb": 1,
    "category_type_cb": 2,
    "locality_district_id": 5007,
    "per_page": 500,
    "page": 1,
    "czk_price_summary_order2": "17000|25000",
}


def test_session_stickiness():
    """Does using a session (cookies) pin you to one backend?"""
    print("=== Test 1: Session stickiness ===")
    print("Does keeping a session (cookies) pin you to one shard?\n")

    # Without session - random backend each time
    no_session_sizes = []
    for i in range(10):
        resp = requests.get(API_URL, params=PARAMS, timeout=15)
        data = resp.json()
        no_session_sizes.append(data.get("result_size", 0))
        time.sleep(0.3)
    print(f"  No session (10 requests): result_sizes = {no_session_sizes}")
    print(f"  Unique sizes: {set(no_session_sizes)}")

    # With persistent session - should we get same backend?
    session = requests.Session()
    session_sizes = []
    for i in range(10):
        resp = session.get(API_URL, params=PARAMS, timeout=15)
        data = resp.json()
        session_sizes.append(data.get("result_size", 0))
        time.sleep(0.3)
    print(f"  With session (10 requests): result_sizes = {session_sizes}")
    print(f"  Unique sizes: {set(session_sizes)}")
    print(f"  Cookies: {dict(session.cookies)}")

    if len(set(session_sizes)) == 1:
        print("  >>> Session IS sticky - cookies pin you to one backend")
    else:
        print("  >>> Session is NOT sticky - you hit random backends even with cookies")


def test_pagination_consistency():
    """When a user pages through results, do they get consistent data?"""
    print("\n=== Test 2: Pagination consistency ===")
    print("If a user browses page 1, then page 2 - is it the same shard?\n")

    # Default per_page on the website is 20
    all_ids_paged = set()
    for page in range(1, 6):  # 5 pages of 20
        resp = requests.get(API_URL, params={**PARAMS, "per_page": 20, "page": page}, timeout=15)
        data = resp.json()
        estates = data.get("_embedded", {}).get("estates", [])
        ids = {e["hash_id"] for e in estates}
        new = ids - all_ids_paged
        overlap = ids & all_ids_paged
        all_ids_paged |= ids
        print(f"  Page {page}: {len(estates)} results, {len(new)} new, {len(overlap)} duplicates from prev pages")
        time.sleep(0.5)

    print(f"  Total unique across 5 pages: {len(all_ids_paged)}")

    # Compare: single request with per_page=500
    resp = requests.get(API_URL, params=PARAMS, timeout=15)
    data = resp.json()
    single_ids = {e["hash_id"] for e in data["_embedded"]["estates"]}
    print(f"  Single request (per_page=500): {len(single_ids)}")
    print(f"  Paged-only (not in single): {len(all_ids_paged - single_ids)}")
    print(f"  Single-only (not in paged): {len(single_ids - all_ids_paged)}")


def test_default_website_params():
    """What params does the actual website use? Check per_page, sorting, etc."""
    print("\n=== Test 3: Website default parameters ===")

    # The website uses per_page=20 by default and tms= timestamp
    # Let's check if adding tms changes the shard
    import hashlib

    def fp(ids):
        return hashlib.md5(str(sorted(ids)).encode()).hexdigest()[:8]

    print("  Testing with tms= parameter (cache buster):\n")
    fps = []
    for i in range(10):
        tms = int(time.time() * 1000)
        resp = requests.get(API_URL, params={**PARAMS, "tms": tms}, timeout=15)
        data = resp.json()
        ids = frozenset(e["hash_id"] for e in data["_embedded"]["estates"])
        f = fp(ids)
        fps.append(f)
        time.sleep(0.3)

    print(f"  Fingerprints with tms: {Counter(fps)}")
    print(f"  Still hitting multiple backends: {len(set(fps)) > 1}")


def test_user_agent_effect():
    """Does User-Agent affect shard selection?"""
    print("\n=== Test 4: User-Agent effect ===")

    import hashlib

    def fp(ids):
        return hashlib.md5(str(sorted(ids)).encode()).hexdigest()[:8]

    agents = [
        "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15",
        "python-requests/2.31.0",  # Default
    ]

    for ua in agents:
        fps = []
        for _ in range(5):
            resp = requests.get(API_URL, params=PARAMS, headers={"User-Agent": ua}, timeout=15)
            ids = frozenset(e["hash_id"] for e in resp.json()["_embedded"]["estates"])
            fps.append(fp(ids))
            time.sleep(0.2)
        print(f"  {ua[:40]:40s} -> backends: {Counter(fps)}")


if __name__ == "__main__":
    test_session_stickiness()
    test_pagination_consistency()
    test_default_website_params()
    test_user_agent_effect()
