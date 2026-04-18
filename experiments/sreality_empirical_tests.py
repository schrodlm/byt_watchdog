#!/usr/bin/env python3
"""Empirical tests on Sreality API sharding behavior for research paper.

Six independent experiments:
1. Response header analysis (20 requests, log ALL headers)
2. IP resolution (dig + direct-IP requests)
3. Different searches same behavior (3 locations x 10 requests)
4. Sorting parameter effect (sort=0 vs sort=1)
5. Time-based correlation (100 rapid requests, pattern analysis)
6. ETag/caching analysis

All results are saved as JSON in experiments/.
"""

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

import requests

# ── Shared config ──────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
API_URL = "https://www.sreality.cz/api/cs/v2/estates"
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

# Base search: Praha 7, rent, 17k-25k (same as existing experiments)
BASE_PARAMS = {
    "category_main_cb": 1,
    "category_type_cb": 2,
    "locality_district_id": 5007,
    "per_page": 500,
    "page": 1,
    "czk_price_summary_order2": "17000|25000",
}


def fingerprint(ids):
    """Short hash identifying a unique set of listing IDs."""
    return hashlib.md5(str(sorted(ids)).encode()).hexdigest()[:8]


def extract_ids(resp_json):
    """Extract listing hash_ids from API response."""
    estates = resp_json.get("_embedded", {}).get("estates", [])
    return frozenset(e.get("hash_id") for e in estates)


