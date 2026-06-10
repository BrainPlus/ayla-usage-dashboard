import importlib
import sys
from types import ModuleType

import pandas as pd

import database


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def _streamlit_stub() -> ModuleType:
    stub = ModuleType("streamlit")
    stub.secrets = {}
    stub.session_state = {}
    stub.sidebar = _Context()
    stub.cache_data = lambda **kwargs: (lambda f: f)
    stub.cache_resource = lambda f: f  # passthrough for @st.cache_resource (no-arg form)
    stub.set_page_config = lambda **kwargs: None
    stub.title = lambda *args, **kwargs: None
    stub.selectbox = lambda label, options, **kwargs: options[0]
    stub.markdown = lambda *args, **kwargs: None
    stub.date_input = lambda label, value, **kwargs: value
    stub.button = lambda *args, **kwargs: False
    stub.caption = lambda *args, **kwargs: None
    stub.tabs = lambda names: [_Context() for _ in names]
    stub.info = lambda *args, **kwargs: None
    return stub


def test_cached_activity_catalogue_returns_empty_when_squidex_secrets_are_missing(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "streamlit", _streamlit_stub())
    monkeypatch.setattr(
        database,
        "get_organisations",
        lambda region: pd.DataFrame(columns=["organisation_id", "organisation_name"]),
    )
    sys.modules.pop("app", None)

    app = importlib.import_module("app")

    assert app._cached_activity_catalogue() == {}


def test_cached_activity_usage_reloads_stale_matomo_module(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "streamlit", _streamlit_stub())
    monkeypatch.setattr(
        database,
        "get_organisations",
        lambda region: pd.DataFrame(columns=["organisation_id", "organisation_name"]),
    )
    sys.modules.pop("app", None)

    app = importlib.import_module("app")
    stale_matomo = ModuleType("matomo")
    fresh_matomo = ModuleType("matomo")
    fresh_matomo.get_activity_usage_by_id = (
        lambda date_range, allowed_user_ids=None: pd.DataFrame(
            [{"activity_id": f"usage:{date_range}", "completion_count": 1}]
        )
    )

    monkeypatch.setattr(app, "matomo", stale_matomo)
    monkeypatch.setattr(app.importlib, "reload", lambda module: fresh_matomo)

    result = app._cached_activity_usage(
        "2026-01-01,2026-01-31", "eu", 196, frozenset({"u1"})
    )
    assert result.to_dict("records") == [
        {
            "activity_id": "usage:2026-01-01,2026-01-31",
            "completion_count": 1,
        }
    ]
    assert app.matomo is fresh_matomo


def test_cached_activity_usage_reloads_stale_one_argument_function(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "streamlit", _streamlit_stub())
    monkeypatch.setattr(
        database,
        "get_organisations",
        lambda region: pd.DataFrame(columns=["organisation_id", "organisation_name"]),
    )
    sys.modules.pop("app", None)

    app = importlib.import_module("app")
    stale_matomo = ModuleType("matomo")
    stale_matomo.get_activity_usage_by_id = lambda date_range: pd.DataFrame()
    fresh_matomo = ModuleType("matomo")
    captured = {}

    def get_activity_usage_by_id(date_range, allowed_user_ids=None):
        captured["allowed_user_ids"] = allowed_user_ids
        return pd.DataFrame([{"activity_id": "a1", "completion_count": 1}])

    fresh_matomo.get_activity_usage_by_id = get_activity_usage_by_id
    monkeypatch.setattr(app, "matomo", stale_matomo)
    monkeypatch.setattr(app.importlib, "reload", lambda module: fresh_matomo)

    result = app._cached_activity_usage(
        "2026-01-01,2026-01-31", "eu", 196, frozenset({"u1"})
    )

    assert captured["allowed_user_ids"] == frozenset({"u1"})
    assert result.to_dict("records") == [
        {"activity_id": "a1", "completion_count": 1}
    ]
    assert app.matomo is fresh_matomo


def test_cached_login_form_outcomes_reloads_stale_matomo_module(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "streamlit", _streamlit_stub())
    monkeypatch.setattr(
        database,
        "get_organisations",
        lambda region: pd.DataFrame(columns=["organisation_id", "organisation_name"]),
    )
    sys.modules.pop("app", None)

    app = importlib.import_module("app")
    stale_matomo = ModuleType("matomo")
    fresh_matomo = ModuleType("matomo")
    expected = {"attempts": 2, "successes": 1, "failures": 1}
    fresh_matomo.get_login_form_outcomes = (
        lambda date_range, allowed_user_ids: expected
    )

    monkeypatch.setattr(app, "matomo", stale_matomo)
    monkeypatch.setattr(app.importlib, "reload", lambda module: fresh_matomo)

    result = app._cached_login_form_outcomes(
        "2026-01-01,2026-01-31", "eu", frozenset({"u1"})
    )

    assert result is expected
    assert app.matomo is fresh_matomo


def test_global_summary_supports_stale_two_argument_merger_module(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "streamlit", _streamlit_stub())
    monkeypatch.setattr(
        database,
        "get_organisations",
        lambda region: pd.DataFrame(columns=["organisation_id", "organisation_name"]),
    )
    sys.modules.pop("app", None)

    app = importlib.import_module("app")
    stale_merger = ModuleType("merger")
    stale_merger.build_global_summary = (
        lambda org_summary, bundle_counts: {
            "overall_groups_avg_rating": 3.0,
            "overall_therapists_avg_rating": 3.0,
        }
    )
    monkeypatch.setattr(app, "merger", stale_merger)

    ratings = app.pd.DataFrame(
        [
            {"target": "groups", "avg_rating": 1.0, "total_responses": 1},
            {"target": "groups", "avg_rating": 5.0, "total_responses": 9},
            {"target": "therapists", "avg_rating": 4.0, "total_responses": 2},
        ]
    )
    result = app._build_global_summary("orgs", "bundles", ratings)

    assert result["overall_groups_avg_rating"] == 4.6
    assert result["overall_therapists_avg_rating"] == 4.0
