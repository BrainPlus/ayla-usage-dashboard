from types import SimpleNamespace

import revision


def test_deployment_revision_prefers_environment_commit(monkeypatch) -> None:
    monkeypatch.setenv("STREAMLIT_GIT_COMMIT", "1234567890abcdef")
    monkeypatch.setattr(
        revision.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("git called")),
    )

    assert revision.get_deployment_revision() == "1234567890ab"


def test_deployment_revision_uses_git_checkout(monkeypatch) -> None:
    for name in revision._REVISION_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        revision.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="abcdef123456\n"),
    )

    assert revision.get_deployment_revision() == "abcdef123456"


def test_deployment_revision_falls_back_when_git_is_unavailable(monkeypatch) -> None:
    for name in revision._REVISION_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    def missing_git(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(revision.subprocess, "run", missing_git)

    assert revision.get_deployment_revision() == "unknown"
