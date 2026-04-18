#!/usr/bin/env python3
"""Probe Sreality API load balancer behavior.

Sends rapid requests and fingerprints which backend serves each one
by looking at the exact set of listing IDs returned. This reveals:
- How many distinct backends exist
- How often we hit each one
- How different their data is
- Whether sticky sessions or round-robin is used
"""

import hashlib
import json
import time
import sys
from collections import Counter, defaultdict
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

NUM_REQUESTS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
DELAY = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5


def fingerprint(ids: frozenset) -> str:
    """Create a short hash to identify a unique backend state."""
    return hashlib.md5(str(sorted(ids)).encode()).hexdigest()[:8]


def main():
    print(f"=== Sreality LB Probe ===")
    print(f"Sending {NUM_REQUESTS} requests with {DELAY}s delay\n")

    # Track each response
    responses = []  # (timestamp, result_size, ids_frozenset, fingerprint)
    fp_to_ids = {}  # fingerprint -> frozenset of IDs

    for i in range(NUM_REQUESTS):
        t0 = time.time()
        resp = requests.get(API_URL, params=PARAMS, timeout=30)
        elapsed = time.time() - t0
        data = resp.json()

        result_size = data.get("result_size", 0)
        estates = data.get("_embedded", {}).get("estates", [])
        ids = frozenset(e.get("hash_id") for e in estates)
        fp = fingerprint(ids)

        if fp not in fp_to_ids:
            fp_to_ids[fp] = ids

        responses.append((datetime.now().isoformat(), result_size, ids, fp, elapsed))
        sys.stdout.write(f"\r  Request {i+1}/{NUM_REQUESTS}: size={result_size}, returned={len(ids)}, backend={fp}, {elapsed:.0f}ms")
        sys.stdout.flush()
        time.sleep(DELAY)

    print("\n")

    # Analysis
    fps = [r[3] for r in responses]
    fp_counts = Counter(fps)
    unique_backends = len(fp_counts)

    print(f"--- Backend Distribution ---")
    print(f"Unique backend states: {unique_backends}")
    for fp, count in fp_counts.most_common():
        ids = fp_to_ids[fp]
        print(f"  {fp}: hit {count}x ({count/NUM_REQUESTS*100:.0f}%), {len(ids)} listings")

    # Compare backends pairwise
    print(f"\n--- Backend Differences ---")
    fps_list = list(fp_to_ids.keys())
    for i in range(len(fps_list)):
        for j in range(i + 1, len(fps_list)):
            a, b = fp_to_ids[fps_list[i]], fp_to_ids[fps_list[j]]
            common = a & b
            only_a = a - b
            only_b = b - a
            print(f"  {fps_list[i]} vs {fps_list[j]}: common={len(common)}, only_first={len(only_a)}, only_second={len(only_b)}")

    # All IDs union
    all_ids = set()
    for ids in fp_to_ids.values():
        all_ids |= ids
    common_all = fp_to_ids[fps_list[0]]
    for ids in fp_to_ids.values():
        common_all = common_all & ids
    print(f"\n--- Coverage ---")
    print(f"Total unique listings across all backends: {len(all_ids)}")
    print(f"Common to ALL backends: {len(common_all)}")
    print(f"Exclusive to only some backends: {len(all_ids - common_all)}")

    # Check for temporal patterns (do we alternate?)
    print(f"\n--- Temporal Pattern ---")
    seq = "".join(fp[:2] for fp in fps)
    print(f"  Backend sequence: {seq}")

    # Check if response times differ by backend (different server = different latency?)
    print(f"\n--- Latency by Backend ---")
    fp_latencies = defaultdict(list)
    for _, _, _, fp, elapsed in responses:
        fp_latencies[fp].append(elapsed)
    for fp, lats in sorted(fp_latencies.items()):
        avg = sum(lats) / len(lats)
        print(f"  {fp}: avg={avg*1000:.0f}ms, min={min(lats)*1000:.0f}ms, max={max(lats)*1000:.0f}ms")

    # Check response headers for server hints
    print(f"\n--- Response Headers (last request) ---")
    for header in ["server", "x-served-by", "x-backend", "x-cache", "via", "x-request-id", "cf-ray"]:
        val = resp.headers.get(header)
        if val:
            print(f"  {header}: {val}")

    # Save raw data
    outfile = f"experiments/sreality_lb_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(outfile, "w") as f:
        json.dump({
            "params": PARAMS,
            "num_requests": NUM_REQUESTS,
            "delay_s": DELAY,
            "backends": {fp: {"count": fp_counts[fp], "num_ids": len(ids), "ids": sorted(ids)} for fp, ids in fp_to_ids.items()},
            "sequence": fps,
            "responses": [{"time": r[0], "result_size": r[1], "fingerprint": r[3], "latency_ms": round(r[4]*1000)} for r in responses],
        }, f, indent=2)
    print(f"\nRaw data saved to {outfile}")


if __name__ == "__main__":
    main()
