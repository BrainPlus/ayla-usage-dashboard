import sys
from types import ModuleType

import pandas as pd
import pytest
import requests

streamlit_stub = ModuleType("streamlit")
streamlit_stub.secrets = {}
sys.modules.setdefault("streamlit", streamlit_stub)

import matomo


def test_full_action_live_visit_page_size_is_bounded() -> None:
    assert matomo.LIVE_VISIT_PAGE_SIZE <= 500


def test_selected_period_metrics_reuse_supplied_live_visits(monkeypatch) -> None:
    visits = [
        {
            "idVisit": "v1",
            "userId": "u1",
            "serverDate": "2026-06-01",
            "visitDuration": 120,
            "actionDetails": [],
        }
    ]
    monkeypatch.setattr(
        matomo,
        "_fetch_all_live_visits",
        lambda *args, **kwargs: pytest.fail("shared visits should prevent another fetch"),
    )

    matomo.get_delivery_funnel_instances("last90", visits=visits)
    matomo.get_activity_completions_per_user("last90", visits=visits)
    matomo.get_activity_usage_by_id("last90", visits=visits)
    matomo.get_step_completion_depth("last90", visits=visits)
    matomo.get_visit_durations("last90", visits=visits)
    matomo.get_visit_dates("last90", visits=visits)
    matomo.get_talking_point_engagement("last90", visits=visits)
    matomo.get_media_usage("last90", visits=visits)
    matomo.get_engagement_events("last90", visits=visits)


def test_streamed_delivery_funnel_processes_bounded_pages_without_fetch_all(
    monkeypatch,
) -> None:
    def completion(visit_id: str) -> dict:
        return {
            "idVisit": visit_id,
            "userId": "u1",
            "actionDetails": [
                {
                    "type": "event",
                    "eventAction": "Session Complete",
                    "dimension10": "false",
                    "dimension14": "b1",
                    "dimension5": "s1",
                }
            ],
        }

    monkeypatch.setattr(
        matomo,
        "_iter_live_visit_pages",
        lambda *args, **kwargs: iter([[completion("v1")], [completion("v2")]]),
    )
    monkeypatch.setattr(
        matomo,
        "_fetch_all_live_visits",
        lambda *args, **kwargs: pytest.fail("streamed history must not fetch all visits"),
    )

    result = matomo.get_delivery_funnel_instances_streamed("last365")

    assert list(result["visit_id"]) == ["v1", "v2"]
    assert result["completed_session"].tolist() == [True, True]


def test_matomo_get_retries_transient_timeout(monkeypatch) -> None:
    response = type(
        "Response",
        (),
        {
            "raise_for_status": lambda self: None,
            "json": lambda self: [{"ok": True}],
        },
    )()
    calls = []
    sleeps = []

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        if len(calls) == 1:
            raise requests.exceptions.ReadTimeout("slow response")
        return response

    matomo.st.secrets = {
        "matomo_url": "https://example.test",
        "matomo_site_id": "4",
        "matomo_token": "secret",
    }
    monkeypatch.setattr(matomo.requests, "get", fake_get)
    monkeypatch.setattr(matomo.time, "sleep", sleeps.append)

    result = matomo.matomo_get({"method": "Example.get"})

    assert result == [{"ok": True}]
    assert len(calls) == 2
    assert calls[0][2] == (10, 120)
    assert sleeps == [1]


def test_matomo_get_identifies_method_after_transient_retries(monkeypatch) -> None:
    matomo.st.secrets = {
        "matomo_url": "https://example.test",
        "matomo_site_id": "4",
        "matomo_token": "secret",
    }
    monkeypatch.setattr(
        matomo.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            requests.exceptions.ReadTimeout("slow response")
        ),
    )
    monkeypatch.setattr(matomo.time, "sleep", lambda seconds: None)

    with pytest.raises(
        requests.exceptions.ReadTimeout,
        match=r"Matomo Example\.get failed after 3 attempts",
    ):
        matomo.matomo_get({"method": "Example.get"})


