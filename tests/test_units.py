"""Unit tests for scoring, dedup, metro, and db modules.

Run with: python3 -m pytest tests/test_units.py -v
"""
import json
import os
import pytest
from scrapers.base import Listing


def _make_listing(**kwargs) -> Listing:
    defaults = dict(
        id="test:1", source="test", title="Test", price=20000,
        location="Praha 7 - Holešovice", url="https://example.com",
    )
    defaults.update(kwargs)
    return Listing(**defaults)


# ─── Scoring ────────────────────────────────────────────────

class TestScoring:
    RENTAL_PROFILE = {
        "scoring": {
            "price_per_m2_weight": 40,
            "disposition_weight": 30,
            "preferred_dispositions": ["2+kk", "2+1", "3+kk"],
            "size_weight": 15,
            "ideal_size_m2": 55,
            "neighborhood_weight": 15,
            "preferred_neighborhoods": ["Holešovice", "Letná", "Bubeneč"],
        }
    }

    HOUSE_PROFILE = {
        "scoring": {
            "land_weight": 40,
            "ideal_land_m2": 2000,
            "price_weight": 30,
            "max_good_price": 3000000,
            "size_weight": 30,
            "ideal_size_m2": 150,
        }
    }

    def test_good_rental_scores_high(self):
        from scoring import compute_score
        l = _make_listing(price=20000, size_m2=50, disposition="2+kk")
        score = compute_score(l, self.RENTAL_PROFILE)
        assert score >= 70, f"Good rental should score 70+, got {score}"

    def test_bad_rental_scores_low(self):
        from scoring import compute_score
        l = _make_listing(price=24000, size_m2=28, disposition="1+kk", location="Praha 7")
        score = compute_score(l, self.RENTAL_PROFILE)
        assert score < 30, f"Bad rental should score <30, got {score}"

    def test_preferred_disposition_first_scores_highest(self):
        from scoring import compute_score
        l1 = _make_listing(price=20000, size_m2=50, disposition="2+kk")
        l2 = _make_listing(price=20000, size_m2=50, disposition="3+kk")
        s1 = compute_score(l1, self.RENTAL_PROFILE)
        s2 = compute_score(l2, self.RENTAL_PROFILE)
        assert s1 > s2, "First preferred disposition should score higher"

    def test_no_size_doesnt_crash(self):
        from scoring import compute_score
        l = _make_listing(disposition="2+kk")
        score = compute_score(l, self.RENTAL_PROFILE)
        assert isinstance(score, int)

    def test_no_disposition_doesnt_crash(self):
        from scoring import compute_score
        l = _make_listing(size_m2=50)
        score = compute_score(l, self.RENTAL_PROFILE)
        assert isinstance(score, int)

    def test_empty_scoring_config_returns_zero(self):
        from scoring import compute_score
        l = _make_listing()
        assert compute_score(l, {}) == 0
        assert compute_score(l, {"scoring": {}}) == 0

    def test_house_large_land_scores_high(self):
        from scoring import compute_score
        l = _make_listing(price=2500000, size_m2=150, land_m2=2000)
        score = compute_score(l, self.HOUSE_PROFILE)
        assert score >= 80, f"House with ideal land/price/size should score 80+, got {score}"

    def test_house_small_land_scores_lower(self):
        from scoring import compute_score
        l1 = _make_listing(price=3000000, size_m2=100, land_m2=2000)
        l2 = _make_listing(price=3000000, size_m2=100, land_m2=200)
        s1 = compute_score(l1, self.HOUSE_PROFILE)
        s2 = compute_score(l2, self.HOUSE_PROFILE)
        assert s1 > s2, "Larger land should score higher"

    def test_house_cheaper_scores_higher(self):
        from scoring import compute_score
        l1 = _make_listing(price=1500000, size_m2=100, land_m2=1000)
        l2 = _make_listing(price=4500000, size_m2=100, land_m2=1000)
        s1 = compute_score(l1, self.HOUSE_PROFILE)
        s2 = compute_score(l2, self.HOUSE_PROFILE)
        assert s1 > s2, "Cheaper house should score higher"

    def test_score_is_0_to_100(self):
        from scoring import compute_score
        for price in [5000, 20000, 50000]:
            for size in [20, 50, 100]:
                l = _make_listing(price=price, size_m2=size, disposition="2+kk")
                score = compute_score(l, self.RENTAL_PROFILE)
                assert 0 <= score <= 100, f"Score {score} out of range"


# ─── Dedup ──────────────────────────────────────────────────