def save_json(data, name):
    path = os.path.join(SCRIPT_DIR, f"{name}_{TIMESTAMP}.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"  -> Saved to {path}")
    return path


# ══════════════════════════════════════════════════════════════
# TEST 1: Response Header Analysis
# ══════════════════════════════════════════════════════════════
def test_response_headers():
    print("\n" + "=" * 70)
    print("TEST 1: Response Header Analysis (20 requests, ALL headers)")
    print("=" * 70)

    INTERESTING_HEADERS = [
        "x-request-id", "x-served-by", "via", "x-cache", "etag",
        "cf-ray", "x-backend", "x-varnish", "x-amz-cf-id",
        "x-amz-request-id", "server", "x-powered-by", "x-frame-options",
        "content-encoding", "vary", "cache-control", "age",
        "last-modified", "x-cdn", "x-node", "x-instance",
        "strict-transport-security", "x-content-type-options",
        "set-cookie", "alt-svc",
    ]

    results = []
    all_header_keys = Counter()
    header_value_sets = defaultdict(set)  # header_name -> set of unique values

    for i in range(20):
        resp = requests.get(API_URL, params=BASE_PARAMS, timeout=30)
        data = resp.json()
        ids = extract_ids(data)
        fp = fingerprint(ids)
        result_size = data.get("result_size", 0)

        headers_dict = dict(resp.headers)
        for k in headers_dict:
            all_header_keys[k.lower()] += 1
            header_value_sets[k.lower()].add(headers_dict[k])

        results.append({
            "request_num": i + 1,
            "timestamp": datetime.now().isoformat(),
            "status_code": resp.status_code,
            "shard_fingerprint": fp,
            "result_size": result_size,
            "num_listings": len(ids),
            "headers": headers_dict,
        })
        sys.stdout.write(f"\r  Request {i+1}/20 - shard={fp} size={result_size}")
        sys.stdout.flush()
        time.sleep(0.5)

    print()

    # Analyze which headers vary
    print("\n  --- All Response Headers Seen ---")
    for hdr, count in sorted(all_header_keys.items()):
        values = header_value_sets[hdr]
        varies = "VARIES" if len(values) > 1 else "constant"
        sample = list(values)[0][:80] if len(values) == 1 else f"({len(values)} unique values)"
        print(f"    {hdr:40s} present={count:2d}/20  {varies:10s}  {sample}")

    # Check if any varying header correlates with shard fingerprint
    print("\n  --- Headers Correlated with Shard ---")
    varying_headers = [h for h, v in header_value_sets.items() if len(v) > 1]
    shard_fps = [r["shard_fingerprint"] for r in results]

    for hdr in varying_headers:
        hdr_values = [r["headers"].get(hdr, r["headers"].get(hdr.title(), "")) for r in results]
        # Check if header value predicts shard
        hdr_to_shards = defaultdict(set)
        for hv, sf in zip(hdr_values, shard_fps):
            hdr_to_shards[hv].add(sf)
        # If each header value maps to exactly one shard, it's a perfect predictor
        perfect = all(len(s) == 1 for s in hdr_to_shards.values() if s)
        if perfect and len(hdr_to_shards) > 1:
            print(f"    {hdr}: PERFECT CORRELATION with shard!")
            for hv, shards in hdr_to_shards.items():
                print(f"      '{hv[:60]}' -> shard {list(shards)}")
        else:
            print(f"    {hdr}: no clear correlation (values map to multiple shards)")

    data_out = {
        "test": "response_headers",
        "num_requests": 20,
        "all_headers_seen": {h: {"count": c, "unique_values": list(header_value_sets[h])[:10]}
                             for h, c in all_header_keys.items()},
        "varying_headers": varying_headers,
        "requests": results,
    }
    save_json(data_out, "test1_headers")
    return data_out


# ══════════════════════════════════════════════════════════════
# TEST 2: IP Resolution
# ══════════════════════════════════════════════════════════════
def test_ip_resolution():
    print("\n" + "=" * 70)
    print("TEST 2: IP Resolution (dig + direct IP requests)")
    print("=" * 70)

    results = {"dns": {}, "direct_ip_tests": []}

    for domain in ["www.sreality.cz", "api.sreality.cz", "sreality.cz"]:
        print(f"\n  --- dig {domain} ---")
        try:
            dig_out = subprocess.run(
                ["dig", "+short", domain], capture_output=True, text=True, timeout=10
            )
            lines = [l.strip() for l in dig_out.stdout.strip().split("\n") if l.strip()]
            print(f"    Records: {lines}")
            results["dns"][domain] = lines
        except FileNotFoundError:
            # Fallback to Python DNS resolution
            try:
                ips = list(set(info[4][0] for info in socket.getaddrinfo(domain, 443)))
                print(f"    IPs (socket): {ips}")
                results["dns"][domain] = ips
            except Exception as e:
                print(f"    Error: {e}")
                results["dns"][domain] = [str(e)]

        # Also try dig with more detail
        try:
            dig_full = subprocess.run(
                ["dig", domain, "ANY", "+noall", "+answer"],
                capture_output=True, text=True, timeout=10
            )
            if dig_full.stdout.strip():
                print(f"    Full: {dig_full.stdout.strip()}")
                results["dns"][f"{domain}_full"] = dig_full.stdout.strip()
        except (FileNotFoundError, Exception):
            pass

    # Try requesting each IP directly with Host header
    print("\n  --- Direct IP Requests ---")
    www_ips = results["dns"].get("www.sreality.cz", [])
    # Filter only IP-like entries (not CNAMEs)
    ips = [ip for ip in www_ips if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip)]

    if not ips:
        # Try resolving directly
        try:
            ips = list(set(info[4][0] for info in socket.getaddrinfo("www.sreality.cz", 443)))
        except Exception:
            ips = []

    print(f"  IPs to test: {ips}")

    for ip in ips[:5]:  # Limit to 5 IPs
        print(f"\n    Testing IP {ip}:")
        shard_fps = []
        for attempt in range(5):
            try:
                # Request the IP directly with proper Host header
                url = f"https://{ip}/api/cs/v2/estates"
                resp = requests.get(
                    url, params=BASE_PARAMS,
                    headers={"Host": "www.sreality.cz"},
                    timeout=15, verify=False  # Self-signed cert when hitting IP directly
                )
                data = resp.json()
                ids = extract_ids(data)
                fp = fingerprint(ids)
                shard_fps.append(fp)
                print(f"      Attempt {attempt+1}: shard={fp}, size={data.get('result_size', 0)}")
            except Exception as e:
                shard_fps.append(f"ERROR: {str(e)[:80]}")
                print(f"      Attempt {attempt+1}: ERROR - {str(e)[:80]}")
            time.sleep(0.3)

        results["direct_ip_tests"].append({
            "ip": ip,
            "shard_fingerprints": shard_fps,
            "unique_shards": len(set(shard_fps)),
        })

    # Summary
    print("\n  --- IP Resolution Summary ---")
    print(f"  Unique IPs behind www.sreality.cz: {len(ips)}")
    for t in results["direct_ip_tests"]:
        fp_counts = Counter(t["shard_fingerprints"])
        print(f"    IP {t['ip']}: shards={fp_counts}")
        if t["unique_shards"] == 1 and "ERROR" not in t["shard_fingerprints"][0]:
            print(f"      -> This IP always hits shard {t['shard_fingerprints'][0]}")
        elif t["unique_shards"] > 1:
            print(f"      -> This IP hits MULTIPLE shards (LB is behind this IP too)")

    save_json(results, "test2_ip_resolution")
    return results