def test_active_delivery_allowlist_matches_issue_28() -> None:
    assert matomo._ACTIVE_DELIVERY_EVENTS == frozenset(
        {
            "Step Complete",
            "Activity Complete",
            "Reality Orientation Date Set",
            "Reality Orientation Time Set",
            "Reality Orientation Song Set",
            "Reality Orientation Group Name Set",
            "Reality Orientation YouTube Playlist Changed",
            "Main Activity Card Start Click",
        }
    )


@pytest.mark.parametrize(
    "function_name",
    [
        "get_visit_durations",
        "get_completed_sessions",
        "get_delivery_funnel_instances",
        "get_activity_completions_per_user",
        "get_activity_usage_by_id",
        "get_step_completion_depth",
        "get_visit_dates",
    ],
)
@pytest.mark.parametrize("org_id", [196, None, "unassigned"])
def test_live_visit_queries_apply_only_required_source_segments(
    monkeypatch, function_name, org_id
) -> None:
    captured = {}

    def fake_fetch(params, page_size=5000):
        captured["params"] = params
        return []

    monkeypatch.setattr(matomo, "_fetch_all_live_visits", fake_fetch)

    getattr(matomo, function_name)("2026-01-01,2026-01-31", org_id=org_id)

    assert "segment" not in captured["params"]


def test_get_completed_sessions_counts_deliver_mode_session_complete_per_visit(
    monkeypatch,
) -> None:
    def fake_matomo_get(params: dict) -> list[dict]:
        return [
            {
                "idVisit": "v1",
                "userId": "u1",
                "visitDuration": matomo.REAL_SESSION_MIN_DURATION_SECONDS + 1,
                "actionDetails": [
                    {
                        "type": "event",
                        "eventAction": "Session Complete",
                        "dimension10": "false",
                        "dimension14": "b1",
                        "dimension5": "s1",
                    },
                    {
                        "type": "event",
                        "eventAction": "Session Complete",
                        "dimension10": "false",
                        "dimension14": "b1",
                        "dimension5": "s1",
                    },
                    {
                        "type": "event",
                        "eventAction": "Session Complete",
                        "dimension10": "true",
                        "dimension14": "b2",
                        "dimension5": "s2",
                    },
                    {
                        "type": "event",
                        "eventAction": "Session Start",
                        "dimension10": "false",
                        "dimension14": "b3",
                        "dimension5": "s3",
                    },
                ],
            },
            {
                "idVisit": "v2",
                "userId": "u1",
                "visitDuration": matomo.REAL_SESSION_MIN_DURATION_SECONDS,
                "actionDetails": [
                    {
                        "type": "event",
                        "eventAction": "Session Complete",
                        "dimension10": "false",
                        "dimension14": "b1",
                        "dimension5": "s1",
                    },
                ],
            },
        ]

    monkeypatch.setattr(matomo, "matomo_get", fake_matomo_get)

    result = matomo.get_completed_sessions("2026-01-01,2026-01-31")

    expected = pd.DataFrame(
        [
            {
                "visit_id": "v1",
                "bundle_id": "b1",
                "session_id": "s1",
                "user_id": "u1",
            },
            {
                "visit_id": "v2",
                "bundle_id": "b1",
                "session_id": "s1",
                "user_id": "u1",
            },
        ],
        columns=["visit_id", "bundle_id", "session_id", "user_id"],
    )
    pd.testing.assert_frame_equal(result, expected)


