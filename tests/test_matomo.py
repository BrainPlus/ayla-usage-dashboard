import sys
from types import ModuleType

import pandas as pd

streamlit_stub = ModuleType("streamlit")
streamlit_stub.secrets = {}
sys.modules.setdefault("streamlit", streamlit_stub)

import matomo


def test_get_sessions_delivered_counts_all_deliver_visits_regardless_of_duration(monkeypatch) -> None:
    def fake_matomo_get(params: dict) -> list[dict]:
        return [
            {
                "userId": "u1",
                "visitDuration": matomo.REAL_SESSION_MIN_DURATION_SECONDS + 1,
                "actionDetails": [
                    {"dimension10": "false", "dimension14": "b1", "dimension5": "s1"},
                    {"dimension10": "false", "dimension14": "b1", "dimension5": "s1"},
                    {"dimension10": "true", "dimension14": "b2", "dimension5": "s2"},
                ],
            },
            {
                "userId": "u2",
                "visitDuration": matomo.REAL_SESSION_MIN_DURATION_SECONDS,
                "actionDetails": [
                    {"dimension10": "false", "dimension14": "b3", "dimension5": "s3"},
                ],
            },
            {
                "userId": "u3",
                "visitDuration": matomo.REAL_SESSION_MIN_DURATION_SECONDS + 1,
                "actionDetails": [
                    {"dimension10": "true", "dimension14": "b4", "dimension5": "s4"},
                ],
            },
        ]

    monkeypatch.setattr(matomo, "matomo_get", fake_matomo_get)

    result = matomo.get_sessions_delivered("2026-01-01,2026-01-31")

    expected = pd.DataFrame(
        [
            {"bundle_id": "b1", "session_id": "s1", "user_id": "u1"},
            {"bundle_id": "b3", "session_id": "s3", "user_id": "u2"},
        ],
        columns=["bundle_id", "session_id", "user_id"],
    )
    pd.testing.assert_frame_equal(result, expected)


def test_get_sessions_delivered_raises_for_non_list_response(monkeypatch) -> None:
    import pytest
    monkeypatch.setattr(matomo, "matomo_get", lambda params: {"error": "bad response"})
    with pytest.raises(RuntimeError, match="non-list response"):
        matomo.get_sessions_delivered("2026-01-01,2026-01-31")


def test_get_activity_usage_by_id_counts_deliver_only(monkeypatch) -> None:
    """Counts Activity Complete events in deliver mode; skips prepare-mode actions."""
    visits = [
        {
            "actionDetails": [
                {
                    "type": "event",
                    "eventCategory": "Activity",
                    "eventAction": "Activity Complete",
                    "dimension10": "false",
                    "dimension6": "act-123",
                },
                {
                    "type": "event",
                    "eventCategory": "Activity",
                    "eventAction": "Activity Complete",
                    "dimension10": "true",  # prepare mode — must be excluded
                    "dimension6": "act-456",
                },
            ]
        }
    ]
    monkeypatch.setattr(matomo, "matomo_get", lambda params: visits)
    result = matomo.get_activity_usage_by_id("2024-01-01,2024-01-31")
    assert len(result) == 1
    assert result.iloc[0]["activity_id"] == "act-123"
    assert result.iloc[0]["completions"] == 1


def test_get_activity_usage_by_id_allowed_user_ids_excludes_other_users(monkeypatch) -> None:
    visits = [
        {
            "userId": "u1",
            "actionDetails": [
                {
                    "type": "event",
                    "eventCategory": "Activity",
                    "eventAction": "Activity Complete",
                    "dimension10": "false",
                    "dimension6": "act-123",
                }
            ],
        },
        {
            "userId": "u2",
            "actionDetails": [
                {
                    "type": "event",
                    "eventCategory": "Activity",
                    "eventAction": "Activity Complete",
                    "dimension10": "false",
                    "dimension6": "act-123",
                },
            ]
        },
    ]
    monkeypatch.setattr(matomo, "matomo_get", lambda params: visits)

    result = matomo.get_activity_usage_by_id(
        "2024-01-01,2024-01-31", frozenset({"u1"})
    )

    assert result.to_dict("records") == [
        {"activity_id": "act-123", "completions": 1}
    ]


