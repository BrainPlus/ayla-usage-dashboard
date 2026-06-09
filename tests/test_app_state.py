"""Tests for the session-state invalidation guard in app.py."""
import pytest


def _should_clear(fetched_region, fetched_date_range, region, date_range):
    """Mirrors the invalidation condition in app.py."""
    return fetched_region != region or fetched_date_range != date_range


@pytest.mark.parametrize(
    "fetched_region,fetched_date_range,region,date_range,expected",
    [
        # Matching — no clear
        ("UK", "2024-01-01,2024-12-31", "UK", "2024-01-01,2024-12-31", False),
        # Region changed
        ("UK", "2024-01-01,2024-12-31", "EU", "2024-01-01,2024-12-31", True),
        # Date range changed
        ("UK", "2024-01-01,2024-06-30", "UK", "2024-01-01,2024-12-31", True),
        # Both None (fresh / upgraded session) — must clear stale data
        (None, None, "UK", "2024-01-01,2024-12-31", True),
        # Only one key missing (partial upgrade)
        (None, "2024-01-01,2024-12-31", "UK", "2024-01-01,2024-12-31", True),
        ("UK", None, "UK", "2024-01-01,2024-12-31", True),
    ],
)
def test_should_clear(fetched_region, fetched_date_range, region, date_range, expected):
    assert _should_clear(fetched_region, fetched_date_range, region, date_range) == expected