# ══════════════════════════════════════════════════════════════
# TEST 3: Different Searches Same Behavior
# ══════════════════════════════════════════════════════════════
def test_different_searches():
    print("\n" + "=" * 70)
    print("TEST 3: Different Searches - Multi-Shard Behavior")
    print("=" * 70)

    searches = {
        "Praha_7_rent_17k25k": {
            "category_main_cb": 1,       # flats
            "category_type_cb": 2,       # rent
            "locality_district_id": 5007, # Praha 7
            "per_page": 500,
            "page": 1,
            "czk_price_summary_order2": "17000|25000",
        },
        "Praha_1_rent_all": {
            "category_main_cb": 1,       # flats
            "category_type_cb": 2,       # rent
            "locality_district_id": 5001, # Praha 1
            "per_page": 500,
            "page": 1,
        },
        "Brno_houses_sale": {
            "category_main_cb": 2,       # houses
            "category_type_cb": 1,       # sale
            "locality_region_id": 14,    # Jihomoravsky kraj (Brno region)
            "per_page": 500,
            "page": 1,
        },
    }

    results = {}

    for name, params in searches.items():
        print(f"\n  --- Search: {name} ---")
        fps = []
        result_sizes = []

        for i in range(10):
            try:
                resp = requests.get(API_URL, params=params, timeout=30)
                data = resp.json()
                ids = extract_ids(data)
                fp = fingerprint(ids)
                rs = data.get("result_size", 0)
                fps.append(fp)
                result_sizes.append(rs)
                sys.stdout.write(f"\r    Request {i+1}/10 - shard={fp} size={rs}")
                sys.stdout.flush()
            except Exception as e:
                fps.append(f"ERROR")
                result_sizes.append(0)
                print(f"\n    Request {i+1}/10 ERROR: {e}")
            time.sleep(0.5)

        print()
        fp_counts = Counter(fps)
        size_set = set(result_sizes)
        multi_shard = len(fp_counts) > 1

        print(f"    Shard distribution: {dict(fp_counts)}")
        print(f"    Unique result_sizes: {size_set}")
        print(f"    Multi-shard behavior: {'YES' if multi_shard else 'NO'}")

        results[name] = {
            "params": params,
            "shard_fingerprints": fps,
            "shard_distribution": dict(fp_counts),
            "result_sizes": result_sizes,
            "unique_result_sizes": list(size_set),
            "multi_shard": multi_shard,
            "num_unique_shards": len(fp_counts),
        }

    # Cross-search analysis
    print("\n  --- Cross-Search Analysis ---")
    for name, data in results.items():
        print(f"    {name}: {data['num_unique_shards']} shards, sizes={data['unique_result_sizes']}")

    all_multi = all(r["multi_shard"] for r in results.values())
    print(f"\n    All searches show multi-shard: {all_multi}")

    # Check if same shards appear across different searches
    all_fps = set()
    for r in results.values():
        all_fps |= set(r["shard_fingerprints"])
    print(f"    Total unique shard fingerprints across all searches: {len(all_fps)}")
    print(f"    (If shards are global, some fingerprints won't match across searches)")

    save_json(results, "test3_different_searches")
    return results