def test_get_delivery_funnel_instances_uses_allowlist_and_shared_deduplication_key(
    monkeypatch,
) -> None:
    def event(action, bundle="b1", session="s1", mode="false"):
        result = {
            "type": "event",
            "eventAction": action,
            "dimension14": bundle,
            "dimension5": session,
        }
        if mode is not None:
            result["dimension10"] = mode
        return result

    visits = [
        {
            "idVisit": "v1",
            "userId": "u1",
            "actionDetails": [
                event("Prepare/Deliver dialog - Deliver Click", mode=None),
                event("Prepare/Deliver dialog - Deliver Click", mode=None),
                event("Talking Point Expand Click"),
                event("Reality Orientation Date Set"),
                event("Session Complete"),
                event("Session Complete"),
                event("Activity Complete", session="s2"),
                event("Main Activity Card Start Click", session="s3", mode="true"),
                event("Drawer Open", session="s4"),
            ],
        },
        {
            "idVisit": "v2",
            "userId": "u1",
            "actionDetails": [
                event("Prepare/Deliver dialog - Deliver Click", mode=None),
                event("Step Complete"),
            ],
        },
    ]
    monkeypatch.setattr(
        matomo, "_fetch_all_live_visits", lambda params, page_size=5000: visits
    )

    result = matomo.get_delivery_funnel_instances("2026-01-01,2026-01-31")

    assert result.to_dict("records") == [
        {
            "visit_id": "v1",
            "bundle_id": "b1",
            "session_id": "s1",
            "user_id": "u1",
            "deliver_selected": True,
            "active_delivery": True,
            "completed_session": True,
            "completed_session_date": "",
        },
        {
            "visit_id": "v1",
            "bundle_id": "b1",
            "session_id": "s2",
            "user_id": "u1",
            "deliver_selected": False,
            "active_delivery": False,
            "completed_session": False,
            "completed_session_date": "",
        },
        {
            "visit_id": "v2",
            "bundle_id": "b1",
            "session_id": "s1",
            "user_id": "u1",
            "deliver_selected": True,
            "active_delivery": True,
            "completed_session": False,
            "completed_session_date": "",
        },
    ]


def test_delivery_funnel_uses_latest_deduplicated_completion_event_date(
    monkeypatch,
) -> None:
    def completion(timestamp: int, mode: str = "false") -> dict:
        return {
            "type": "event",
            "eventAction": "Session Complete",
            "dimension10": mode,
            "dimension14": "b1",
            "dimension5": "s1",
            "timestamp": timestamp,
        }

    visits = [
        {
            "idVisit": "v1",
            "userId": "u1",
            "actionDetails": [
                completion(1767225600),
                completion(1767312000),
                completion(1767398400, mode="true"),
            ],
        }
    ]
    monkeypatch.setattr(
        matomo, "_fetch_all_live_visits", lambda params, page_size=5000: visits
    )

    result = matomo.get_delivery_funnel_instances("last365")

    assert len(result) == 1
    assert result.iloc[0]["completed_session_date"] == "2026-01-02"


def test_delivery_funnel_completed_stage_matches_completed_sessions(monkeypatch) -> None:
    visits = [
        {
            "idVisit": "v1",
            "userId": "u1",
            "actionDetails": [
                {
                    "type": "event",
                    "eventAction": "Session Complete",
                    "dimension10": "false",
                    "dimension14": "b1",
                    "dimension5": "s1",
                }
            ],
        }
    ]
    monkeypatch.setattr(
        matomo, "_fetch_all_live_visits", lambda params, page_size=5000: visits
    )

    completed = matomo.get_completed_sessions("2026-01-01,2026-01-31")
    funnel = matomo.get_delivery_funnel_instances("2026-01-01,2026-01-31")
    funnel_completed = funnel.loc[
        funnel["completed_session"],
        ["visit_id", "bundle_id", "session_id", "user_id"],
    ].reset_index(drop=True)

    pd.testing.assert_frame_equal(funnel_completed, completed)


def test_get_completed_sessions_raises_for_non_list_response(monkeypatch) -> None:
    import pytest
    monkeypatch.setattr(matomo, "matomo_get", lambda params: {"error": "bad response"})
    with pytest.raises(RuntimeError, match="non-list response"):
        matomo.get_completed_sessions("2026-01-01,2026-01-31")


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
    assert result.iloc[0]["language"] == ""
    assert result.iloc[0]["completion_count"] == 1


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
        {"activity_id": "act-123", "language": "", "completion_count": 1}
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
        {"activity_id": "act-123", "language": "", "completion_count": 2}
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
    assert list(result.columns) == ["activity_id", "language", "completion_count"]


