import importlib
import sys
from types import ModuleType


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
    sys.modules.pop("app", None)

    app = importlib.import_module("app")

    assert app._cached_activity_catalogue() == {}


def test_cached_activity_usage_reloads_stale_matomo_module(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "streamlit", _streamlit_stub())
    sys.modules.pop("app", None)

    app = importlib.import_module("app")
    stale_matomo = ModuleType("matomo")
    fresh_matomo = ModuleType("matomo")
    fresh_matomo.get_activity_usage_by_id = lambda date_range: f"usage:{date_range}"

    monkeypatch.setattr(app, "matomo", stale_matomo)
    monkeypatch.setattr(app.importlib, "reload", lambda module: fresh_matomo)

    assert app._cached_activity_usage("2026-01-01,2026-01-31") == (
        "usage:2026-01-01,2026-01-31"
    )
    assert app.matomo is fresh_matomo


def test_global_summary_supports_stale_two_argument_merger_module(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "streamlit", _streamlit_stub())
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