# ══════════════════════════════════════════════════════════════
# TEST 4: Sorting Parameter Effect
# ══════════════════════════════════════════════════════════════
def test_sorting_parameter():
    print("\n" + "=" * 70)
    print("TEST 4: Sorting Parameter Effect")
    print("=" * 70)

    sort_modes = {
        "no_sort": {},                           # default (no sort param)
        "sort_0_by_date": {"sort": 0},           # by date
        "sort_1_by_price": {"sort": 1},          # by price ascending
        "sort_2_by_price_desc": {"sort": 2},     # by price descending (guess)
        "sort_3_by_area": {"sort": 3},           # by area (guess)
    }

    results = {}

    for name, extra_params in sort_modes.items():
        print(f"\n  --- Sort mode: {name} ---")
        params = {**BASE_PARAMS, **extra_params}
        fps = []
        result_sizes = []
        id_sets = []

        for i in range(10):
            try:
                resp = requests.get(API_URL, params=params, timeout=30)
                data = resp.json()
                ids = extract_ids(data)
                fp = fingerprint(ids)
                rs = data.get("result_size", 0)
                fps.append(fp)
                result_sizes.append(rs)
                id_sets.append(ids)
                sys.stdout.write(f"\r    Request {i+1}/10 - shard={fp} size={rs}")
                sys.stdout.flush()
            except Exception as e:
                fps.append("ERROR")
                result_sizes.append(0)
                id_sets.append(frozenset())
                print(f"\n    ERROR: {e}")
            time.sleep(0.5)

        print()
        fp_counts = Counter(fps)
        multi_shard = len(fp_counts) > 1

        # Check if sorting changes which listings are returned (not just order)
        all_ids_union = frozenset().union(*id_sets) if id_sets else frozenset()
        all_ids_intersection = id_sets[0] if id_sets else frozenset()
        for s in id_sets[1:]:
            all_ids_intersection = all_ids_intersection & s

        print(f"    Shard distribution: {dict(fp_counts)}")
        print(f"    Multi-shard: {'YES' if multi_shard else 'NO'}")
        print(f"    Total unique IDs across all responses: {len(all_ids_union)}")
        print(f"    IDs common to ALL responses: {len(all_ids_intersection)}")

        results[name] = {
            "extra_params": extra_params,
            "shard_fingerprints": fps,
            "shard_distribution": dict(fp_counts),
            "result_sizes": result_sizes,
            "multi_shard": multi_shard,
            "num_unique_shards": len(fp_counts),
            "total_unique_ids": len(all_ids_union),
            "common_ids": len(all_ids_intersection),
        }

    # Compare: does sort change which shard you hit, or just order within a shard?
    print("\n  --- Sort Comparison ---")
    for name, r in results.items():
        print(f"    {name:25s}: {r['num_unique_shards']} shards, "
              f"sizes={set(r['result_sizes'])}, "
              f"union={r['total_unique_ids']}, common={r['common_ids']}")

    save_json(results, "test4_sorting")
    return results


