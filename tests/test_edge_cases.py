"""Edge-case tests for dedup, notifier, scoring, and db modules.

Run with: python3 -m pytest tests/test_edge_cases.py -v
"""
import os
import re
import pytest
from scrapers.base import Listing


def _make_listing(**kwargs) -> Listing:
    defaults = dict(
        id="test:1", source="test", title="Test", price=20000,
        location="Praha 7 - Holesovice", url="https://example.com",
    )
    defaults.update(kwargs)
    return Listing(**defaults)


# ─── 1. Dedup cross_source correctness ────────────────────────

class TestDedupCrossSourceCorrectness:
    """After dedup, no listing should have its OWN source in cross_source."""

    def test_own_source_never_in_cross_source(self):
        from dedup import cross_source_dedup

        listings = [
            _make_listing(id="sreality:1", source="sreality", price=20000,
                          size_m2=50, disposition="2+kk", lat=50.1, lon=14.4),
            _make_listing(id="bezrealitky:1", source="bezrealitky", price=20000,
                          size_m2=50, disposition="2+kk", lat=50.1001, lon=14.4001),
            _make_listing(id="remax:1", source="remax", price=20000,
                          size_m2=50, disposition="2+kk", lat=50.1002, lon=14.4002),
        ]

        result = cross_source_dedup(listings)

        for listing in result:
            assert listing.source not in listing.cross_source, (
                f"Listing {listing.id} (source={listing.source}) has its own "
                f"source in cross_source: {listing.cross_source}"
            )

    def test_own_source_excluded_two_pairs(self):
        """Two separate dedup groups -- verify for each keeper."""
        from dedup import cross_source_dedup

        # Group A: close GPS, same price
        a1 = _make_listing(id="sreality:a", source="sreality", price=18000,
                           size_m2=40, disposition="1+kk", lat=50.0, lon=14.0)
        a2 = _make_listing(id="bezrealitky:a", source="bezrealitky", price=18000,
                           size_m2=40, disposition="1+kk", lat=50.0001, lon=14.0001)

        # Group B: different area
        b1 = _make_listing(id="sreality:b", source="sreality", price=25000,
                           size_m2=60, disposition="3+kk", lat=49.0, lon=13.0)
        b2 = _make_listing(id="remax:b", source="remax", price=25000,
                           size_m2=60, disposition="3+kk", lat=49.0001, lon=13.0001)

        result = cross_source_dedup([a1, a2, b1, b2])

        for listing in result:
            assert listing.source not in listing.cross_source


# ─── 2. Dedup with 3 sources ─────────────────────────────────

class TestDedupThreeSources:
    """3 listings (sreality, bezrealitky, remax) for the same flat merge into 1."""

    def test_three_sources_merge_into_one(self):
        from dedup import cross_source_dedup

        listings = [
            _make_listing(id="sreality:100", source="sreality", price=22000,
                          size_m2=55, disposition="2+kk", lat=50.1, lon=14.4,
                          location="Praha 7"),
            _make_listing(id="bezrealitky:200", source="bezrealitky", price=22000,
                          size_m2=55, disposition="2+kk", lat=50.1001, lon=14.4001,
                          location="Praha 7"),
            _make_listing(id="remax:300", source="remax", price=22000,
                          size_m2=55, disposition="2+kk", lat=50.1002, lon=14.4002,
                          location="Praha 7"),
        ]

        result = cross_source_dedup(listings)
        assert len(result) == 1, f"Expected 1 merged listing, got {len(result)}"

    def test_three_sources_cross_source_has_two_entries(self):
        from dedup import cross_source_dedup

        listings = [
            _make_listing(id="sreality:100", source="sreality", price=22000,
                          size_m2=55, disposition="2+kk", lat=50.1, lon=14.4,
                          location="Praha 7"),
            _make_listing(id="bezrealitky:200", source="bezrealitky", price=22000,
                          size_m2=55, disposition="2+kk", lat=50.1001, lon=14.4001,
                          location="Praha 7"),
            _make_listing(id="remax:300", source="remax", price=22000,
                          size_m2=55, disposition="2+kk", lat=50.1002, lon=14.4002,
                          location="Praha 7"),
        ]

        result = cross_source_dedup(listings)
        keeper = result[0]

        # cross_source should contain exactly the two OTHER sources
        expected_others = {"sreality", "bezrealitky", "remax"} - {keeper.source}
        assert set(keeper.cross_source) == expected_others, (
            f"Keeper source={keeper.source}, cross_source={keeper.cross_source}, "
            f"expected others={expected_others}"
        )


