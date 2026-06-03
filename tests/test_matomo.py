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


def test_get_sessions_delivered_returns_empty_frame_for_non_list_response(monkeypatch) -> None:
    monkeypatch.setattr(matomo, "matomo_get", lambda params: {"error": "bad response"})

    result = matomo.get_sessions_delivered("2026-01-01,2026-01-31")

    assert result.empty
    assert list(result.columns) == ["bundle_id", "session_id", "user_id"]


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
    assert result.iloc[0]["completion_count"] == 1


def test_get_activity_usage_by_id_non_list_returns_empty(monkeypatch) -> None:
    """Non-list response returns empty DataFrame with correct columns."""
    monkeypatch.setattr(matomo, "matomo_get", lambda params: {"error": "oops"})
    result = matomo.get_activity_usage_by_id("2024-01-01,2024-01-31")
    assert result.empty
    assert "activity_id" in result.columns
    assert "completion_count" in result.columns