def test_get_activity_usage_by_id_non_list_raises(monkeypatch) -> None:
    """Non-list response raises RuntimeError so the caller sees the API error."""
    import pytest
    monkeypatch.setattr(matomo, "matomo_get", lambda params: {"error": "oops"})
    with pytest.raises(RuntimeError, match="non-list response"):
        matomo.get_activity_usage_by_id("2024-01-01,2024-01-31")


def test_get_step_completion_depth_numbers_unique_steps_in_chronological_order(
    monkeypatch,
) -> None:
    visits = [
        {
            "idVisit": "v1",
            "userId": "u1",
            "actionDetails": [
                {
                    "type": "event",
                    "eventCategory": "Step",
                    "eventAction": "Step Complete",
                    "dimension10": "false",
                    "dimension14": "b1",
                    "dimension5": "s1",
                    "dimension6": "a1",
                    "dimension7": "step-uuid-2",
                    "dimension2": "en-GB",
                    "timestamp": 20,
                },
                {
                    "type": "event",
                    "eventCategory": "Step",
                    "eventAction": "Step Complete",
                    "dimension10": "false",
                    "dimension14": "b1",
                    "dimension5": "s1",
                    "dimension6": "a1",
                    "dimension7": "step-uuid-1",
                    "dimension2": "en-GB",
                    "timestamp": 10,
                },
                {
                    "type": "event",
                    "eventCategory": "Step",
                    "eventAction": "Step Complete",
                    "dimension10": "false",
                    "dimension14": "b1",
                    "dimension5": "s1",
                    "dimension6": "a1",
                    "dimension7": "step-uuid-2",
                    "dimension2": "en-GB",
                    "timestamp": 30,
                },
                {
                    "type": "event",
                    "eventCategory": "Step",
                    "eventAction": "Step Complete",
                    "dimension10": "true",
                    "dimension6": "a1",
                    "dimension7": "step-uuid-3",
                    "timestamp": 40,
                },
            ],
        }
    ]
    monkeypatch.setattr(matomo, "_fetch_all_live_visits", lambda params, page_size: visits)

    result = matomo.get_step_completion_depth(
        "2024-01-01,2024-01-31", frozenset({"u1"})
    )

    assert result.to_dict("records") == [
        {
            "activity_instance_id": "v1|b1|s1|a1",
            "user_id": "u1",
            "activity_id": "a1",
            "language": "en-GB",
            "step_number": 1,
        },
        {
            "activity_instance_id": "v1|b1|s1|a1",
            "user_id": "u1",
            "activity_id": "a1",
            "language": "en-GB",
            "step_number": 2,
        },
    ]


def test_get_step_completion_depth_excludes_users_outside_selected_scope(
    monkeypatch,
) -> None:
    visits = [
        {
            "idVisit": f"v-{user_id}",
            "userId": user_id,
            "actionDetails": [
                {
                    "type": "event",
                    "eventCategory": "Step",
                    "eventAction": "Step Complete",
                    "dimension10": "false",
                    "dimension5": "s1",
                    "dimension6": "a1",
                    "dimension7": "step-uuid-1",
                    "dimension14": "b1",
                }
            ],
        }
        for user_id in ("u1", "u2")
    ]
    monkeypatch.setattr(matomo, "_fetch_all_live_visits", lambda params, page_size: visits)

    result = matomo.get_step_completion_depth(
        "2024-01-01,2024-01-31", frozenset({"u2"})
    )

    assert list(result["user_id"]) == ["u2"]