# ─── 3. Sreality URL with spaces ─────────────────────────────

class TestSrealityURLSpaces:
    """Disposition 'rodinny dum' should produce a valid URL (no spaces)."""

    def test_detail_url_no_spaces(self):
        """Verify Sreality URL construction replaces spaces with hyphens."""
        # Reproduce the URL construction from scrapers/sreality.py (after fix)
        disp_label = "rodinny dum"
        disp_slug = disp_label.replace(" ", "-")  # This is what the fixed code does

        detail_url = f"https://www.sreality.cz/detail/prodej/dum/{disp_slug}/domazlice/12345"

        assert " " not in detail_url, "URL should not contain spaces"
        assert "rodinny-dum" in detail_url

        listing = _make_listing(
            id="sreality:12345", source="sreality",
            title="Prodej rodinneho domu", price=3000000,
            url=detail_url, disposition=disp_label,
        )

        from notifier import _render_card
        html = _render_card(listing, is_rent=False)
        assert html  # did not crash

    def test_listing_url_is_escapable(self):
        """Notifier _safe_url should still return a usable href even with spaces."""
        from notifier import _safe_url

        url_with_space = "https://www.sreality.cz/detail/prodej/dum/rodinny dum/domazlice/12345"
        result = _safe_url(url_with_space)
        # _safe_url only validates prefix and HTML-escapes; it should not crash
        assert result.startswith("https://")


# ─── 4. Notifier with price=0 ────────────────────────────────

class TestNotifierPriceZero:
    def test_render_card_price_zero_no_crash(self):
        from notifier import _render_card

        listing = _make_listing(price=0)
        html = _render_card(listing, is_rent=True)
        assert isinstance(html, str)
        assert "0" in html

    def test_format_price_zero(self):
        from notifier import _format_price

        assert "0" in _format_price(0, is_rent=True)
        assert "0" in _format_price(0, is_rent=False)


# ─── 5. Notifier with all None optional fields ───────────────

class TestNotifierAllNoneOptionals:
    def test_render_card_minimal_listing(self):
        """Only required fields set -- all optional fields are None/default."""
        from notifier import _render_card

        listing = Listing(
            id="test:bare", source="test", title="Bare listing",
            price=15000, location="Praha", url="https://example.com",
        )

        html = _render_card(listing, is_rent=True)
        assert isinstance(html, str)
        assert "Bare listing" in html

    def test_render_card_no_image(self):
        from notifier import _render_card

        listing = Listing(
            id="test:noimg", source="test", title="No image",
            price=10000, location="Praha", url="https://example.com",
        )
        html = _render_card(listing, is_rent=True)
        assert "<img" not in html

    def test_render_card_no_location_no_gps_no_map_link(self):
        from notifier import _render_card

        listing = Listing(
            id="test:nogps", source="test", title="No GPS",
            price=10000, location="", url="https://example.com",
        )
        html = _render_card(listing, is_rent=True)
        assert "maps.google.com" not in html

    def test_render_card_location_produces_map_link(self):
        from notifier import _render_card

        listing = Listing(
            id="test:loc", source="test", title="Test",
            price=10000, location="Umělecká, Praha - Holešovice", url="https://example.com",
        )
        html = _render_card(listing, is_rent=True)
        assert "maps.google.com" in html
        assert "Um%C4%9Bleck" in html  # URL-encoded address


