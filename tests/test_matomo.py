import concurrent.futures

import matomo
import pytest


class _ImmediateFuture:
    def __init__(self, result):
        self._result = result

    def result(self):
        return self._result


class _RecordingExecutor:
    max_workers_seen = []

    def __init__(self, max_workers):
        self.max_workers = max_workers
        self.futures = []
        self.max_workers_seen.append(max_workers)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def submit(self, fn, *args):
        future = _ImmediateFuture(fn(*args))
        self.futures.append(future)
        return future


@pytest.mark.parametrize("max_workers", [0, -3])
def test_last_login_normalizes_worker_count_and_reports_initial_progress(
    monkeypatch, max_workers
):
    _RecordingExecutor.max_workers_seen = []

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", _RecordingExecutor)
    monkeypatch.setattr(concurrent.futures, "as_completed", lambda futures: list(futures))
    monkeypatch.setattr(
        matomo,
        "matomo_get",
        lambda params: [{"lastActionDateTime": f"2026-06-0{params['segment'][-1]} 10:00:00"}],
    )

    progress_calls = []

    def record_progress(current, total):
        progress_calls.append((current, total))

    result = matomo.get_last_login_per_user(
        ["u1", "u2"],
        record_progress,
        max_workers=max_workers,
    )

    assert _RecordingExecutor.max_workers_seen == [1]
    assert progress_calls == [(0, 2), (1, 2), (2, 2)]
    assert result.to_dict("records") == [
        {"user_id": "u1", "last_login_date": "2026-06-01"},
        {"user_id": "u2", "last_login_date": "2026-06-02"},
    ]


def test_last_login_caps_worker_count_to_user_count(monkeypatch):
    _RecordingExecutor.max_workers_seen = []

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", _RecordingExecutor)
    monkeypatch.setattr(concurrent.futures, "as_completed", lambda futures: list(futures))
    monkeypatch.setattr(matomo, "matomo_get", lambda params: [])

    matomo.get_last_login_per_user(["u1", "u2"], max_workers=10)

    assert _RecordingExecutor.max_workers_seen == [2]
