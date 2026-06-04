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