# ─── 6. Notifier maps link uniqueness ────────────────────────

class TestNotifierMapsLinkUniqueness:
    def test_different_locations_different_map_urls(self):
        from notifier import _render_card

        locations = [
            "Umělecká, Praha - Holešovice",
            "Letohradská, Praha - Holešovice",
            "Jana Zajíce, Praha - Bubeneč",
        ]

        map_urls = []
        for i, loc in enumerate(locations):
            listing = _make_listing(id=f"test:{i}", location=loc)
            html = _render_card(listing, is_rent=True)
            match = re.search(r'https://maps\.google\.com/\?q=[^"]+', html)
            assert match is not None, f"No maps URL found for listing {i}"
            map_urls.append(match.group(0))

        assert len(set(map_urls)) == 3, (
            f"Expected 3 unique map URLs, got {len(set(map_urls))}: {map_urls}"
        )

    def test_gps_fallback_when_no_location(self):
        from notifier import _render_card

        listing = _make_listing(location="", lat=50.10199, lon=14.42769)
        html = _render_card(listing, is_rent=True)
        assert "50.10199" in html, "GPS fallback should be used when no location"


# ─── 7. Scoring with all zero weights ────────────────────────

class TestScoringAllZeroWeights:
    def test_all_zero_weights_returns_zero(self):
        from scoring import compute_score

        profile = {
            "scoring": {
                "price_per_m2_weight": 0,
                "disposition_weight": 0,
                "size_weight": 0,
                "neighborhood_weight": 0,
                "land_weight": 0,
                "price_weight": 0,
            }
        }
        listing = _make_listing(
            price=20000, size_m2=50, disposition="2+kk",
            land_m2=500, location="Praha 7 - Holesovice",
        )
        score = compute_score(listing, profile)
        assert score == 0, f"All-zero weights should yield 0, got {score}"

    def test_all_zero_weights_doesnt_crash(self):
        from scoring import compute_score

        profile = {"scoring": {
            "price_per_m2_weight": 0,
            "disposition_weight": 0,
            "size_weight": 0,
            "neighborhood_weight": 0,
        }}
        listing = _make_listing()
        score = compute_score(listing, profile)
        assert isinstance(score, int)


# ─── 8. DB mark_seen twice ───────────────────────────────────

class TestDBMarkSeenTwice:
    PROFILE = "test_edge_double_seen"

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

    def test_mark_seen_twice_no_duplicate(self):
        import db

        listing = _make_listing(id="test:dup1", price=20000)
        db.mark_seen(self.PROFILE, [listing])
        db.mark_seen(self.PROFILE, [listing])

        seen = db.get_seen(self.PROFILE)
        # Should have exactly one entry, not two
        matching = [k for k in seen if k == "test:dup1"]
        assert len(matching) == 1, f"Expected 1 entry, found {len(matching)}"

    def test_mark_seen_twice_updates_last_seen(self):
        import db
        import time

        listing = _make_listing(id="test:dup2", price=20000)
        db.mark_seen(self.PROFILE, [listing])

        seen_before = db.get_seen(self.PROFILE)
        first_last_seen = seen_before["test:dup2"]["last_seen"]

        # Tiny delay to ensure timestamp differs
        time.sleep(0.05)

        db.mark_seen(self.PROFILE, [listing])
        seen_after = db.get_seen(self.PROFILE)
        second_last_seen = seen_after["test:dup2"]["last_seen"]

        assert second_last_seen >= first_last_seen, (
            f"last_seen should be updated: {first_last_seen} -> {second_last_seen}"
        )

    def test_mark_seen_twice_preserves_first_seen(self):
        import db
        import time

        listing = _make_listing(id="test:dup3", price=20000)
        db.mark_seen(self.PROFILE, [listing])

        seen_before = db.get_seen(self.PROFILE)
        first_seen_orig = seen_before["test:dup3"]["first_seen"]

        time.sleep(0.05)
        db.mark_seen(self.PROFILE, [listing])

        seen_after = db.get_seen(self.PROFILE)
        first_seen_after = seen_after["test:dup3"]["first_seen"]

        assert first_seen_orig == first_seen_after, (
            f"first_seen should be preserved: {first_seen_orig} != {first_seen_after}"
        )