# ══════════════════════════════════════════════════════════════
# TEST 5: Time-Based Correlation (100 rapid requests)
# ══════════════════════════════════════════════════════════════
def test_time_based_correlation():
    print("\n" + "=" * 70)
    print("TEST 5: Time-Based Correlation (100 rapid requests, 0.1s apart)")
    print("=" * 70)

    NUM = 100
    DELAY = 0.1

    results = []
    t_start = time.time()

    for i in range(NUM):
        t0 = time.time()
        try:
            resp = requests.get(API_URL, params=BASE_PARAMS, timeout=30)
            t1 = time.time()
            data = resp.json()
            ids = extract_ids(data)
            fp = fingerprint(ids)
            rs = data.get("result_size", 0)

            results.append({
                "request_num": i + 1,
                "timestamp": datetime.now().isoformat(),
                "elapsed_since_start": round(t0 - t_start, 3),
                "latency_ms": round((t1 - t0) * 1000),
                "shard": fp,
                "result_size": rs,
                "num_ids": len(ids),
            })
            if (i + 1) % 10 == 0:
                sys.stdout.write(f"\r  {i+1}/{NUM} requests done...")
                sys.stdout.flush()
        except Exception as e:
            results.append({
                "request_num": i + 1,
                "timestamp": datetime.now().isoformat(),
                "elapsed_since_start": round(t0 - t_start, 3),
                "latency_ms": -1,
                "shard": "ERROR",
                "result_size": 0,
                "error": str(e)[:100],
            })
        time.sleep(DELAY)

    print()
    total_time = time.time() - t_start
    print(f"  Total time: {total_time:.1f}s for {NUM} requests")

    # Analyze pattern
    shards = [r["shard"] for r in results if r["shard"] != "ERROR"]
    shard_counts = Counter(shards)
    unique_shards = sorted(shard_counts.keys())

    print(f"\n  --- Shard Distribution ---")
    for s, c in shard_counts.most_common():
        pct = c / len(shards) * 100
        bar = "#" * int(pct / 2)
        print(f"    {s}: {c:3d} hits ({pct:5.1f}%) {bar}")

    # Check for round-robin pattern
    print(f"\n  --- Pattern Analysis ---")
    # Map shards to indices for analysis
    shard_map = {s: i for i, s in enumerate(unique_shards)}
    shard_seq = [shard_map[s] for s in shards]

    # Check for strict alternation (round-robin)
    alternating = 0
    for i in range(1, len(shard_seq)):
        if shard_seq[i] != shard_seq[i - 1]:
            alternating += 1
    alternation_rate = alternating / (len(shard_seq) - 1) if len(shard_seq) > 1 else 0

    # Check for runs (same shard repeated)
    runs = []
    current_run = 1
    for i in range(1, len(shard_seq)):
        if shard_seq[i] == shard_seq[i - 1]:
            current_run += 1
        else:
            runs.append(current_run)
            current_run = 1
    runs.append(current_run)

    avg_run = sum(runs) / len(runs) if runs else 0
    max_run = max(runs) if runs else 0

    print(f"    Alternation rate: {alternation_rate:.2f} (1.0=perfect alternation, 0.0=all same)")
    print(f"    Average run length: {avg_run:.1f} (1.0=perfect alternation)")
    print(f"    Max run length: {max_run}")
    print(f"    Number of runs: {len(runs)}")

    # Chi-squared test for uniformity
    if len(unique_shards) >= 2:
        expected = len(shards) / len(unique_shards)
        chi2 = sum((c - expected) ** 2 / expected for c in shard_counts.values())
        # Rough p-value estimate for 1 df
        print(f"    Chi-squared (uniform): {chi2:.2f} (lower = more uniform)")
        if chi2 < 3.84:
            print(f"    -> Distribution is consistent with UNIFORM (p > 0.05)")
        else:
            print(f"    -> Distribution is NOT uniform (p < 0.05) -> WEIGHTED")

    # Check for time-based clustering
    print(f"\n  --- Temporal Clustering ---")
    # Split into 10 buckets of 10 requests each
    for bucket in range(10):
        bucket_shards = shards[bucket * 10: (bucket + 1) * 10]
        bc = Counter(bucket_shards)
        print(f"    Requests {bucket*10+1:3d}-{(bucket+1)*10:3d}: {dict(bc)}")

    # Text-based visualization of the sequence
    print(f"\n  --- Shard Sequence (first 100) ---")
    # Use letters A, B, C, ... for each shard
    shard_letters = {s: chr(65 + i) for i, s in enumerate(unique_shards)}
    seq_str = "".join(shard_letters.get(s, "?") for s in shards)
    for row in range(0, len(seq_str), 50):
        chunk = seq_str[row:row + 50]
        print(f"    {row+1:3d}: {chunk}")

    # Latency by shard
    print(f"\n  --- Latency by Shard ---")
    shard_latencies = defaultdict(list)
    for r in results:
        if r["shard"] != "ERROR" and r["latency_ms"] > 0:
            shard_latencies[r["shard"]].append(r["latency_ms"])
    for s in unique_shards:
        lats = shard_latencies[s]
        if lats:
            avg = sum(lats) / len(lats)
            print(f"    {s}: avg={avg:.0f}ms min={min(lats)}ms max={max(lats)}ms n={len(lats)}")

    data_out = {
        "test": "time_based_correlation",
        "num_requests": NUM,
        "delay_s": DELAY,
        "total_time_s": round(total_time, 1),
        "shard_distribution": dict(shard_counts),
        "alternation_rate": round(alternation_rate, 3),
        "avg_run_length": round(avg_run, 2),
        "max_run_length": max_run,
        "shard_sequence": shards,
        "shard_letters": shard_letters,
        "requests": results,
    }
    save_json(data_out, "test5_time_correlation")
    return data_out