def test_get_step_completion_depth_skips_incomplete_activity_instances(
    monkeypatch,
) -> None:
    visits = [
        {
            "idVisit": "v1",
            "userId": "u1",
            "actionDetails": [
                {
                    "type": "event",
                    "eventCategory": "Step",
                    "eventAction": "Step Complete",
                    "dimension10": "false",
                    "dimension6": "a1",
                    "dimension7": "step-uuid-1",
                },
                {
                    "type": "event",
                    "eventCategory": "Step",
                    "eventAction": "Step Complete",
                    "dimension10": "false",
                    "dimension5": "s1",
                    "dimension6": "a1",
                    "dimension7": "step-uuid-1",
                },
            ],
        }
    ]
    monkeypatch.setattr(matomo, "_fetch_all_live_visits", lambda params, page_size: visits)

    result = matomo.get_step_completion_depth(
        "2024-01-01,2024-01-31", frozenset({"u1"})
    )

    assert result.empty


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


def test_fetch_all_live_visits_uses_bounded_default_page_size(monkeypatch) -> None:
    captured = {}

    def fake_get(params: dict) -> list:
        captured.update(params)
        return []

    monkeypatch.setattr(matomo, "matomo_get", fake_get)

    matomo._fetch_all_live_visits({"method": "Live.getLastVisitsDetails"})

    assert captured["filter_limit"] == matomo.LIVE_VISIT_PAGE_SIZE


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


# ── get_visit_dates ───────────────────────────────────────────────────────────

def test_get_visit_dates_returns_user_id_and_visit_date(monkeypatch) -> None:
    monkeypatch.setattr(
        matomo,
        "matomo_get",
        lambda params: [
            {"userId": "u1", "serverDate": "2026-06-01"},
            {"userId": "u2", "serverDate": "2026-06-02"},
        ],
    )
    result = matomo.get_visit_dates("2026-06-01,2026-06-02")
    assert list(result.columns) == ["user_id", "visit_date"]
    assert result.to_dict("records") == [
        {"user_id": "u1", "visit_date": "2026-06-01"},
        {"user_id": "u2", "visit_date": "2026-06-02"},
    ]


def test_get_visit_dates_skips_visits_without_user_id(monkeypatch) -> None:
    monkeypatch.setattr(
        matomo,
        "matomo_get",
        lambda params: [
            {"serverDate": "2026-06-01"},           # no userId
            {"userId": "", "serverDate": "2026-06-01"},  # empty userId
            {"userId": "u1", "serverDate": "2026-06-01"},
        ],
    )
    result = matomo.get_visit_dates("2026-06-01,2026-06-01")
    assert len(result) == 1
    assert result.iloc[0]["user_id"] == "u1"


def test_get_visit_dates_skips_visits_without_server_date(monkeypatch) -> None:
    monkeypatch.setattr(
        matomo,
        "matomo_get",
        lambda params: [
            {"userId": "u1"},                        # no serverDate key
            {"userId": "u2", "serverDate": ""},      # empty serverDate
            {"userId": "u3", "serverDate": "2026-06-01"},
        ],
    )
    result = matomo.get_visit_dates("2026-06-01,2026-06-01")
    assert len(result) == 1
    assert result.iloc[0]["user_id"] == "u3"


def test_get_visit_dates_empty_response_returns_empty_frame(monkeypatch) -> None:
    monkeypatch.setattr(matomo, "matomo_get", lambda params: [])
    result = matomo.get_visit_dates("2026-06-01,2026-06-01")
    assert result.empty
    assert list(result.columns) == ["user_id", "visit_date"]


def test_fetch_non_list_later_page_raises(monkeypatch) -> None:
    """Non-list on page 2 raises RuntimeError to prevent silent partial results."""
    import pytest

    def fake_get(params: dict):
        return [{"userId": "u0"}] * 5 if params["filter_offset"] == 0 else {"error": "bad"}

    monkeypatch.setattr(matomo, "matomo_get", fake_get)
    with pytest.raises(RuntimeError, match="non-list response"):
        matomo._fetch_all_live_visits({"method": "Live.getLastVisitsDetails"}, page_size=5)
