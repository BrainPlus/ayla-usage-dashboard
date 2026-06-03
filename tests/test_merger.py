import pandas as pd

import merger


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def _base_users() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "user_id": "u1",
                "email": "u1@example.com",
                "organisation_name": "Org A",
            }
        ]
    )


def _visit_durations(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["user_id", "visit_duration_seconds", "has_deliver_action"],
    )


def _build_user_detail(
    visit_durations: pd.DataFrame,
    db_users: pd.DataFrame | None = None,
    logins_30: pd.DataFrame | None = None,
    logins_90: pd.DataFrame | None = None,
) -> pd.DataFrame:
    return merger.build_user_detail(
        db_users if db_users is not None else _base_users(),
        logins_30
        if logins_30 is not None
        else _empty(["user_id", "visits"]),
        logins_90
        if logins_90 is not None
        else _empty(["user_id", "visits"]),
        _empty(["user_id", "last_login_date"]),
        visit_durations,
        _empty(["user_id", "activities_completed"]),
    )


def test_real_session_only_sets_real_average() -> None:
    result = _build_user_detail(
        _visit_durations(
            [
                {
                    "user_id": "u1",
                    "visit_duration_seconds": 25 * 60,
                    "has_deliver_action": True,
                }
            ]
        )
    )

    row = result.iloc[0]
    assert row["avg_real_session_minutes"] == 25.0
    assert row["median_prepare_minutes"] == 0.0
    assert row["short_visit_count"] == 0


def test_short_visit_only_increments_short_visit_count() -> None:
    result = _build_user_detail(
        _visit_durations(
            [
                {
                    "user_id": "u1",
                    "visit_duration_seconds": 20 * 60,
                    "has_deliver_action": True,
                }
            ]
        )
    )

    row = result.iloc[0]
    assert row["avg_real_session_minutes"] == 0.0
    assert row["median_prepare_minutes"] == 0.0
    assert row["short_visit_count"] == 1


def test_prepare_only_visit_sets_prepare_average() -> None:
    result = _build_user_detail(
        _visit_durations(
            [
                {
                    "user_id": "u1",
                    "visit_duration_seconds": 12 * 60,
                    "has_deliver_action": False,
                }
            ]
        )
    )

    row = result.iloc[0]
    assert row["avg_real_session_minutes"] == 0.0
    assert row["median_prepare_minutes"] == 12.0
    assert row["short_visit_count"] == 0


def test_mixed_visit_is_classified_as_deliver() -> None:
    result = _build_user_detail(
        _visit_durations(
            [
                {
                    "user_id": "u1",
                    "visit_duration_seconds": 30 * 60,
                    "has_deliver_action": True,
                }
            ]
        )
    )

    row = result.iloc[0]
    assert row["avg_real_session_minutes"] == 30.0
    assert row["median_prepare_minutes"] == 0.0
    assert row["short_visit_count"] == 0


def test_user_with_no_visits_gets_zero_duration_metrics() -> None:
    result = _build_user_detail(
        _visit_durations([]),
    )

    row = result.iloc[0]
    assert row["avg_real_session_minutes"] == 0.0
    assert row["median_prepare_minutes"] == 0.0
    assert row["short_visit_count"] == 0


def test_empty_visit_durations_keep_duration_averages_numeric_for_org_summary() -> None:
    with pd.option_context("future.no_silent_downcasting", True):
        user_detail = _build_user_detail(_visit_durations([]))

        assert user_detail["avg_real_session_minutes"].dtype == "float64"
        assert user_detail["median_prepare_minutes"].dtype == "float64"

        org_summary = merger.build_org_summary(
            user_detail,
            _empty(["bundle_id", "session_id", "user_id"]),
            _empty(["bundle_id", "session_id", "user_id"]),
            _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
            pd.DataFrame([{"organisation_name": "Org A", "user_count": 1}]),
            visit_durations=_visit_durations([]),
        )

    row = org_summary.iloc[0]
    assert row["avg_real_session_minutes"] == 0.0
    assert row["median_prepare_minutes"] == 0.0


