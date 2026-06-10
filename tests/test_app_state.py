import importlib
import sys
from datetime import date
from types import ModuleType

import pandas as pd


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def _import_app(monkeypatch):
    streamlit = ModuleType("streamlit")
    streamlit._captions = []
    streamlit.secrets = {}
    streamlit.session_state = {}
    streamlit.sidebar = _Context()
    streamlit.cache_data = lambda **kwargs: (lambda f: f)
    streamlit.cache_resource = lambda f: f
    streamlit.set_page_config = lambda **kwargs: None
    streamlit.title = lambda *args, **kwargs: None
    streamlit.selectbox = lambda label, options, **kwargs: options[0]
    streamlit.markdown = lambda *args, **kwargs: None
    streamlit.date_input = lambda label, value, **kwargs: value
    streamlit.button = lambda *args, **kwargs: False
    streamlit.caption = lambda text, **kwargs: streamlit._captions.append(text)
    streamlit.tabs = lambda names: [_Context() for _ in names]
    streamlit.info = lambda *args, **kwargs: None

    database = ModuleType("database")
    database.get_organisations = lambda region: pd.DataFrame(
        columns=["organisation_id", "organisation_name"]
    )

    monkeypatch.setitem(sys.modules, "streamlit", streamlit)
    monkeypatch.setitem(sys.modules, "database", database)
    sys.modules.pop("app", None)
    return importlib.import_module("app")


def test_should_clear_report(monkeypatch) -> None:
    app = _import_app(monkeypatch)

    assert not app._should_clear_report({}, "eu", None, "range")
    loaded = {
        "global_summary": {},
        "fetched_region": "eu",
        "fetched_org_id": 196,
        "fetched_date_range": "range",
    }
    assert not app._should_clear_report(loaded, "eu", 196, "range")
    assert app._should_clear_report(loaded, "uk", 196, "range")
    assert app._should_clear_report(loaded, "eu", "unassigned", "range")
    assert app._should_clear_report(loaded, "eu", 196, "different-range")
    assert app._should_clear_report({"global_summary": {}}, "eu", None, "range")


def test_database_user_ids_are_normalised_for_raw_aggregate_filters(monkeypatch) -> None:
    app = _import_app(monkeypatch)
    db_users = pd.DataFrame([{"user_id": 1}, {"user_id": "u2"}])

    assert app._database_user_ids(db_users) == frozenset({"1", "u2"})


def test_filter_to_database_users_produces_distinct_regional_results(monkeypatch) -> None:
    app = _import_app(monkeypatch)
    df = pd.DataFrame([{"user_id": "u1"}, {"user_id": "u2"}])

    eu_result = app._filter_to_database_users(df, frozenset({"u1"}))
    uk_result = app._filter_to_database_users(df, frozenset({"u2"}))

    assert eu_result.to_dict("records") == [{"user_id": "u1"}]
    assert uk_result.to_dict("records") == [{"user_id": "u2"}]
    without_user_ids = pd.DataFrame([{"activity_id": "a1"}])
    assert app._filter_to_database_users(
        without_user_ids, frozenset({"u2"})
    ).equals(without_user_ids)


def test_last_login_user_ids(monkeypatch) -> None:
    app = _import_app(monkeypatch)
    db_users = pd.DataFrame([{"user_id": "u1"}, {"user_id": "u2"}])
    logins = pd.DataFrame([{"user_id": "u2"}, {"user_id": "u3"}])

    assert app._last_login_user_ids(db_users, logins, 196) == ["u1", "u2"]
    assert app._last_login_user_ids(db_users, logins, None) == ["u1", "u2", "u3"]


def test_overview_metrics_depend_on_organisation_scope(monkeypatch) -> None:
    app = _import_app(monkeypatch)

    all_org_metric_keys = [metric[0] for metric in app._overview_metrics(None)]
    single_org_metric_keys = [metric[0] for metric in app._overview_metrics(196)]

    assert "total_organisations" in all_org_metric_keys
    assert "total_organisations" not in single_org_metric_keys
    assert set(single_org_metric_keys) == set(all_org_metric_keys) - {
        "total_organisations"
    }


def test_overview_metrics_all_have_help_text(monkeypatch) -> None:
    app = _import_app(monkeypatch)

    assert all(help_text for _, _, help_text in app._overview_metrics(None))


def test_all_report_sections_have_help_text(monkeypatch) -> None:
    app = _import_app(monkeypatch)

    assert set(app._SECTION_HELP) == {
        "overview",
        "logins_by_organisation",
        "monthly_bundle_creations",
        "bundle_filter_breakdown",
        "monthly_average_star_ratings",
        "group_feedback_by_question",
        "therapist_feedback_by_question",
        "activity_usage",
        "daily_visit_activity",
        "by_organisation",
        "by_user",
    }
    assert all(app._SECTION_HELP.values())
    assert "selected date range" in app._SECTION_HELP["activity_usage"]


def test_logins_by_organisation_only_shows_for_all_organisations(monkeypatch) -> None:
    app = _import_app(monkeypatch)

    assert app._show_logins_by_organisation(None)
    assert not app._show_logins_by_organisation(196)
    assert not app._show_logins_by_organisation("unassigned")


def test_user_organisation_filter_only_shows_for_all_organisations(monkeypatch) -> None:
    app = _import_app(monkeypatch)

    assert app._show_user_organisation_filter(None)
    assert not app._show_user_organisation_filter(196)
    assert not app._show_user_organisation_filter("unassigned")