# ══════════════════════════════════════════════════════════════
# TEST 6: ETag / Caching Analysis
# ══════════════════════════════════════════════════════════════
def test_etag_caching():
    print("\n" + "=" * 70)
    print("TEST 6: ETag / Caching Analysis")
    print("=" * 70)

    results = []

    # Phase 1: Check basic caching headers
    print("\n  --- Phase 1: Caching Headers (20 requests) ---")
    etags = set()
    last_modified_values = set()

    for i in range(20):
        resp = requests.get(API_URL, params=BASE_PARAMS, timeout=30)
        data = resp.json()
        ids = extract_ids(data)
        fp = fingerprint(ids)

        cache_headers = {}
        for h in ["etag", "last-modified", "cache-control", "age", "expires",
                   "x-cache", "x-cache-hits", "x-served-by", "cf-cache-status",
                   "pragma", "x-varnish"]:
            val = resp.headers.get(h)
            if val:
                cache_headers[h] = val

        if "etag" in cache_headers:
            etags.add(cache_headers["etag"])
        if "last-modified" in cache_headers:
            last_modified_values.add(cache_headers["last-modified"])

        results.append({
            "request_num": i + 1,
            "shard": fp,
            "result_size": data.get("result_size", 0),
            "cache_headers": cache_headers,
        })
        sys.stdout.write(f"\r    Request {i+1}/20 - shard={fp}")
        sys.stdout.flush()
        time.sleep(0.3)

    print()

    # Summarize cache headers
    all_cache_headers = Counter()
    for r in results:
        for h in r["cache_headers"]:
            all_cache_headers[h] += 1

    if all_cache_headers:
        print("\n    Cache-related headers found:")
        for h, c in all_cache_headers.most_common():
            values = set(r["cache_headers"].get(h, "") for r in results if h in r["cache_headers"])
            print(f"      {h}: present in {c}/20 responses, unique values: {len(values)}")
            for v in list(values)[:5]:
                print(f"        '{v}'")
    else:
        print("\n    No caching headers found in any response.")

    # Check ETag correlation with shard
    if etags:
        print(f"\n    Unique ETags: {len(etags)}")
        etag_to_shard = defaultdict(set)
        for r in results:
            if "etag" in r["cache_headers"]:
                etag_to_shard[r["cache_headers"]["etag"]].add(r["shard"])
        for et, shards in etag_to_shard.items():
            print(f"      ETag '{et}' -> shards: {shards}")
        if all(len(s) == 1 for s in etag_to_shard.values()):
            print("      -> ETags correlate perfectly with shards!")
        else:
            print("      -> ETags do NOT map 1:1 to shards")

    # Phase 2: Conditional requests (If-None-Match / If-Modified-Since)
    print("\n  --- Phase 2: Conditional Requests ---")
    if etags:
        for etag in list(etags)[:3]:
            print(f"\n    Testing If-None-Match: {etag}")
            resp = requests.get(
                API_URL, params=BASE_PARAMS,
                headers={"If-None-Match": etag},
                timeout=30
            )
            print(f"      Status: {resp.status_code} (304=Not Modified, 200=Changed)")
            if resp.status_code == 304:
                print(f"      -> Server respects ETags! Content not re-sent.")
            elif resp.status_code == 200:
                print(f"      -> Server ignores If-None-Match, always sends full response")
            time.sleep(0.3)

    if last_modified_values:
        for lm in list(last_modified_values)[:2]:
            print(f"\n    Testing If-Modified-Since: {lm}")
            resp = requests.get(
                API_URL, params=BASE_PARAMS,
                headers={"If-Modified-Since": lm},
                timeout=30
            )
            print(f"      Status: {resp.status_code}")
            time.sleep(0.3)

    # Phase 3: Check Age header to infer cache freshness
    print("\n  --- Phase 3: Cache Age Analysis ---")
    age_values = [int(r["cache_headers"]["age"]) for r in results if "age" in r["cache_headers"]]
    if age_values:
        print(f"    Age header values: min={min(age_values)}s, max={max(age_values)}s, avg={sum(age_values)/len(age_values):.0f}s")
        # Group by shard
        shard_ages = defaultdict(list)
        for r in results:
            if "age" in r["cache_headers"]:
                shard_ages[r["shard"]].append(int(r["cache_headers"]["age"]))
        for shard, ages in shard_ages.items():
            print(f"      Shard {shard}: ages = {ages}")
    else:
        print("    No Age header found - responses may not be cached or cache doesn't report age")

    data_out = {
        "test": "etag_caching",
        "etags_found": list(etags),
        "last_modified_found": list(last_modified_values),
        "cache_headers_summary": dict(all_cache_headers),
        "requests": results,
    }
    save_json(data_out, "test6_etag_caching")
    return data_out