def test_org_summary_sums_short_visits_and_uses_median_of_user_medians() -> None:
    db_users = pd.DataFrame(
        [
            {
                "user_id": "u1",
                "email": "u1@example.com",
                "organisation_name": "Org A",
            },
            {
                "user_id": "u2",
                "email": "u2@example.com",
                "organisation_name": "Org A",
            },
        ]
    )
    user_detail = _build_user_detail(
        _visit_durations(
            [
                {
                    "user_id": "u1",
                    "visit_duration_seconds": 30 * 60,
                    "has_deliver_action": True,
                },
                {
                    "user_id": "u1",
                    "visit_duration_seconds": 60 * 60,
                    "has_deliver_action": True,
                },
                {
                    "user_id": "u1",
                    "visit_duration_seconds": 10 * 60,
                    "has_deliver_action": False,
                },
                {
                    "user_id": "u1",
                    "visit_duration_seconds": 20 * 60,
                    "has_deliver_action": False,
                },
                {
                    "user_id": "u1",
                    "visit_duration_seconds": 5 * 60,
                    "has_deliver_action": True,
                },
                {
                    "user_id": "u2",
                    "visit_duration_seconds": 90 * 60,
                    "has_deliver_action": True,
                },
                {
                    "user_id": "u2",
                    "visit_duration_seconds": 45 * 60,
                    "has_deliver_action": False,
                },
                {
                    "user_id": "u2",
                    "visit_duration_seconds": 2 * 60,
                    "has_deliver_action": True,
                },
                {
                    "user_id": "u2",
                    "visit_duration_seconds": 20 * 60,
                    "has_deliver_action": True,
                },
            ]
        ),
        db_users=db_users,
        logins_30=pd.DataFrame(
            [
                {"user_id": "u1", "visits": 2},
                {"user_id": "u2", "visits": 1},
            ]
        ),
        logins_90=pd.DataFrame(
            [
                {"user_id": "u1", "visits": 4},
                {"user_id": "u2", "visits": 3},
            ]
        ),
    )

    org_summary = merger.build_org_summary(
        user_detail,
        _empty(["bundle_id", "session_id", "user_id"]),
        _empty(["bundle_id", "session_id", "user_id"]),
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([{"organisation_name": "Org A", "user_count": 2}]),
        visit_durations=_visit_durations([]),
    )

    row = org_summary.iloc[0]
    assert row["short_visit_count"] == 3
    assert row["avg_real_session_minutes"] == 67.5
    assert row["median_prepare_minutes"] == 30.0


def test_prepare_median_not_mean() -> None:
    """Skewed distribution: median (10) != mean (25) — verifies we use median."""
    result = _build_user_detail(
        _visit_durations(
            [
                {"user_id": "u1", "visit_duration_seconds": 5 * 60, "has_deliver_action": False},
                {"user_id": "u1", "visit_duration_seconds": 10 * 60, "has_deliver_action": False},
                {"user_id": "u1", "visit_duration_seconds": 60 * 60, "has_deliver_action": False},
            ]
        )
    )

    row = result.iloc[0]
    assert row["median_prepare_minutes"] == 10.0  # median, not mean (25.0)


def test_org_summary_two_level_median() -> None:
    """Org-level aggregation uses median of per-user medians."""
    db_users = pd.DataFrame(
        [
            {"user_id": "u1", "email": "u1@example.com", "organisation_name": "Org A"},
            {"user_id": "u2", "email": "u2@example.com", "organisation_name": "Org A"},
        ]
    )
    user_detail = _build_user_detail(
        _visit_durations(
            [
                # u1: prepare visits 5, 10, 60 min -> median 10.0
                {"user_id": "u1", "visit_duration_seconds": 5 * 60, "has_deliver_action": False},
                {"user_id": "u1", "visit_duration_seconds": 10 * 60, "has_deliver_action": False},
                {"user_id": "u1", "visit_duration_seconds": 60 * 60, "has_deliver_action": False},
                # u2: prepare visits 20, 30 min -> median 25.0
                {"user_id": "u2", "visit_duration_seconds": 20 * 60, "has_deliver_action": False},
                {"user_id": "u2", "visit_duration_seconds": 30 * 60, "has_deliver_action": False},
            ]
        ),
        db_users=db_users,
    )

    org_summary = merger.build_org_summary(
        user_detail,
        _empty(["bundle_id", "session_id", "user_id"]),
        _empty(["bundle_id", "session_id", "user_id"]),
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([{"organisation_name": "Org A", "user_count": 2}]),
        visit_durations=_visit_durations([]),
    )

    row = org_summary.iloc[0]
    # median of user medians: median([10.0, 25.0]) = 17.5
    assert row["median_prepare_minutes"] == 17.5

