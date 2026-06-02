import sys
from types import ModuleType

import pandas as pd

streamlit_stub = ModuleType("streamlit")
streamlit_stub.secrets = {}
sys.modules.setdefault("streamlit", streamlit_stub)

import matomo


def test_get_sessions_delivered_only_counts_real_deliver_visits(monkeypatch) -> None:
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
        [{"bundle_id": "b1", "session_id": "s1", "user_id": "u1"}],
        columns=["bundle_id", "session_id", "user_id"],
    )
    pd.testing.assert_frame_equal(result, expected)


def test_get_sessions_delivered_returns_empty_frame_for_non_list_response(monkeypatch) -> None:
    monkeypatch.setattr(matomo, "matomo_get", lambda params: {"error": "bad response"})

    result = matomo.get_sessions_delivered("2026-01-01,2026-01-31")

    assert result.empty
    assert list(result.columns) == ["bundle_id", "session_id", "user_id"]
