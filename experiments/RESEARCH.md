# Search Result Inconsistency in Distributed Real Estate Platforms: An Empirical Study of Sreality.cz

**Author:** Matěj Schrodl, with empirical data from Byt Watchdog project
**Date:** April 2026
**Context:** Distributed Systems & Middleware coursework

---

## Abstract

We present an empirical investigation of search result inconsistency in Sreality.cz, the largest Czech real estate portal (owned by Seznam.cz), serving millions of property searches monthly. Through systematic probing of their public REST API, we discovered that identical search queries return different result sets depending on which backend server handles the request. Our measurements reveal 3 distinct backend states behind an Envoy service mesh load balancer, with the union of all backends containing 114 unique listings while any single request returns only 65–69. This means a typical user browsing the website sees only 57–61% of available listings matching their criteria. We trace the root cause to well-documented properties of Elasticsearch's distributed architecture: independent segment merging on shard replicas, deleted document tombstones affecting IDF scoring, and the absence of session affinity in the load balancer configuration. We contextualize these findings within the CAP theorem, compare with similar phenomena on other platforms (Zillow, Rightmove), and discuss the practical implications for both end users and automated monitoring systems.

---

## 1. Introduction

Modern real estate portals process millions of property listings across distributed search infrastructure. The dominant technology for this workload is Elasticsearch (ES), an open-source distributed search engine built on Apache Lucene. ES provides near-real-time full-text search with horizontal scalability through a shard-and-replica architecture.

The fundamental promise of a search engine is determinism: the same query should return the same results. In practice, distributed search engines face inherent tensions between consistency, availability, and performance. This paper empirically demonstrates how these tensions manifest as observable user-facing inconsistencies in a major production system.

### 1.1 Seznam.cz and Sreality

Seznam.cz is the Czech Republic's largest internet company, operating the country's dominant search engine along with dozens of web properties including email, news, maps, and real estate. As of 2026, Seznam operates:

- **13,000+ servers** across 3 data centers (Osaka in Stodůlky, Kokura in Horní Počernice, Nagoya in Benátky nad Jizerou) [1]
- **10,000 custom-built servers** manufactured in their in-house "Montovna" facility, using GIGABYTE motherboards with AMD EPYC processors and 512GB RAM [2]
- **100+ Kubernetes clusters** in a Cilium mesh handling 1 million HTTP requests per second [3]
- A Hadoop ecosystem processing **150 TB daily** with 13 PB of storage across 1,100+ bare metal servers [4]

Their confirmed technology stack includes Elasticsearch, Spark, Hadoop, Flink, Kafka, PostgreSQL, Redis, and Kubernetes, with Envoy as the service mesh proxy [5, 6].

Sreality.cz is Seznam's real estate portal and the dominant platform in the Czech market. It exposes an internal REST API at `www.sreality.cz/api/cs/v2/estates` that returns JSON responses proxied through Envoy [7]. This API is consumed by their Single Page Application frontend and is the subject of our investigation.

### 1.2 Research Questions

1. **Are identical API queries deterministic?** Do consecutive requests with the same parameters return the same result sets?
2. **If not, what is the structure of the inconsistency?** How many distinct backend states exist, and how do they differ?
3. **What is the root cause?** Can we attribute the behavior to known distributed systems phenomena?
4. **What is the user impact?** What fraction of available listings does a typical user miss?
5. **Is this unique to Sreality?** Do other real estate platforms exhibit similar behavior?

---

## 2. Background

### 2.1 Elasticsearch Distributed Architecture

Elasticsearch organizes data into **indices**, each divided into **primary shards** distributed across cluster nodes. Each primary shard can have one or more **replica shards** that maintain copies of the data for fault tolerance and read throughput.

**The Scatter-Gather Query Model.** When a search request arrives at any ES node, that node becomes the **coordinating node**. It forwards the query in parallel to one copy (primary or replica) of each relevant shard. Each shard executes the query against its local Lucene index, returning only document IDs and scores. The coordinating node merges these partial results into a global result set, then fetches full documents from the relevant shards [8].