# ══════════════════════════════════════════════════════════════
# MAIN: Run all tests and produce summary
# ══════════════════════════════════════════════════════════════
def main():
    print("=" * 70)
    print("SREALITY API EMPIRICAL TESTS FOR RESEARCH PAPER")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 70)

    # Suppress InsecureRequestWarning for direct-IP tests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    all_results = {}

    tests = [
        ("test1_headers", test_response_headers),
        ("test2_ip_resolution", test_ip_resolution),
        ("test3_different_searches", test_different_searches),
        ("test4_sorting", test_sorting_parameter),
        ("test5_time_correlation", test_time_based_correlation),
        ("test6_etag_caching", test_etag_caching),
    ]

    for name, func in tests:
        try:
            result = func()
            all_results[name] = result
        except Exception as e:
            print(f"\n  !!! TEST FAILED: {e}")
            import traceback
            traceback.print_exc()
            all_results[name] = {"error": str(e)}

    # ── Final Summary ──────────────────────────────────────
    print("\n" + "=" * 70)
    print("SUMMARY OF FINDINGS")
    print("=" * 70)

    # Test 1 summary
    if "test1_headers" in all_results and "error" not in all_results["test1_headers"]:
        d = all_results["test1_headers"]
        print(f"\n1. RESPONSE HEADERS:")
        print(f"   Varying headers: {d.get('varying_headers', [])}")

    # Test 2 summary
    if "test2_ip_resolution" in all_results and "error" not in all_results["test2_ip_resolution"]:
        d = all_results["test2_ip_resolution"]
        dns = d.get("dns", {})
        www_ips = dns.get("www.sreality.cz", [])
        print(f"\n2. IP RESOLUTION:")
        print(f"   IPs behind www.sreality.cz: {www_ips}")
        for t in d.get("direct_ip_tests", []):
            print(f"   IP {t['ip']}: {t['unique_shards']} unique shards -> "
                  f"{'Multiple shards per IP' if t['unique_shards'] > 1 else 'Single shard per IP'}")

    # Test 3 summary
    if "test3_different_searches" in all_results and "error" not in all_results["test3_different_searches"]:
        d = all_results["test3_different_searches"]
        print(f"\n3. DIFFERENT SEARCHES:")
        for name, r in d.items():
            if isinstance(r, dict) and "multi_shard" in r:
                print(f"   {name}: {'MULTI-SHARD' if r['multi_shard'] else 'SINGLE-SHARD'} "
                      f"({r['num_unique_shards']} shards)")

    # Test 4 summary
    if "test4_sorting" in all_results and "error" not in all_results["test4_sorting"]:
        d = all_results["test4_sorting"]
        print(f"\n4. SORTING EFFECT:")
        for name, r in d.items():
            if isinstance(r, dict) and "multi_shard" in r:
                print(f"   {name}: {r['num_unique_shards']} shards, "
                      f"union={r.get('total_unique_ids', '?')}, common={r.get('common_ids', '?')}")

    # Test 5 summary
    if "test5_time_correlation" in all_results and "error" not in all_results["test5_time_correlation"]:
        d = all_results["test5_time_correlation"]
        dist = d.get("shard_distribution", {})
        print(f"\n5. TIME-BASED CORRELATION (100 requests):")
        print(f"   Shard distribution: {dist}")
        total = sum(dist.values())
        for s, c in dist.items():
            print(f"     {s}: {c}/{total} ({c/total*100:.1f}%)")
        alt = d.get("alternation_rate", 0)
        avg_run = d.get("avg_run_length", 0)
        if alt > 0.8:
            print(f"   Pattern: Appears RANDOM/ROUND-ROBIN (alternation={alt:.2f})")
        elif alt < 0.3:
            print(f"   Pattern: Appears STICKY/SEQUENTIAL (alternation={alt:.2f})")
        else:
            print(f"   Pattern: MIXED (alternation={alt:.2f}, avg_run={avg_run:.1f})")

    # Test 6 summary
    if "test6_etag_caching" in all_results and "error" not in all_results["test6_etag_caching"]:
        d = all_results["test6_etag_caching"]
        print(f"\n6. ETAG/CACHING:")
        print(f"   ETags found: {len(d.get('etags_found', []))}")
        print(f"   Last-Modified found: {len(d.get('last_modified_found', []))}")
        print(f"   Cache headers: {d.get('cache_headers_summary', {})}")

    # Save combined summary
    summary_path = save_json(all_results, "test_all_summary")
    print(f"\nAll results saved. Combined summary: {summary_path}")
    print(f"Finished: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