def _base_org_setup_for_minmax(visit_rows):
    """Helper: single-org (Org A) with u1 and u2, returns (user_detail, visit_durations_df)."""
    db_users = pd.DataFrame([
        {"user_id": "u1", "email": "u1@example.com", "organisation_name": "Org A"},
        {"user_id": "u2", "email": "u2@example.com", "organisation_name": "Org A"},
    ])
    vd = _visit_durations(visit_rows)
    user_detail = _build_user_detail(vd, db_users=db_users)
    return user_detail, vd


def _org_summary_with_vd(user_detail, vd, user_count=2):
    return merger.build_org_summary(
        user_detail,
        _empty(["bundle_id", "session_id", "user_id"]),
        _empty(["bundle_id", "session_id", "user_id"]),
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([{"organisation_name": "Org A", "user_count": user_count}]),
        visit_durations=vd,
    )


def test_org_min_max_basic() -> None:
    """Two users with different session lengths: min/max from raw visits."""
    user_detail, vd = _base_org_setup_for_minmax([
        {"user_id": "u1", "visit_duration_seconds": 30 * 60, "has_deliver_action": True},
        {"user_id": "u1", "visit_duration_seconds": 60 * 60, "has_deliver_action": True},
        {"user_id": "u2", "visit_duration_seconds": 45 * 60, "has_deliver_action": True},
    ])
    row = _org_summary_with_vd(user_detail, vd).iloc[0]
    assert row["min_real_session_minutes"] == 30.0
    assert row["max_real_session_minutes"] == 60.0


def test_org_min_max_single_session() -> None:
    """Org has only one real session: min == max."""
    db_users = pd.DataFrame([
        {"user_id": "u1", "email": "u1@example.com", "organisation_name": "Org A"},
    ])
    vd = _visit_durations([
        {"user_id": "u1", "visit_duration_seconds": 25 * 60, "has_deliver_action": True},
    ])
    user_detail = _build_user_detail(vd, db_users=db_users)
    org_summary = merger.build_org_summary(
        user_detail,
        _empty(["bundle_id", "session_id", "user_id"]),
        _empty(["bundle_id", "session_id", "user_id"]),
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([{"organisation_name": "Org A", "user_count": 1}]),
        visit_durations=vd,
    )
    row = org_summary.iloc[0]
    assert row["min_real_session_minutes"] == 25.0
    assert row["max_real_session_minutes"] == 25.0


def test_org_min_max_excludes_short_visits() -> None:
    """Short deliver visits (<= 20 min) must NOT affect min_real_session_minutes."""
    db_users = pd.DataFrame([
        {"user_id": "u1", "email": "u1@example.com", "organisation_name": "Org A"},
    ])
    vd = _visit_durations([
        {"user_id": "u1", "visit_duration_seconds": 10 * 60, "has_deliver_action": True},  # short
        {"user_id": "u1", "visit_duration_seconds": 40 * 60, "has_deliver_action": True},  # real
    ])
    user_detail = _build_user_detail(vd, db_users=db_users)
    org_summary = merger.build_org_summary(
        user_detail,
        _empty(["bundle_id", "session_id", "user_id"]),
        _empty(["bundle_id", "session_id", "user_id"]),
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([{"organisation_name": "Org A", "user_count": 1}]),
        visit_durations=vd,
    )
    row = org_summary.iloc[0]
    assert row["min_real_session_minutes"] == 40.0  # short visit excluded
    assert row["max_real_session_minutes"] == 40.0


def test_org_min_max_no_real_sessions() -> None:
    """When no real sessions exist, both min and max should be 0.0."""
    db_users = pd.DataFrame([
        {"user_id": "u1", "email": "u1@example.com", "organisation_name": "Org A"},
    ])
    vd = _visit_durations([
        {"user_id": "u1", "visit_duration_seconds": 5 * 60, "has_deliver_action": True},  # short only
    ])
    user_detail = _build_user_detail(vd, db_users=db_users)
    org_summary = merger.build_org_summary(
        user_detail,
        _empty(["bundle_id", "session_id", "user_id"]),
        _empty(["bundle_id", "session_id", "user_id"]),
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([{"organisation_name": "Org A", "user_count": 1}]),
        visit_durations=vd,
    )
    row = org_summary.iloc[0]
    assert row["min_real_session_minutes"] == 0.0
    assert row["max_real_session_minutes"] == 0.0
