#!/usr/bin/env python3
"""Track how Sreality backend states change over time.

Runs a probe every N minutes and records whether backend fingerprints change.
This reveals the index rebuild frequency.

Usage: python3 experiments/sreality_lb_drift.py [interval_seconds] [duration_minutes]
"""

import hashlib
import json
import sys
import time
from collections import defaultdict
from datetime import datetime

import requests

API_URL = "https://www.sreality.cz/api/cs/v2/estates"
PARAMS = {
    "category_main_cb": 1,
    "category_type_cb": 2,
    "locality_district_id": 5007,
    "per_page": 500,
    "page": 1,
    "czk_price_summary_order2": "17000|25000",
}

INTERVAL = int(sys.argv[1]) if len(sys.argv) > 1 else 60  # seconds between probes
DURATION = int(sys.argv[2]) if len(sys.argv) > 2 else 30   # minutes to run


def fingerprint(ids: frozenset) -> str:
    return hashlib.md5(str(sorted(ids)).encode()).hexdigest()[:8]


def probe_once(num_requests: int = 10) -> dict:
    """Send several requests and identify unique backends."""
    backends = {}  # fp -> ids
    hit_counts = defaultdict(int)

    for _ in range(num_requests):
        try:
            resp = requests.get(API_URL, params=PARAMS, timeout=15)
            data = resp.json()
            estates = data.get("_embedded", {}).get("estates", [])
            ids = frozenset(e.get("hash_id") for e in estates)
            fp = fingerprint(ids)
            backends[fp] = ids
            hit_counts[fp] += 1
        except Exception as e:
            print(f"    Error: {e}")
        time.sleep(0.3)

    return {"backends": backends, "hits": dict(hit_counts)}


def main():
    print(f"=== Sreality LB Drift Monitor ===")
    print(f"Probing every {INTERVAL}s for {DURATION} minutes")
    print(f"Each probe: 10 requests to identify all backends\n")

    history = []  # (timestamp, {fp: count}, {fp: ids})
    all_fps_seen = set()
    start = time.time()
    end = start + DURATION * 60

    probe_num = 0
    while time.time() < end:
        probe_num += 1
        now = datetime.now()
        result = probe_once(10)

        fps = set(result["backends"].keys())
        new_fps = fps - all_fps_seen
        all_fps_seen |= fps

        # Total unique listings this probe
        all_ids = set()
        for ids in result["backends"].values():
            all_ids |= ids

        status = ""
        if new_fps:
            status = f" *** NEW BACKEND(S): {new_fps} ***"

        print(f"[{now.strftime('%H:%M:%S')}] Probe #{probe_num}: "
              f"{len(result['backends'])} backends, "
              f"hits={dict(result['hits'])}, "
              f"total_unique={len(all_ids)}{status}")

        history.append({
            "time": now.isoformat(),
            "backends": {fp: {"count": result["hits"][fp], "num_ids": len(ids)}
                        for fp, ids in result["backends"].items()},
            "total_unique": len(all_ids),
            "new_backends": list(new_fps),
        })

        # Sleep until next probe
        elapsed = time.time() - (start + (probe_num - 1) * INTERVAL)
        sleep_time = max(0, INTERVAL - elapsed)
        if time.time() + sleep_time >= end:
            break
        time.sleep(sleep_time)

    # Summary
    print(f"\n--- Summary ---")
    print(f"Total probes: {probe_num}")
    print(f"Total unique backend states seen: {len(all_fps_seen)}")
    print(f"Backend fingerprints: {all_fps_seen}")

    # Check which probes saw new backends
    changes = [h for h in history if h["new_backends"]]
    if changes:
        print(f"\nBackend changes detected at:")
        for h in changes:
            print(f"  {h['time']}: new backends {h['new_backends']}")
    else:
        print(f"\nNo backend changes during monitoring period (indexes stable)")

    outfile = f"experiments/sreality_lb_drift_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(outfile, "w") as f:
        json.dump(history, f, indent=2)
    print(f"\nData saved to {outfile}")


if __name__ == "__main__":
    main()