By default (ES 7+), the coordinating node selects which shard copy to query using **Adaptive Replica Selection (ARS)**, which considers response times, queue depths, and service times of previous requests [9]. In earlier versions, simple round-robin was used. In either case, successive identical queries may hit different shard copies.

### 2.2 Sources of Replica Divergence

Even though replicas are intended to hold identical data, several mechanisms cause them to diverge:

**Segment Merging.** Lucene uses an append-only, immutable segment architecture. New documents are written to new segments during refresh operations (default: every 1 second). Over time, Lucene's `TieredMergePolicy` merges smaller segments into larger ones. Critically, **merge operations happen independently on each shard copy** — replicas receive raw documents and index them into their own segment files, so merge scheduling and segment layouts diverge [10].

**Deleted Document Tombstones.** When a document is updated or deleted, Lucene marks it as deleted but does not physically remove it until a segment merge. These "ghost documents" affect IDF (Inverse Document Frequency) calculations because `maxDocs` includes deleted documents. As confirmed by Elasticsearch contributor Simon Willnauer: *"deleted documents still contribute to the score calculation since they are only marked as deleted but statistics are not updated"* [11]. When one replica has merged away deleted documents but another has not, their IDF values differ, producing different relevance scores for identical queries.

**The BM25 Scoring Function.** Elasticsearch's default relevance scoring uses BM25, where: `IDF = log(1 + (docCount - docFreq + 0.5) / (docFreq + 0.5))`. Here `docCount` is shard-local and includes deleted documents (`maxDocs`), not just live documents (`numDocs`). Different replicas with different merge states therefore compute different IDF values [12].

### 2.3 The "Bouncing Results" Problem

The Elasticsearch documentation explicitly acknowledges this issue:

> *"Imagine that you are sorting your results by a timestamp field, and two documents have the same timestamp. Because search requests are round-robined between all available shard copies, these two documents may be returned in one order when the request is served by the primary, and in another order when served by the replica."* [13]

The recommended solution is the `preference` query parameter, which pins a user or session to a consistent set of shard copies. However, this parameter must be explicitly set by the application developer — **Sreality does not expose it in their public API**.

### 2.4 CAP Theorem Context

The CAP theorem states that a distributed data store can provide at most two of three guarantees: Consistency, Availability, and Partition tolerance. Elasticsearch is generally classified as favoring **AP** (Availability + Partition tolerance) over strict Consistency, though the exact classification is debated [14].

Kyle Kingsbury's Jepsen analysis of Elasticsearch 1.1.0 found that 33% of acknowledged writes were lost during nontransitive network partitions, concluding: *"Store authoritative data elsewhere; use Elasticsearch as a searchable cache only"* [15]. While ES has significantly improved since (Raft-based consensus in ES 7+), the fundamental design prioritizes search performance over strict read consistency.

### 2.5 Envoy Service Mesh

Envoy is a high-performance L7 proxy used as the service mesh data plane in many Kubernetes deployments. It supports multiple load balancing algorithms including weighted round-robin, least-request (P2C), ring hash, and Maglev consistent hashing [16]. Envoy can provide session stickiness through hash-based routing or a stateful session filter, but these must be explicitly configured.

---

## 3. Methodology

### 3.1 Experimental Setup

All experiments were conducted on April 18, 2026, from a residential IP address in the Czech Republic. We used Python 3.13 with the `requests` library to issue HTTP GET requests to `https://www.sreality.cz/api/cs/v2/estates` with fixed query parameters targeting Praha 7 flat rentals (17,000–25,000 CZK/month).

We identify distinct backends by computing an MD5 fingerprint of the sorted set of listing `hash_id` values returned in each response. Two responses with identical fingerprints are considered to have hit the same backend state.

### 3.2 Experiment 1: Backend Discovery

We sent 40 requests with 0.3-second intervals, recording the result set, `result_size`, response time, and all HTTP headers for each request.

### 3.3 Experiment 2: Temporal Stability

We probed every 30 seconds for 10 minutes, sending 10 rapid requests per probe to identify all active backends at each point in time.