class TestDedup:
    def test_same_flat_different_sources_deduped(self):
        from dedup import cross_source_dedup
        l1 = _make_listing(id="sreality:1", source="sreality", price=20000,
                           size_m2=50, disposition="2+kk", lat=50.1, lon=14.4)
        l2 = _make_listing(id="bezrealitky:1", source="bezrealitky", price=20000,
                           size_m2=50, disposition="2+kk", lat=50.1001, lon=14.4001)
        result = cross_source_dedup([l1, l2])
        assert len(result) == 1, "Same flat should be deduped"
        assert len(result[0].cross_source) == 1

    def test_different_price_not_deduped(self):
        from dedup import cross_source_dedup
        l1 = _make_listing(id="sreality:1", source="sreality", price=15000,
                           lat=50.1, lon=14.4)
        l2 = _make_listing(id="bezrealitky:1", source="bezrealitky", price=25000,
                           lat=50.1001, lon=14.4001)
        result = cross_source_dedup([l1, l2])
        assert len(result) == 2, "Different prices should not dedup"

    def test_same_source_not_deduped(self):
        from dedup import cross_source_dedup
        l1 = _make_listing(id="sreality:1", source="sreality", price=20000)
        l2 = _make_listing(id="sreality:2", source="sreality", price=20000)
        result = cross_source_dedup([l1, l2])
        assert len(result) == 2, "Same source should not dedup"

    def test_gps_far_apart_not_deduped(self):
        from dedup import cross_source_dedup
        l1 = _make_listing(id="sreality:1", source="sreality", price=20000,
                           lat=50.1, lon=14.4)
        l2 = _make_listing(id="bezrealitky:1", source="bezrealitky", price=20000,
                           lat=50.2, lon=14.5)  # ~12km away
        result = cross_source_dedup([l1, l2])
        assert len(result) == 2, "GPS far apart should not dedup"

    def test_empty_list(self):
        from dedup import cross_source_dedup
        assert cross_source_dedup([]) == []

    def test_single_listing(self):
        from dedup import cross_source_dedup
        l = _make_listing()
        assert cross_source_dedup([l]) == [l]


# ─── Tram Enrichment ────────────────────────────────────────

class TestTramEnrichment:
    def test_adds_nearest_stop(self):
        from metro import enrich_tram
        l = _make_listing(lat=50.1017, lon=14.4330)
        enrich_tram(l)
        assert l.nearest_stop is not None
        assert "tram" in l.nearest_stop
        assert l.stop_distance_m is not None
        assert l.stop_distance_m >= 0

    def test_skips_without_gps(self):
        from metro import enrich_tram
        l = _make_listing()
        enrich_tram(l)
        assert l.nearest_stop is None

    def test_distance_reasonable(self):
        from metro import enrich_tram
        # Right at Vltavska stop
        l = _make_listing(lat=50.09907, lon=14.438273)
        enrich_tram(l)
        assert l.stop_distance_m < 50, f"Should be very close to stop, got {l.stop_distance_m}m"

    def test_stop_includes_line_numbers(self):
        from metro import enrich_tram
        l = _make_listing(lat=50.09907, lon=14.438273)
        enrich_tram(l)
        assert "tram" in l.nearest_stop
        # Should have at least one line number
        import re
        assert re.search(r"tram \d", l.nearest_stop)


# ─── DB ─────────────────────────────────────────────────────

class TestDB:
    PROFILE = "test_profile"

    def setup_method(self):
        import db
        path = db._db_path(self.PROFILE)
        if os.path.exists(path):
            os.unlink(path)

    def teardown_method(self):
        import db
        path = db._db_path(self.PROFILE)
        if os.path.exists(path):
            os.unlink(path)
        lock = db._lock_path(self.PROFILE)
        if os.path.exists(lock):
            os.unlink(lock)

    def test_empty_db_returns_empty(self):
        import db
        assert db.get_seen(self.PROFILE) == {}

    def test_mark_seen_persists(self):
        import db
        l = _make_listing(id="test:1")
        db.mark_seen(self.PROFILE, [l])
        seen = db.get_seen(self.PROFILE)
        assert "test:1" in seen
        assert seen["test:1"]["price"] == 20000
        assert seen["test:1"]["title"] == "Test"

    def test_separate_profiles_isolated(self):
        import db
        l1 = _make_listing(id="test:1")
        l2 = _make_listing(id="test:2")
        db.mark_seen("profile_a", [l1])
        db.mark_seen("profile_b", [l2])
        assert "test:1" in db.get_seen("profile_a")
        assert "test:1" not in db.get_seen("profile_b")
        assert "test:2" in db.get_seen("profile_b")
        assert "test:2" not in db.get_seen("profile_a")
        # Cleanup (both json and lock files)
        for p in ["profile_a", "profile_b"]:
            for path in [db._db_path(p), db._lock_path(p)]:
                if os.path.exists(path):
                    os.unlink(path)

    def test_price_drop_detection(self):
        import db
        l = _make_listing(id="test:1", price=25000)
        db.mark_seen(self.PROFILE, [l])
        # Same listing, lower price
        l2 = _make_listing(id="test:1", price=22000)
        drops = db.update_prices(self.PROFILE, [l2])
        assert len(drops) == 1
        assert drops[0][1] == 25000  # old price

    def test_no_false_price_drop(self):
        import db
        l = _make_listing(id="test:1", price=20000)
        db.mark_seen(self.PROFILE, [l])
        l2 = _make_listing(id="test:1", price=20000)  # Same price
        drops = db.update_prices(self.PROFILE, [l2])
        assert len(drops) == 0

    def test_corrupt_json_handled(self):
        import db
        path = db._db_path(self.PROFILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("{broken json")
        seen = db.get_seen(self.PROFILE)
        assert seen == {}, "Corrupt JSON should return empty dict"