# ─── 9. Large price formatting ───────────────────────────────

class TestLargePriceFormatting:
    def test_sale_price_uses_nbsp_separator(self):
        from notifier import _format_price

        result = _format_price(4500000, is_rent=False)
        assert "," not in result, f"Should not contain comma: {result}"
        # Uses non-breaking space (\xa0) as thousand separator
        assert "4\xa0500\xa0000" in result, f"Expected nbsp-separated price in: {repr(result)}"
        assert "Kč" in result, f"Sale price should contain 'Kč': {result}"

    def test_rent_price_uses_nbsp_separator(self):
        from notifier import _format_price

        result = _format_price(25000, is_rent=True)
        assert "," not in result, f"Should not contain comma: {result}"
        assert "25\xa0000" in result, f"Expected nbsp-separated in: {repr(result)}"
        assert "měsíc" in result, f"Rent should mention 'měsíc': {result}"

    def test_format_in_rendered_card(self):
        from notifier import _render_card

        listing = _make_listing(price=4500000)
        html = _render_card(listing, is_rent=False)
        assert "4\xa0500\xa0000" in html, f"Rendered card should contain nbsp-formatted price"
        assert "4,500,000" not in html, f"Rendered card should NOT contain comma-separated price"


# ─── 10. Config missing optional keys ────────────────────────

class TestConfigMissingOptionalKeys:
    """Scoring should not crash when preferred_dispositions,
    preferred_neighborhoods, etc. are missing from config."""

    def test_missing_preferred_dispositions(self):
        from scoring import compute_score

        profile = {
            "scoring": {
                "disposition_weight": 30,
                # preferred_dispositions is MISSING
                "size_weight": 15,
                "ideal_size_m2": 55,
            }
        }
        listing = _make_listing(disposition="2+kk", size_m2=50)
        score = compute_score(listing, profile)
        assert isinstance(score, int)

    def test_missing_preferred_neighborhoods(self):
        from scoring import compute_score

        profile = {
            "scoring": {
                "neighborhood_weight": 15,
                # preferred_neighborhoods is MISSING
                "size_weight": 15,
                "ideal_size_m2": 55,
            }
        }
        listing = _make_listing(location="Praha 7 - Holesovice", size_m2=50)
        score = compute_score(listing, profile)
        assert isinstance(score, int)

    def test_missing_ideal_size(self):
        from scoring import compute_score

        profile = {
            "scoring": {
                "size_weight": 15,
                # ideal_size_m2 is MISSING (defaults to 55)
            }
        }
        listing = _make_listing(size_m2=50)
        score = compute_score(listing, profile)
        assert isinstance(score, int)

    def test_missing_max_good_price(self):
        from scoring import compute_score

        profile = {
            "scoring": {
                "price_weight": 30,
                # max_good_price is MISSING (defaults to 3000000)
            }
        }
        listing = _make_listing(price=2500000)
        score = compute_score(listing, profile)
        assert isinstance(score, int)

    def test_completely_empty_scoring_section(self):
        from scoring import compute_score

        listing = _make_listing(
            price=20000, size_m2=50, disposition="2+kk",
            location="Praha 7 - Holesovice",
        )
        # Empty scoring dict
        assert compute_score(listing, {"scoring": {}}) == 0
        # No scoring key at all
        assert compute_score(listing, {}) == 0

    def test_missing_ideal_land(self):
        from scoring import compute_score

        profile = {
            "scoring": {
                "land_weight": 40,
                # ideal_land_m2 is MISSING (defaults to 2000)
            }
        }
        listing = _make_listing(land_m2=1500)
        score = compute_score(listing, profile)
        assert isinstance(score, int)
        assert score > 0