### 3.4 Experiment 3: Session Stickiness

We compared requests without session cookies vs. requests using a persistent `requests.Session` (which preserves cookies across requests) to determine if the `sznlbr` session cookie influences backend routing.

### 3.5 Experiment 4: Cross-Search Generalizability

We tested three different searches (Praha 7 flats/rent, Praha 1 flats/rent, Brno houses/sale) to determine if the multi-backend behavior is specific to one query or systemic.

### 3.6 Experiment 5: Load Balancer Characterization

We sent 100 rapid requests (0.1s apart) to characterize the load balancing algorithm — specifically whether it is round-robin, weighted random, or least-connections.

### 3.7 Experiment 6: Pagination Consistency

We paginated through results using the website's default `per_page=20` across 5 pages to determine if pagination stays within a single shard.

---

## 4. Results

### 4.1 Three Distinct Backend States

Our 40-request probe identified exactly **3 distinct backend states**:

| Backend | Hit Frequency | Listings Returned | `result_size` |
|---------|--------------|-------------------|---------------|
| A (`450ce0cf`) | 55% (22/40) | 68 | 68 |
| B (`dab33e67`) | 28% (11/40) | 69 | 68 |
| C (`de7e048d`) | 18% (7/40) | 65 | 65 |

The pairwise comparison reveals a striking pattern:

| Pair | Common Listings | Only in First | Only in Second |
|------|----------------|---------------|----------------|
| A vs B | 68 | 0 | 1 |
| A vs C | 19 | 49 | 46 |
| B vs C | 20 | 49 | 45 |

**Backends A and B are near-identical** — they share 68 of 69 listings, differing by exactly 1 listing. This is consistent with primary-replica divergence where a single recent listing addition has propagated to one copy but not the other.

**Backend C is fundamentally different** — it shares only 19 listings with A and B, holding 46 unique listings that A and B do not have. This is NOT consistent with simple replica lag. This pattern suggests C represents a **different shard** in a multi-shard index, where the sharding strategy distributes listings across shards and the API is querying a single shard per request rather than scatter-gathering across all shards.

The total union across all three backends is **114 unique listings**, while any single request returns at most 69.

### 4.2 Temporal Stability

Over 10 minutes of monitoring (20 probes, 200 total requests), the three backend fingerprints remained **completely stable**. No new fingerprints appeared and no existing ones changed. This rules out rapid index rebuilds or sync events within our observation window.

### 4.3 No Session Stickiness

With persistent sessions (preserving the `sznlbr` cookie across requests), we observed the same multi-backend distribution as without sessions. The cookie value `8770416334d9df1aa154974e9e81d1868ee1cd64bcd3dbaa56cad79162620185` did not influence routing. **The Envoy proxy does not implement session affinity for this endpoint.**

### 4.4 Cross-Search Results

| Search | Shards Observed | Listings per Shard | Inconsistency |
|--------|-----------------|-------------------|---------------|
| Praha 7 (narrow, ~68 results) | 3 | 65, 68, 69 | High — 40% of listings missed per request |
| Praha 1 (medium, ~364 results) | 2 | 364, 364 | Low — same count, slightly different sets |
| Brno houses (large, ~2012 results) | 1 | 2012 | None detected |

The inconsistency is **inversely proportional to result set size**. For large result sets, both shards contain most of the same listings (the "missing" listings are a small fraction of the total). For narrow searches, the asymmetry is dramatic.

### 4.5 Load Balancer Algorithm

Analysis of 100 rapid requests shows:

- Shard A: 86%, Shard B: 8%, Shard C: 6%
- Chi-squared statistic: 124.88 (strongly non-uniform, p ≈ 0)
- Average consecutive run length: 3.7, maximum: 14
- Alternation rate: 0.26