def test_bundle_creation_charts_show_in_scope_specific_tabs(monkeypatch) -> None:
    app = _import_app(monkeypatch)

    assert app._show_global_bundle_creation_chart(None)
    assert not app._show_organisation_bundle_creation_chart(None)

    for org_id in (196, "unassigned"):
        assert not app._show_global_bundle_creation_chart(org_id)
        assert app._show_organisation_bundle_creation_chart(org_id)


def test_monthly_bundle_creation_chart_uses_display_label_and_zero_fills(
    monkeypatch,
) -> None:
    app = _import_app(monkeypatch)
    creations = pd.DataFrame(
        [{"month": "2026-01", "organisation_name": "Org A", "bundles_created": 2}]
    )

    chart = app._monthly_bundle_creation_chart(
        creations, date(2026, 1, 1), date(2026, 2, 28)
    )

    assert chart.to_dict("index") == {
        "2026-01": {"Bundles created": 2},
        "2026-02": {"Bundles created": 0},
    }


def test_bundle_filter_chart_selects_category_and_orders_by_count(monkeypatch) -> None:
    app = _import_app(monkeypatch)
    breakdown = pd.DataFrame(
        [
            {"filter_type": "severity", "filter_value": "mild", "bundle_count": 4},
            {"filter_type": "age", "filter_value": "sixties", "bundle_count": 5},
            {"filter_type": "severity", "filter_value": "Not set", "bundle_count": 2},
        ]
    )

    chart = app._bundle_filter_chart(breakdown, "severity")

    assert chart.to_dict("index") == {
        "mild": {"Bundles": 4},
        "Not set": {"Bundles": 2},
    }


def test_monthly_bundle_creation_summary_reloads_stale_merger_module(
    monkeypatch,
) -> None:
    app = _import_app(monkeypatch)
    stale_merger = ModuleType("merger")
    fresh_merger = ModuleType("merger")
    expected = pd.DataFrame([{"month": "2026-05", "bundles_created": 1}])
    fresh_merger.build_monthly_bundle_creation_summary = (
        lambda creations, start, end: expected
    )

    monkeypatch.setattr(app, "merger", stale_merger)
    monkeypatch.setattr(app.importlib, "reload", lambda module: fresh_merger)

    result = app._build_monthly_bundle_creation_summary(
        pd.DataFrame(), date(2026, 5, 1), date(2026, 5, 31)
    )

    assert result is expected
    assert app.merger is fresh_merger


def test_monthly_bundle_creations_reloads_stale_database_module(monkeypatch) -> None:
    app = _import_app(monkeypatch)
    stale_database = ModuleType("database")
    fresh_database = ModuleType("database")
    expected = pd.DataFrame([{"month": "2026-05", "bundles_created": 1}])
    fresh_database.get_monthly_bundle_creations = (
        lambda region, start, end, org_id=None: expected
    )

    monkeypatch.setattr(app, "database", stale_database)
    monkeypatch.setattr(app.importlib, "reload", lambda module: fresh_database)

    result = app._get_monthly_bundle_creations(
        "eu", date(2026, 5, 1), date(2026, 5, 31), 196
    )

    assert result is expected
    assert app.database is fresh_database


def test_bundle_filter_breakdown_reloads_stale_database_module(monkeypatch) -> None:
    app = _import_app(monkeypatch)
    stale_database = ModuleType("database")
    fresh_database = ModuleType("database")
    expected = pd.DataFrame(
        [{"filter_type": "age", "filter_value": "sixties", "bundle_count": 1}]
    )
    fresh_database.get_bundle_filter_breakdown = (
        lambda region, start, end, org_id=None: expected
    )

    monkeypatch.setattr(app, "database", stale_database)
    monkeypatch.setattr(app.importlib, "reload", lambda module: fresh_database)

    result = app._get_bundle_filter_breakdown(
        "eu", date(2026, 5, 1), date(2026, 5, 31), 196
    )

    assert result is expected
    assert app.database is fresh_database


def test_deployment_revision_is_not_shown_in_sidebar(monkeypatch) -> None:
    app = _import_app(monkeypatch)

    assert not any("Deployment revision:" in caption for caption in app.st._captions)


def test_monthly_question_chart_separates_target_and_labels_outcome_proxy(
    monkeypatch,
) -> None:
    app = _import_app(monkeypatch)
    monthly_ratings = pd.DataFrame(
        [
            {
                "month": "2026-05",
                "target": "groups",
                "question_label": "How much did you enjoy the session?",
                "avg_rating": 4.0,
                "total_responses": 1,
            },
            {
                "month": "2026-05",
                "target": "groups",
                "question_label": "How do you feel after today's session?",
                "avg_rating": 4.5,
                "total_responses": 1,
            },
            {
                "month": "2026-05",
                "target": "therapists",
                "question_label": "How much did the group enjoy the session?",
                "avg_rating": 3.0,
                "total_responses": 1,
            },
        ]
    )

    chart, colors = app._monthly_question_chart(monthly_ratings, "groups")

    assert list(chart.columns) == [
        "How do you feel after today's session? (not a clinical outcome)",
        "How much did you enjoy the session?",
    ]
    assert "How much did the group enjoy the session?" not in chart.columns
    assert colors[0] == "#ff7f0e"


def test_monthly_question_summary_reloads_stale_merger_module(monkeypatch) -> None:
    app = _import_app(monkeypatch)
    stale_merger = ModuleType("merger")
    fresh_merger = ModuleType("merger")
    expected = pd.DataFrame([{"month": "2026-05"}])
    fresh_merger.build_monthly_question_rating_summary = lambda ratings: expected

    monkeypatch.setattr(app, "merger", stale_merger)
    monkeypatch.setattr(app.importlib, "reload", lambda module: fresh_merger)

    result = app._build_monthly_question_rating_summary(pd.DataFrame())

    assert result is expected
    assert app.merger is fresh_merger
