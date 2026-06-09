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
    streamlit.caption = lambda *args, **kwargs: None
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
    assert not app._should_clear_report(
        {
            "fetched_region": "eu",
            "fetched_org_id": 196,
            "fetched_date_range": "range",
        },
        "eu",
        196,
        "range",
    )
    assert app._should_clear_report(
        {
            "fetched_region": "eu",
            "fetched_org_id": 196,
            "fetched_date_range": "range",
        },
        "eu",
        "unassigned",
        "range",
    )


def test_filter_to_org_users(monkeypatch) -> None:
    app = _import_app(monkeypatch)
    df = pd.DataFrame([{"user_id": "u1"}, {"user_id": "u2"}])

    result = app._filter_to_org_users(df, {"u2"})

    assert result.to_dict("records") == [{"user_id": "u2"}]


def test_last_login_user_ids(monkeypatch) -> None:
    app = _import_app(monkeypatch)
    db_users = pd.DataFrame([{"user_id": "u1"}, {"user_id": "u2"}])
    logins = pd.DataFrame([{"user_id": "u2"}, {"user_id": "u3"}])

    assert app._last_login_user_ids(db_users, logins, 196) == ["u1", "u2"]
    assert app._last_login_user_ids(db_users, logins, None) == ["u1", "u2", "u3"]
