import importlib
import sys
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


def test_filter_to_org_users(monkeypatch) -> None:
    app = _import_app(monkeypatch)
    df = pd.DataFrame([{"user_id": "u1"}, {"user_id": "u2"}])

    result = app._filter_to_org_users(df, {"u2"})

    assert result.to_dict("records") == [{"user_id": "u2"}]
    without_user_ids = pd.DataFrame([{"activity_id": "a1"}])
    assert app._filter_to_org_users(without_user_ids, {"u2"}).equals(without_user_ids)


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
        "monthly_average_star_ratings",
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


def test_deployment_revision_is_not_shown_in_sidebar(monkeypatch) -> None:
    app = _import_app(monkeypatch)

    assert not any("Deployment revision:" in caption for caption in app.st._captions)