def test_get_activity_usage_by_id_without_allowed_users_counts_all(monkeypatch) -> None:
    visits = [
        {
            "userId": user_id,
            "actionDetails": [
                {
                    "type": "event",
                    "eventCategory": "Activity",
                    "eventAction": "Activity Complete",
                    "dimension10": "false",
                    "dimension6": "act-123",
                }
            ],
        }
        for user_id in ("u1", "u2")
    ]
    monkeypatch.setattr(matomo, "matomo_get", lambda params: visits)

    result = matomo.get_activity_usage_by_id("2024-01-01,2024-01-31", None)

    assert result.to_dict("records") == [
        {"activity_id": "act-123", "completions": 2}
    ]


def test_get_activity_usage_by_id_empty_allowed_users_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        matomo,
        "matomo_get",
        lambda params: [{"userId": "u1", "actionDetails": []}],
    )

    result = matomo.get_activity_usage_by_id(
        "2024-01-01,2024-01-31", frozenset()
    )

    assert result.empty
    assert list(result.columns) == ["activity_id", "completions"]


def test_get_activity_usage_by_id_non_list_raises(monkeypatch) -> None:
    """Non-list response raises RuntimeError so the caller sees the API error."""
    import pytest
    monkeypatch.setattr(matomo, "matomo_get", lambda params: {"error": "oops"})
    with pytest.raises(RuntimeError, match="non-list response"):
        matomo.get_activity_usage_by_id("2024-01-01,2024-01-31")


# ── _fetch_all_live_visits pagination ─────────────────────────────────────────

def test_fetch_single_page_less_than_page_size(monkeypatch) -> None:
    """Single page with fewer results than page_size: one API call, all results returned."""
    page = [{"userId": f"u{i}"} for i in range(3)]

    def fake_get(params: dict) -> list:
        assert params["filter_offset"] == 0
        return page

    monkeypatch.setattr(matomo, "matomo_get", fake_get)
    result = matomo._fetch_all_live_visits({"method": "Live.getLastVisitsDetails"}, page_size=5)
    assert len(result) == 3
    assert result[0]["userId"] == "u0"


def test_fetch_multiple_pages_concatenated(monkeypatch) -> None:
    """Three pages: first two full, last partial — all concatenated in order."""
    pages = {
        0:  [{"userId": f"u{i}"} for i in range(5)],
        5:  [{"userId": f"u{i}"} for i in range(5, 10)],
        10: [{"userId": f"u{i}"} for i in range(10, 12)],
    }

    monkeypatch.setattr(matomo, "matomo_get", lambda p: pages[p["filter_offset"]])
    result = matomo._fetch_all_live_visits({"method": "Live.getLastVisitsDetails"}, page_size=5)
    assert len(result) == 12
    assert result[0]["userId"] == "u0"
    assert result[11]["userId"] == "u11"


def test_fetch_exact_page_boundary_triggers_followup(monkeypatch) -> None:
    """Exactly page_size results on page 1 must trigger a second call that returns empty."""
    call_offsets: list[int] = []

    def fake_get(params: dict) -> list:
        call_offsets.append(params["filter_offset"])
        return [{"userId": "u0"}] * 5 if params["filter_offset"] == 0 else []

    monkeypatch.setattr(matomo, "matomo_get", fake_get)
    result = matomo._fetch_all_live_visits({"method": "Live.getLastVisitsDetails"}, page_size=5)
    assert len(result) == 5
    assert call_offsets == [0, 5]  # second call was made to check for more data


def test_fetch_non_list_first_page_raises(monkeypatch) -> None:
    """Non-list on the first page raises RuntimeError — silently returning [] hides API errors."""
    import pytest
    monkeypatch.setattr(matomo, "matomo_get", lambda p: {"error": "no data"})
    with pytest.raises(RuntimeError, match="non-list response"):
        matomo._fetch_all_live_visits({"method": "Live.getLastVisitsDetails"})


def test_fetch_non_list_later_page_raises(monkeypatch) -> None:
    """Non-list on page 2 raises RuntimeError to prevent silent partial results."""
    import pytest

    def fake_get(params: dict):
        return [{"userId": "u0"}] * 5 if params["filter_offset"] == 0 else {"error": "bad"}

    monkeypatch.setattr(matomo, "matomo_get", fake_get)
    with pytest.raises(RuntimeError, match="non-list response"):
        matomo._fetch_all_live_visits({"method": "Live.getLastVisitsDetails"}, page_size=5)