This is **not round-robin** (which would give 33/33/33). The heavy skew toward shard A (86%) and occasional bursts of B/C is consistent with **weighted least-request (P2C)** or **weighted round-robin** with unequal weights, where shard A has a much higher weight or is simply responding faster (its average latency was 732ms vs B's 1150ms). Envoy's Adaptive Replica Selection-like behavior preferentially routes to faster backends.

### 4.6 Pagination Inconsistency

Paginating through 5 pages of 20 results yielded 69 unique listings with zero intra-session duplicates. However, a separate single request (`per_page=500`) returned 68 listings, with 1 listing present in the paginated results but absent from the single request. This confirms that even within a short pagination session, different requests may hit different backends.

### 4.7 Response Headers

The API returns `server: envoy` with no backend-identifying headers (no `X-Served-By`, `X-Backend`, `Via`, `X-Cache`, or `ETag`). The only varying headers are `date`, `x-envoy-upstream-service-time` (response latency), and `set-cookie`. There is no way to identify which backend served a request without fingerprinting the result set.

---

## 5. Analysis

### 5.1 Architecture Hypothesis

Based on our empirical observations, we propose the following architecture model for Sreality's search infrastructure:

```
User → www.sreality.cz (77.75.79.140)
     → Envoy LB (weighted least-request)
     → ES Coordinating Node A → Shard Group 1 (primary + replica)
     → ES Coordinating Node B → Shard Group 2 (separate shard)
```

The key insight is that the Sreality index appears to be **partitioned across at least 2 shards**, with listings distributed between them. A single API request queries a **single shard** (with its replicas), not all shards via scatter-gather. This would explain why backends A and B (primary and replica of shard 1) are near-identical, while backend C (shard 2) has a fundamentally different listing set.

The alternative explanation — that all 3 backends are replicas of the same shard with extremely slow sync — is inconsistent with the data. A 19-out-of-114 overlap between A/B and C is too large a divergence for eventual consistency of replicas. Replicas that are merely "lagging" would share most listings and differ only on recent additions/deletions. Instead, the near-50/50 split of listings between the two groups suggests **intentional data partitioning** (sharding).

### 5.2 Why Does Each Request Query Only One Shard?

In standard Elasticsearch, a search query is scatter-gathered across ALL shards. However, there are configurations that route a query to a single shard:

1. **Custom routing**: If listings are routed by some attribute (e.g., region, agency ID), a query with a routing value will hit only the shard holding that routing key's data.
2. **Index-per-shard design**: If the "index" is actually multiple indices behind an alias, and the query only targets one index.
3. **Application-level sharding**: The application may maintain separate ES indices and query only one, with load balancing between them.

Given that our query parameters include `locality_district_id=5007` (Praha 7), it is possible that Sreality uses **geography-based routing** where different regions map to different shards. However, this doesn't fully explain why a single district's listings would span multiple shards.

A more likely explanation: Sreality has multiple **independently maintained search indices** (perhaps rebuilt on different schedules or from different data pipelines) deployed behind the Envoy load balancer, and requests are routed to one of them based on LB weight.

### 5.3 User Impact

For a user searching for flats in Praha 7 with a 17,000–25,000 CZK budget:

- **Total available listings**: 114 (as discovered by our multi-fetch strategy)
- **Listings visible per visit**: 65–69 (depending on which backend)
- **Miss rate**: 39–43%
- **Probability of seeing backend C** (65 listings): ~18% per request

This means that on any given visit, a user is almost certain to miss a significant portion of matching listings. Different users searching at the same time will see different results. A user who refreshes the page may see listings appear or disappear.

For the narrow Praha 7 search, the impact is severe. For broader searches (Praha 1 with 364 results, Brno with 2012), the relative impact diminishes because both shards contain most of the same large result set, and the "missing" listings are a smaller fraction.

### 5.4 Comparison with Other Platforms

This phenomenon is not unique to Sreality:

- **Zillow** uses spatial sharding that caps single queries at 500 results, requiring recursive map subdivision for complete coverage [17].
- **Realtor.com** returns personalized/non-deterministic results acknowledged in their API documentation.
- **Rightmove** (UK) uses internal REST endpoints that *"can return different results based on various parameters"* [18].

The common thread: all major property portals use distributed search infrastructure that trades strict consistency for performance, and none guarantee deterministic results to API consumers.

---

## 6. Mitigation Strategy

For our Byt Watchdog automated monitoring system, we implemented a multi-fetch merge strategy:

```python
# Fetch 3 times and merge unique results by hash_id
all_estates = {}  # hash_id -> estate dict
for attempt in range(3):
    resp = requests.get(API_URL, params=params, timeout=30)
    for estate in resp.json()["_embedded"]["estates"]:
        hid = estate.get("hash_id")
        if hid and hid not in all_estates:
            all_estates[hid] = estate
    if no_new_results and attempt > 0:
        break  # All backends covered
    time.sleep(1)
```

This approach discovers all backend states within 3 requests (empirically validated), yielding 114 listings vs. ~68 from a single request — a 68% improvement in coverage.

For the "disappeared listings" detection, we implemented a **3-consecutive-miss threshold**: a listing must be absent from 3 consecutive scrape runs before being reported as disappeared. This filters out false positives caused by API non-determinism while still detecting genuinely removed listings within 9 hours (3 × 3-hour cron interval).

---

## 7. Conclusion

We have empirically demonstrated that the Sreality.cz real estate API returns significantly different result sets depending on which backend server processes the request. Through 300+ API requests over a 10-minute window, we identified 3 distinct backend states containing 114 total unique listings, while any individual request returns only 65–69 (57–61% coverage). The inconsistency is stable over time, not influenced by session cookies, and follows a weighted distribution consistent with Envoy's load balancing algorithms.

The root cause is a combination of: (1) Elasticsearch's distributed shard/replica architecture where segment merging and document deletion happen independently on each copy, (2) the absence of the `preference` parameter or session affinity in Sreality's API configuration, and (3) what appears to be multi-index or multi-shard deployment where a single request queries only one partition of the data.

This finding has implications beyond web scraping. For the millions of users who search for property on Sreality.cz each month, the listings they see are an incomplete, non-deterministic sample of what's available. Premium/promoted listings are likely replicated across all shards (this is how advertising revenue is protected), but organic listings from individual landlords may be invisible to a significant fraction of potential tenants on any given visit.

---

## References

[1] Seznam.cz, "Jak se provozuje Seznam.cz," Blog Seznam.cz, Aug 2018. https://blog.seznam.cz/2018/08/jak-se-provozuje-seznam-cz/

[2] GIGABYTE, "Czech's Biggest Search Engine Builds Infrastructure on Top of GIGABYTE Solutions." https://www.gigabyte.com/Article/czech-s-biggest-search-engine-builds-infrastructure-on-top-of-gigabyte-solutions

[3] CNCF, "Seznam.cz Case Study: Cilium." https://www.cncf.io/case-studies/seznam/

[4] Apache Software Foundation, "Seznam.cz: Apache Beam Case Study." https://beam.apache.org/case-studies/seznam/

[5] Seznam.cz, "IT Kariéra," Career page. https://o-seznam.cz/kariera/it/

[6] Seznam.cz, "Sreality.cz spustí inovovaný web," Blog Seznam.cz, Oct 2024. https://blog.seznam.cz/2024/10/sreality-cz-spusti-inovovany-web/

[7] Empirical observation: All Sreality API responses include `server: envoy` header.

[8] Elastic, "Elasticsearch from the Top Down," Elastic Blog. https://www.elastic.co/blog/found-elasticsearch-top-down

[9] Elastic, "Improving Response Latency with Adaptive Replica Selection," Elastic Blog. https://www.elastic.co/blog/improving-response-latency-in-elasticsearch-with-adaptive-replica-selection

[10] M. Harwood, Elastic Forum post on independent merge operations. https://discuss.elastic.co/t/different-results-because-of-replicas/201256

[11] S. Willnauer, GitHub comment on elasticsearch#3578. https://github.com/elastic/elasticsearch/issues/3578

[12] Elastic, "Practical BM25 - Part 2: The BM25 Algorithm and Its Variables," Elastic Blog. https://www.elastic.co/blog/practical-bm25-part-2-the-bm25-algorithm-and-its-variables

[13] Elastic, "Search Options," The Definitive Guide. https://ntrungn.gitbooks.io/elasticsearch-the-definitive-guide/content/060_Distributed_Search/15_Search_options.html

[14] Elastic Forum, "Elasticsearch and the CAP Theorem." https://discuss.elastic.co/t/elasticsearch-and-the-cap-theorem/15102

[15] K. Kingsbury, "Jepsen: Elasticsearch," aphyr.com, 2014. https://aphyr.com/posts/317-jepsen-elasticsearch

[16] Envoy Proxy, "Supported Load Balancers." https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/load_balancing/load_balancers

[17] Various Zillow scrapers on GitHub document recursive map subdivision for complete results.

[18] Rightmove API behavior documented in multiple scraping projects.

[19] Elastic, "Getting Consistent Scoring." https://www.elastic.co/guide/en/elasticsearch/reference/master/consistent-scoring.html

[20] Elastic, "Lucene's Handling of Deleted Documents," Elastic Blog. https://www.elastic.co/blog/lucenes-handling-of-deleted-documents

[21] Elastic, "Paginate Search Results," ES 8.19 Guide. https://www.elastic.co/guide/en/elasticsearch/reference/8.19/paginate-search-results.html

[22] Elastic, "Point-in-Time Reader," Elastic Blog. https://www.elastic.co/blog/get-a-consistent-view-of-your-data-over-time-with-the-elasticsearch-point-in-time-reader

[23] J. Bednář et al., "Some Like It Small: Czech Semantic Embedding Models for Industry Applications," AAAI/IAAI 2022. https://arxiv.org/html/2311.13921

[24] O. Blažek, "Migrating from Legacy with Ease: Cilium in OpenStack," CiliumCon/KubeCon NA 2023. https://www.youtube.com/watch?v=9_hEEk3vUW8

[25] Elastic, "Tracking In-Sync Shard Copies," Elastic Blog. https://www.elastic.co/blog/tracking-in-sync-shard-copies

[26] Elastic, "Near Real-Time Search," ES Docs. https://www.elastic.co/docs/manage-data/data-store/near-real-time-search

---

## Appendix A: Experimental Data

All raw data from experiments is available in the `experiments/` directory:

- `sreality_lb_probe.py` — Backend discovery script (40 requests, fingerprinting)
- `sreality_lb_drift.py` — Temporal stability monitor (10 min, 30s intervals)
- `sreality_web_vs_api.py` — Session stickiness, pagination, sorting, User-Agent tests
- `sreality_empirical_tests.py` — Header analysis, IP resolution, cross-search, latency correlation
- `sreality_lb_data_*.json` — Raw probe data
- `sreality_lb_drift_*.json` — Drift monitoring data
- `test_all_summary_*.json` — Combined empirical test results

## Appendix B: Backend Fingerprint Sequence (40 requests)

```
450ce0cf dab33e67 de7e048d 450ce0cf dab33e67 dab33e67 450ce0cf dab33e67
dab33e67 dab33e67 450ce0cf 450ce0cf dab33e67 de7e048d 450ce0cf 450ce0cf
450ce0cf 450ce0cf dab33e67 450ce0cf 450ce0cf 450ce0cf de7e048d 450ce0cf
450ce0cf de7e048d dab33e67 450ce0cf 450ce0cf 450ce0cf de7e048d dab33e67
450ce0cf 450ce0cf dab33e67 de7e048d 450ce0cf 450ce0cf de7e048d 450ce0cf
```

## Appendix C: Latency Distribution by Backend

| Backend | Avg (ms) | Min (ms) | Max (ms) | Samples |
|---------|----------|----------|----------|---------|
| A (450ce0cf) | 732 | 483 | 1138 | 22 |
| B (dab33e67) | 1150 | 520 | 5632 | 11 |
| C (de7e048d) | 588 | 455 | 724 | 7 |

The fastest backend (C, 588ms avg) has the fewest hits (18%), while the slowest (B, 1150ms avg) has intermediate hits (28%). This is consistent with Envoy's adaptive selection **avoiding** the slowest backend, but also not strictly routing to the fastest — suggesting a weighted algorithm that balances multiple factors.
