from datetime import date

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
    logins: pd.DataFrame | None = None,
    last_login: pd.DataFrame | None = None,
) -> pd.DataFrame:
    return merger.build_user_detail(
        db_users if db_users is not None else _base_users(),
        logins if logins is not None else _empty(["user_id", "visits"]),
        last_login if last_login is not None else _empty(["user_id", "last_login_date"]),
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


def test_empty_last_login_uses_no_usage_fallback_for_user_and_org() -> None:
    user_detail = _build_user_detail(
        _visit_durations([]),
        last_login=pd.DataFrame([{"user_id": "u1", "last_login_date": ""}]),
    )

    assert user_detail.iloc[0]["last_login_date"] == "No tracked usage"

    org_summary = merger.build_org_summary(
        user_detail,
        _empty(["visit_id", "bundle_id", "session_id", "user_id"]),
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([{"organisation_name": "Org A", "user_count": 1}]),
        visit_durations=_visit_durations([]),
    )

    assert org_summary.iloc[0]["last_login_date"] == "No tracked usage"


def test_empty_visit_durations_keep_duration_averages_numeric_for_org_summary() -> None:
    with pd.option_context("future.no_silent_downcasting", True):
        user_detail = _build_user_detail(_visit_durations([]))

        assert user_detail["avg_real_session_minutes"].dtype == "float64"
        assert user_detail["median_prepare_minutes"].dtype == "float64"

        org_summary = merger.build_org_summary(
            user_detail,
            _empty(["visit_id", "bundle_id", "session_id", "user_id"]),
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
        logins=pd.DataFrame(
            [
                {"user_id": "u1", "visits": 2},
                {"user_id": "u2", "visits": 1},
            ]
        ),
    )

    org_summary = merger.build_org_summary(
        user_detail,
        _empty(["visit_id", "bundle_id", "session_id", "user_id"]),
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
        _empty(["visit_id", "bundle_id", "session_id", "user_id"]),
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
        _empty(["visit_id", "bundle_id", "session_id", "user_id"]),
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
        _empty(["visit_id", "bundle_id", "session_id", "user_id"]),
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
        _empty(["visit_id", "bundle_id", "session_id", "user_id"]),
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([{"organisation_name": "Org A", "user_count": 1}]),
        visit_durations=vd,
    )
    row = org_summary.iloc[0]
    assert row["min_real_session_minutes"] == 40.0  # short visit excluded
    assert row["max_real_session_minutes"] == 40.0


def test_org_avg_is_visit_weighted_when_raw_visits_provided() -> None:
    """When raw visit_durations are passed, org avg is weighted by visit count (not user count)."""
    db_users = pd.DataFrame([
        {"user_id": "u1", "email": "u1@example.com", "organisation_name": "Org A"},
        {"user_id": "u2", "email": "u2@example.com", "organisation_name": "Org A"},
    ])
    # u1: 1 real session of 30 min, u2: 10 real sessions of 60 min each
    visit_rows = [
        {"user_id": "u1", "visit_duration_seconds": 30 * 60, "has_deliver_action": True},
    ] + [
        {"user_id": "u2", "visit_duration_seconds": 60 * 60, "has_deliver_action": True}
    ] * 10
    vd = _visit_durations(visit_rows)
    user_detail = _build_user_detail(vd, db_users=db_users)
    row = _org_summary_with_vd(user_detail, vd).iloc[0]

    # Visit-weighted: (30 + 10*60) / 11 = 57.3 min
    expected = round((30 + 10 * 60) / 11, 1)
    assert row["avg_real_session_minutes"] == expected
    # Confirm it is NOT the unweighted mean-of-means (45.0)
    assert row["avg_real_session_minutes"] != 45.0


def test_org_avg_falls_back_to_user_detail_when_visit_durations_absent() -> None:
    """When visit_durations is empty, org avg falls back to the mean of per-user averages."""
    db_users = pd.DataFrame([
        {"user_id": "u1", "email": "u1@example.com", "organisation_name": "Org A"},
        {"user_id": "u2", "email": "u2@example.com", "organisation_name": "Org A"},
    ])
    vd = _visit_durations([
        {"user_id": "u1", "visit_duration_seconds": 30 * 60, "has_deliver_action": True},
        {"user_id": "u2", "visit_duration_seconds": 60 * 60, "has_deliver_action": True},
    ])
    user_detail = _build_user_detail(vd, db_users=db_users)

    # build_org_summary called with EMPTY visit_durations — must use user_detail fallback
    org_summary = merger.build_org_summary(
        user_detail,
        _empty(["visit_id", "bundle_id", "session_id", "user_id"]),
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([{"organisation_name": "Org A", "user_count": 2}]),
        visit_durations=_visit_durations([]),
    )

    row = org_summary.iloc[0]
    assert row["avg_real_session_minutes"] == 45.0  # mean of [30.0, 60.0]
    assert row["min_real_session_minutes"] == 0.0   # cannot derive without raw visits
    assert row["max_real_session_minutes"] == 0.0


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
        _empty(["visit_id", "bundle_id", "session_id", "user_id"]),
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([{"organisation_name": "Org A", "user_count": 1}]),
        visit_durations=vd,
    )
    row = org_summary.iloc[0]
    assert row["min_real_session_minutes"] == 0.0
    assert row["max_real_session_minutes"] == 0.0



def test_avg_activities_per_session_basic() -> None:
    """Sum activities_completed across users, divide by completed_sessions."""
    db_users = pd.DataFrame([
        {"user_id": "u1", "email": "u1@example.com", "organisation_name": "Org A"},
        {"user_id": "u2", "email": "u2@example.com", "organisation_name": "Org A"},
    ])
    activity_completions = pd.DataFrame([
        {"user_id": "u1", "activities_completed": 10},
        {"user_id": "u2", "activities_completed": 5},
    ])
    user_detail = merger.build_user_detail(
        db_users,
        _empty(["user_id", "visits"]),
        _empty(["user_id", "last_login_date"]),
        _visit_durations([]),
        activity_completions,
    )
    sessions_30 = pd.DataFrame([
        {"visit_id": "v1", "bundle_id": "b1", "session_id": "s1", "user_id": "u1"},
        {"visit_id": "v2", "bundle_id": "b1", "session_id": "s2", "user_id": "u1"},
        {"visit_id": "v3", "bundle_id": "b1", "session_id": "s3", "user_id": "u2"},
    ])
    org_summary = merger.build_org_summary(
        user_detail,
        sessions_30,
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([{"organisation_name": "Org A", "user_count": 2}]),
        visit_durations=_visit_durations([]),
    )
    row = org_summary.iloc[0]
    assert row["avg_activities_per_session"] == 5.0  # 15 / 3 = 5.0


def test_completed_sessions_are_consistent_across_user_org_and_global_summaries() -> None:
    db_users = pd.DataFrame([
        {"user_id": "u1", "email": "u1@example.com", "organisation_name": "Org A"},
    ])
    completed_sessions = pd.DataFrame([
        {"visit_id": "v1", "bundle_id": "b1", "session_id": "s1", "user_id": "u1"},
        {"visit_id": "v1", "bundle_id": "b1", "session_id": "s1", "user_id": "u1"},
        {"visit_id": "v2", "bundle_id": "b1", "session_id": "s1", "user_id": "u1"},
    ])
    user_detail = merger.build_user_detail(
        db_users,
        _empty(["user_id", "visits"]),
        _empty(["user_id", "last_login_date"]),
        _visit_durations([]),
        _empty(["user_id", "activities_completed"]),
        completed_sessions,
    )
    org_summary = merger.build_org_summary(
        user_detail,
        completed_sessions,
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([{"organisation_name": "Org A", "user_count": 1}]),
        visit_durations=_visit_durations([]),
    )
    global_summary = merger.build_global_summary(
        org_summary,
        _empty(["organisation_name", "total_groups"]),
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
    )

    assert user_detail.iloc[0]["completed_sessions"] == 2
    assert org_summary.iloc[0]["completed_sessions"] == 2
    assert global_summary["total_completed_sessions"] == 2


def test_feedback_coverage_uses_unique_bundle_session_pairs_and_submission_comments() -> None:
    db_users = pd.DataFrame([
        {"user_id": "u1", "email": "u1@example.com", "organisation_name": "Org A"},
    ])
    completed_sessions = pd.DataFrame([
        {"visit_id": "v1", "bundle_id": "b1", "session_id": "s1", "user_id": "u1"},
        {"visit_id": "v2", "bundle_id": "b1", "session_id": "s1", "user_id": "u1"},
        {"visit_id": "v3", "bundle_id": "b1", "session_id": "s2", "user_id": "u1"},
        {"visit_id": "v4", "bundle_id": "b1", "session_id": "s3", "user_id": "u1"},
    ])
    feedback_submissions = pd.DataFrame([
        {
            "organisation_name": "Org A", "target": "groups",
            "bundle_id": "feedback-b1", "session_id": "s1", "has_comment": False,
        },
        {
            "organisation_name": "Org A", "target": "groups",
            "bundle_id": "feedback-b1", "session_id": "s1", "has_comment": False,
        },
        {
            "organisation_name": "Org A", "target": "groups",
            "bundle_id": "feedback-b1", "session_id": "s2", "has_comment": False,
        },
        {
            "organisation_name": "Org A", "target": "therapists",
            "bundle_id": "feedback-b1", "session_id": "s1", "has_comment": True,
        },
        {
            "organisation_name": "Org A", "target": "therapists",
            "bundle_id": "feedback-b1", "session_id": "s1", "has_comment": False,
        },
        {
            "organisation_name": "Org A", "target": "therapists",
            "bundle_id": "feedback-b1", "session_id": "s2", "has_comment": True,
        },
    ])
    user_detail = merger.build_user_detail(
        db_users,
        _empty(["user_id", "visits"]),
        _empty(["user_id", "last_login_date"]),
        _visit_durations([]),
        _empty(["user_id", "activities_completed"]),
        completed_sessions,
    )

    result = merger.build_org_summary(
        user_detail,
        completed_sessions,
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([{"organisation_name": "Org A", "user_count": 1}]),
        visit_durations=_visit_durations([]),
        feedback_submissions=feedback_submissions,
    ).iloc[0]

    assert result["completed_sessions"] == 4
    assert result["group_feedback_coverage"] == "67%"
    assert result["therapist_feedback_coverage"] == "67%"
    assert result["therapist_comment_rate"] == "67%"


def test_feedback_rates_show_no_sessions_for_organisations_without_completed_pairs() -> None:
    db_users = pd.DataFrame([
        {"user_id": "u1", "email": "u1@example.com", "organisation_name": "Org A"},
    ])
    user_detail = merger.build_user_detail(
        db_users,
        _empty(["user_id", "visits"]),
        _empty(["user_id", "last_login_date"]),
        _visit_durations([]),
        _empty(["user_id", "activities_completed"]),
    )
    feedback_submissions = pd.DataFrame([
        {
            "organisation_name": "Org A", "target": "therapists",
            "bundle_id": "b1", "session_id": "s1", "has_comment": True,
        },
    ])

    result = merger.build_org_summary(
        user_detail,
        _empty(["visit_id", "bundle_id", "session_id", "user_id"]),
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([{"organisation_name": "Org A", "user_count": 1}]),
        visit_durations=_visit_durations([]),
        feedback_submissions=feedback_submissions,
    ).iloc[0]

    assert result["group_feedback_coverage"] == "No sessions"
    assert result["therapist_feedback_coverage"] == "No sessions"
    assert result["therapist_comment_rate"] == "No sessions"


def test_feedback_coverage_deduplicates_completed_pairs_within_each_organisation() -> None:
    db_users = pd.DataFrame([
        {"user_id": "u1", "email": "u1@example.com", "organisation_name": "Org A"},
        {"user_id": "u2", "email": "u2@example.com", "organisation_name": "Org B"},
    ])
    completed_sessions = pd.DataFrame([
        {"visit_id": "v1", "bundle_id": "b1", "session_id": "s1", "user_id": "u1"},
        {"visit_id": "v2", "bundle_id": "b1", "session_id": "s1", "user_id": "u2"},
    ])
    user_detail = merger.build_user_detail(
        db_users,
        _empty(["user_id", "visits"]),
        _empty(["user_id", "last_login_date"]),
        _visit_durations([]),
        _empty(["user_id", "activities_completed"]),
        completed_sessions,
    )

    result = merger.build_org_summary(
        user_detail,
        completed_sessions,
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([
            {"organisation_name": "Org A", "user_count": 1},
            {"organisation_name": "Org B", "user_count": 1},
        ]),
        visit_durations=_visit_durations([]),
    ).set_index("organisation_name")

    assert result.loc["Org A", "group_feedback_coverage"] == "0%"
    assert result.loc["Org B", "group_feedback_coverage"] == "0%"


def test_days_since_last_completed_session_uses_latest_deduplicated_session() -> None:
    db_users = pd.DataFrame([
        {"user_id": "u1", "email": "u1@example.com", "organisation_name": "Org A"},
        {"user_id": "u2", "email": "u2@example.com", "organisation_name": "Org B"},
    ])
    user_detail = merger.build_user_detail(
        db_users,
        _empty(["user_id", "visits"]),
        _empty(["user_id", "last_login_date"]),
        _visit_durations([]),
        _empty(["user_id", "activities_completed"]),
    )
    recent_completed_sessions = pd.DataFrame([
        {
            "visit_id": "v1", "bundle_id": "b1", "session_id": "s1",
            "user_id": "u1", "completion_date": "2026-05-01",
        },
        {
            "visit_id": "v1", "bundle_id": "b1", "session_id": "s1",
            "user_id": "u1", "completion_date": "2026-05-09",
        },
        {
            "visit_id": "v2", "bundle_id": "b1", "session_id": "s2",
            "user_id": "u1", "completion_date": "2026-05-08",
        },
    ])

    org_summary = merger.build_org_summary(
        user_detail,
        _empty(["visit_id", "bundle_id", "session_id", "user_id"]),
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([
            {"organisation_name": "Org A", "user_count": 1},
            {"organisation_name": "Org B", "user_count": 1},
        ]),
        visit_durations=_visit_durations([]),
        recent_completed_sessions=recent_completed_sessions,
        as_of_date=date(2026, 5, 10),
    ).set_index("organisation_name")

    assert org_summary.loc["Org A", "days_since_last_completed_session"] == "1"
    assert (
        org_summary.loc["Org B", "days_since_last_completed_session"]
        == "No recent session"
    )


def test_delivery_funnel_counts_and_dropoffs_are_aggregated_by_org() -> None:
    db_users = pd.DataFrame([
        {"user_id": "u1", "email": "u1@example.com", "organisation_name": "Org A"},
        {"user_id": "u2", "email": "u2@example.com", "organisation_name": "Org B"},
    ])
    completed_sessions = pd.DataFrame([
        {"visit_id": "v1", "bundle_id": "b1", "session_id": "s1", "user_id": "u1"},
    ])
    delivery_funnel = pd.DataFrame([
        {
            "visit_id": "v1", "bundle_id": "b1", "session_id": "s1", "user_id": "u1",
            "deliver_selected": True, "active_delivery": True, "completed_session": True,
        },
        {
            "visit_id": "v2", "bundle_id": "b1", "session_id": "s2", "user_id": "u1",
            "deliver_selected": True, "active_delivery": False, "completed_session": False,
        },
        {
            "visit_id": "v2", "bundle_id": "b1", "session_id": "s2", "user_id": "u1",
            "deliver_selected": True, "active_delivery": False, "completed_session": False,
        },
    ])
    user_detail = merger.build_user_detail(
        db_users,
        _empty(["user_id", "visits"]),
        _empty(["user_id", "last_login_date"]),
        _visit_durations([]),
        _empty(["user_id", "activities_completed"]),
        completed_sessions,
    )

    org_summary = merger.build_org_summary(
        user_detail,
        completed_sessions,
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([
            {"organisation_name": "Org A", "user_count": 1},
            {"organisation_name": "Org B", "user_count": 1},
        ]),
        visit_durations=_visit_durations([]),
        delivery_funnel=delivery_funnel,
    )
    global_summary = merger.build_global_summary(
        org_summary,
        _empty(["organisation_name", "total_groups"]),
    )

    org_a = org_summary.set_index("organisation_name").loc["Org A"]
    assert org_a["deliver_selected_sessions"] == 2
    assert org_a["active_delivery_sessions"] == 1
    assert org_a["completed_sessions"] == 1
    assert org_a["deliver_to_active_dropoff"] == 1
    assert org_a["deliver_to_active_dropoff_pct"] == 50.0
    assert org_a["active_to_completed_dropoff"] == 0
    assert org_a["active_to_completed_dropoff_pct"] == 0.0

    org_b = org_summary.set_index("organisation_name").loc["Org B"]
    assert org_b["deliver_selected_sessions"] == 0
    assert org_b["active_delivery_sessions"] == 0
    assert org_b["completed_sessions"] == 0
    assert org_b["deliver_to_active_dropoff_pct"] == 0.0
    assert global_summary["total_deliver_selected_sessions"] == 2
    assert global_summary["total_active_delivery_sessions"] == 1
    assert global_summary["total_completed_sessions"] == 1


def test_build_activity_usage_table_known_ids() -> None:
    """Known IDs get mapped to catalogue titles, sorted descending by completions."""
    usage = pd.DataFrame({"activity_id": ["abc", "def"], "completion_count": [5, 10]})
    catalogue = {"abc": "Reality Orientation", "def": "Warm Up"}
    result = merger.build_activity_usage_table(usage, catalogue)
    assert list(result["Activity Name"]) == ["Warm Up", "Reality Orientation"]
    assert list(result["Completions"]) == [10, 5]


def test_build_activity_usage_table_unknown_id_fallback() -> None:
    """Unknown IDs fall back to raw ID string."""
    usage = pd.DataFrame({"activity_id": ["unknown-xyz"], "completion_count": [3]})
    result = merger.build_activity_usage_table(usage, {})
    assert result.iloc[0]["Activity Name"] == "unknown-xyz"
    assert result.iloc[0]["Completions"] == 3


def test_build_activity_usage_table_empty_catalogue() -> None:
    """Empty catalogue returns raw IDs, no crash."""
    usage = pd.DataFrame({"activity_id": ["a1", "b2"], "completion_count": [7, 2]})
    result = merger.build_activity_usage_table(usage, {})
    assert list(result["Activity Name"]) == ["a1", "b2"]
    assert list(result["Completions"]) == [7, 2]


def test_build_activity_usage_table_empty_usage() -> None:
    """Empty usage DataFrame returns empty result with correct columns."""
    empty = pd.DataFrame(columns=["activity_id", "completion_count"])
    result = merger.build_activity_usage_table(empty, {"x": "Foo"})
    assert result.empty
    assert "Activity Name" in result.columns
    assert "Completions" in result.columns


def test_build_activity_usage_table_includes_normalised_language() -> None:
    usage = pd.DataFrame(
        {
            "activity_id": ["abc", "abc", "def"],
            "language": ["en-GB", "en", "da-DK"],
            "completion_count": [5, 2, 10],
        }
    )
    catalogue = {"abc": "Reality Orientation", "def": "Warm Up"}

    result = merger.build_activity_usage_table(usage, catalogue)

    assert list(result.columns) == ["Activity Name", "Language", "Completions"]
    assert result.to_dict("records") == [
        {"Activity Name": "Warm Up", "Language": "DK", "Completions": 10},
        {"Activity Name": "Reality Orientation", "Language": "UK", "Completions": 7},
    ]


def test_build_step_completion_depth_table_summarises_depth_and_reach() -> None:
    completions = pd.DataFrame(
        [
            {"activity_instance_id": "i1", "activity_id": "a1", "language": "en-GB", "step_number": 1},
            {"activity_instance_id": "i1", "activity_id": "a1", "language": "en-GB", "step_number": 2},
            {"activity_instance_id": "i1", "activity_id": "a1", "language": "en-GB", "step_number": 2},
            {"activity_instance_id": "i2", "activity_id": "a1", "language": "en", "step_number": 1},
            {"activity_instance_id": "i2", "activity_id": "a1", "language": "en", "step_number": 2},
            {"activity_instance_id": "i2", "activity_id": "a1", "language": "en", "step_number": 3},
            {"activity_instance_id": "i3", "activity_id": "a1", "language": "en", "step_number": 1},
        ]
    )

    result = merger.build_step_completion_depth_table(completions, {"a1": "Warm Up"})

    assert result.to_dict("records") == [
        {
            "Activity Name": "Warm Up",
            "Language": "UK",
            "Activity Occurrences": 3,
            "Avg Last Step Reached": 2.0,
            "Completion Depth Distribution": "Step 1: 1 (33%); Step 2: 1 (33%); Step 3: 1 (33%)",
            "Least Reached Step(s)": "Step 3 (1/3, 33%)",
        }
    ]


def test_build_step_completion_depth_table_excludes_activities_without_events() -> None:
    result = merger.build_step_completion_depth_table(
        pd.DataFrame(
            columns=[
                "activity_instance_id",
                "activity_id",
                "language",
                "step_number",
            ]
        ),
        {"a1": "Warm Up"},
    )

    assert result.empty
    assert list(result.columns) == [
        "Activity Name",
        "Language",
        "Activity Occurrences",
        "Avg Last Step Reached",
        "Completion Depth Distribution",
        "Least Reached Step(s)",
    ]


def test_activity_language_filter_options_normalise_common_locales() -> None:
    usage = pd.DataFrame(
        {
            "activity_id": ["a", "b", "c", "d"],
            "language": ["en-GB", "da-DK", "de-DE", ""],
            "completion_count": [1, 1, 1, 1],
        }
    )

    result = merger.activity_language_filter_options(usage)

    assert result == ["all", "uk", "dk", "de", "unknown"]


def test_filter_activity_usage_by_language_uses_normalised_locale() -> None:
    usage = pd.DataFrame(
        {
            "activity_id": ["a", "b", "c"],
            "language": ["en-GB", "en", "da-DK"],
            "completion_count": [1, 2, 3],
        }
    )

    result = merger.filter_activity_usage_by_language(usage, "uk")

    assert list(result["activity_id"]) == ["a", "b"]


def test_activity_catalogue_match_stats_all_miss() -> None:
    usage = pd.DataFrame({"activity_id": ["a1", "b2"], "completion_count": [7, 2]})
    result = merger.activity_catalogue_match_stats(usage, {"c3": "Warm Up"})

    assert result == {
        "usage_ids": 2,
        "catalogue_ids": 1,
        "matched_ids": 0,
        "unmatched_ids": 2,
    }


def test_activity_catalogue_match_stats_partial_match() -> None:
    usage = pd.DataFrame({"activity_id": ["a1", "b2", "b2"], "completion_count": [7, 2, 1]})
    result = merger.activity_catalogue_match_stats(
        usage,
        {"a1": "Reality Orientation", "c3": "Warm Up"},
    )

    assert result == {
        "usage_ids": 2,
        "catalogue_ids": 2,
        "matched_ids": 1,
        "unmatched_ids": 1,
    }


def test_avg_activities_per_session_zero_completed_sessions() -> None:
    """When completed_sessions == 0, result must be 0.0 (not NaN or error)."""
    db_users = pd.DataFrame([
        {"user_id": "u1", "email": "u1@example.com", "organisation_name": "Org A"},
    ])
    activity_completions = pd.DataFrame([
        {"user_id": "u1", "activities_completed": 8},
    ])
    user_detail = merger.build_user_detail(
        db_users,
        _empty(["user_id", "visits"]),
        _empty(["user_id", "last_login_date"]),
        _visit_durations([]),
        activity_completions,
    )
    org_summary = merger.build_org_summary(
        user_detail,
        _empty(["visit_id", "bundle_id", "session_id", "user_id"]),
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
        pd.DataFrame([{"organisation_name": "Org A", "user_count": 1}]),
        visit_durations=_visit_durations([]),
    )
    row = org_summary.iloc[0]
    assert row["avg_activities_per_session"] == 0.0
    assert not pd.isna(row["avg_activities_per_session"])


def test_global_summary_weights_ratings_by_response_count() -> None:
    org_summary = pd.DataFrame(
        [
            {
                "organisation_name": "Org A",
                "total_users": 1,
                "completed_sessions": 2,
            },
            {
                "organisation_name": "Org B",
                "total_users": 1,
                "completed_sessions": 4,
            },
        ]
    )
    star_ratings = pd.DataFrame(
        [
            {
                "organisation_name": "Org A",
                "target": "groups",
                "avg_rating": 1.0,
                "total_responses": 1,
            },
            {
                "organisation_name": "Org B",
                "target": "groups",
                "avg_rating": 5.0,
                "total_responses": 9,
            },
            {
                "organisation_name": "Org A",
                "target": "therapists",
                "avg_rating": 2.0,
                "total_responses": 3,
            },
            {
                "organisation_name": "Org B",
                "target": "therapists",
                "avg_rating": 4.0,
                "total_responses": 1,
            },
        ]
    )

    result = merger.build_global_summary(
        org_summary,
        pd.DataFrame([{"organisation_name": "Org A", "total_groups": 2}]),
        star_ratings,
    )

    assert result["overall_groups_avg_rating"] == 4.6
    assert result["overall_therapists_avg_rating"] == 2.5


def test_global_summary_with_single_organisation_input() -> None:
    org_summary = pd.DataFrame(
        [
            {
                "organisation_name": "Org A",
                "total_users": 3,
                "completed_sessions": 4,
            }
        ]
    )

    result = merger.build_global_summary(
        org_summary,
        pd.DataFrame([{"organisation_name": "Org A", "total_groups": 2}]),
        _empty(["organisation_name", "target", "avg_rating", "total_responses"]),
    )

    assert result["total_organisations"] == 1
    assert result["total_users"] == 3
    assert result["total_groups_created"] == 2
    assert result["total_completed_sessions"] == 4


def test_global_summary_falls_back_to_org_averages_without_star_ratings() -> None:
    org_summary = pd.DataFrame(
        [
            {
                "organisation_name": "Org A",
                "total_users": 1,
                "completed_sessions": 2,
                "groups_avg_rating": 1.0,
                "therapists_avg_rating": 0.0,
            },
            {
                "organisation_name": "Org B",
                "total_users": 1,
                "completed_sessions": 4,
                "groups_avg_rating": 5.0,
                "therapists_avg_rating": 4.0,
            },
        ]
    )

    result = merger.build_global_summary(
        org_summary,
        pd.DataFrame(columns=["organisation_name", "total_groups"]),
    )

    assert result["overall_groups_avg_rating"] == 3.0
    assert result["overall_therapists_avg_rating"] == 4.0


def test_build_monthly_rating_summary_weights_ratings_by_response_count() -> None:
    monthly_ratings = pd.DataFrame(
        [
            {
                "month": "2026-05",
                "organisation_name": "Org A",
                "target": "groups",
                "avg_rating": 1.0,
                "total_responses": 1,
            },
            {
                "month": "2026-05",
                "organisation_name": "Org B",
                "target": "groups",
                "avg_rating": 5.0,
                "total_responses": 9,
            },
        ]
    )

    result = merger.build_monthly_rating_summary(monthly_ratings)

    assert result.to_dict("records") == [
        {"month": "2026-05", "target": "groups", "avg_rating": 4.6}
    ]


def test_monthly_bundle_creation_summary_aggregates_orgs_and_zero_fills() -> None:
    monthly_creations = pd.DataFrame(
        [
            {"month": "2026-01", "organisation_name": "Org A", "bundles_created": 2},
            {"month": "2026-01", "organisation_name": "Org B", "bundles_created": 3},
            {"month": "2026-03", "organisation_name": "Org A", "bundles_created": 1},
        ]
    )

    result = merger.build_monthly_bundle_creation_summary(
        monthly_creations, date(2026, 1, 15), date(2026, 3, 2)
    )

    assert result.to_dict("records") == [
        {"month": "2026-01", "bundles_created": 5},
        {"month": "2026-02", "bundles_created": 0},
        {"month": "2026-03", "bundles_created": 1},
    ]


def test_monthly_bundle_creation_summary_zero_fills_empty_period() -> None:
    result = merger.build_monthly_bundle_creation_summary(
        _empty(["month", "organisation_name", "bundles_created"]),
        date(2026, 1, 1),
        date(2026, 2, 28),
    )

    assert result.to_dict("records") == [
        {"month": "2026-01", "bundles_created": 0},
        {"month": "2026-02", "bundles_created": 0},
    ]


def test_build_monthly_question_rating_summary_keeps_questions_separate() -> None:
    monthly_ratings = pd.DataFrame(
        [
            {
                "month": "2026-05",
                "organisation_name": "Org A",
                "target": "groups",
                "question_label": "Session enjoyment",
                "avg_rating": 1.0,
                "total_responses": 1,
            },
            {
                "month": "2026-05",
                "organisation_name": "Org B",
                "target": "groups",
                "question_label": "Session enjoyment",
                "avg_rating": 5.0,
                "total_responses": 9,
            },
            {
                "month": "2026-05",
                "organisation_name": "Org A",
                "target": "groups",
                "question_label": "Activity engagement",
                "avg_rating": 3.0,
                "total_responses": 2,
            },
        ]
    )

    result = merger.build_monthly_question_rating_summary(monthly_ratings)

    assert result.to_dict("records") == [
        {
            "month": "2026-05",
            "target": "groups",
            "question_label": "Activity engagement",
            "avg_rating": 3.0,
        },
        {
            "month": "2026-05",
            "target": "groups",
            "question_label": "Session enjoyment",
            "avg_rating": 4.6,
        },
    ]


def test_build_monthly_question_rating_summary_requires_question_labels() -> None:
    result = merger.build_monthly_question_rating_summary(
        _empty(["month", "target", "avg_rating", "total_responses"])
    )

    assert list(result.columns) == ["month", "target", "question_label", "avg_rating"]
    assert result.empty


# ── build_daily_visit_activity ────────────────────────────────────────────────

def _visits(*rows: tuple) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["user_id", "visit_date"])


def test_daily_visit_activity_zero_fills_all_dates_in_period() -> None:
    result = merger.build_daily_visit_activity(
        _visits(),
        date(2026, 6, 1),
        date(2026, 6, 5),
    )
    assert list(result["date"]) == [
        "2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"
    ]
    assert list(result["visits"]) == [0, 0, 0, 0, 0]
    assert list(result["unique_users"]) == [0, 0, 0, 0, 0]


def test_daily_visit_activity_counts_visits_and_unique_users() -> None:
    visits = _visits(
        ("u1", "2026-06-01"),
        ("u2", "2026-06-01"),
        ("u1", "2026-06-03"),
    )
    result = merger.build_daily_visit_activity(visits, date(2026, 6, 1), date(2026, 6, 3))
    assert result.to_dict("records") == [
        {"date": "2026-06-01", "visits": 2, "unique_users": 2},
        {"date": "2026-06-02", "visits": 0, "unique_users": 0},
        {"date": "2026-06-03", "visits": 1, "unique_users": 1},
    ]


def test_daily_visit_activity_same_user_multiple_visits_one_day() -> None:
    visits = _visits(
        ("u1", "2026-06-01"),
        ("u1", "2026-06-01"),
        ("u1", "2026-06-01"),
    )
    result = merger.build_daily_visit_activity(visits, date(2026, 6, 1), date(2026, 6, 1))
    assert result.iloc[0]["visits"] == 3
    assert result.iloc[0]["unique_users"] == 1


def test_daily_visit_activity_single_date_period() -> None:
    visits = _visits(("u1", "2026-06-01"))
    result = merger.build_daily_visit_activity(visits, date(2026, 6, 1), date(2026, 6, 1))
    assert len(result) == 1
    assert result.iloc[0]["visits"] == 1
    assert result.iloc[0]["unique_users"] == 1


def test_bundle_progression_uses_actual_configured_sessions_and_first_completions() -> None:
    bundles = pd.DataFrame([
        {
            "bundle_id": "101",
            "bundle_name": "Short programme",
            "organisation_name": "Org A",
            "configured_session_ids": ["s1", "s2", "s3"],
        },
        {
            "bundle_id": "102",
            "bundle_name": "Complete programme",
            "organisation_name": "Org A",
            "configured_session_ids": ["s1"],
        },
    ])
    completions = pd.DataFrame([
        {"visit_id": "v1", "bundle_id": "101", "session_id": "s1", "completion_date": "2026-01-01"},
        {"visit_id": "v1", "bundle_id": "101", "session_id": "s1", "completion_date": "2026-01-01"},
        {"visit_id": "v2", "bundle_id": "101", "session_id": "s1", "completion_date": "2026-01-03"},
        {"visit_id": "v3", "bundle_id": "101", "session_id": "s2", "completion_date": "2026-01-11"},
        {"visit_id": "v4", "bundle_id": "101", "session_id": "not-configured", "completion_date": "2026-01-12"},
        {"visit_id": "v5", "bundle_id": "102", "session_id": "s1", "completion_date": "2026-02-01"},
    ])

    result = merger.build_bundle_progression(
        bundles, completions, as_of_date=date(2026, 2, 15)
    ).set_index("bundle_id")

    assert result.loc["101", "progress"] == "2 / 3"
    assert result.loc["101", "completed_configured_sessions"] == 2
    assert result.loc["101", "total_configured_sessions"] == 3
    assert result.loc["101", "avg_days_between_completions"] == 10.0
    assert result.loc["101", "status"] == "Stalled 30+ days"
    assert result.loc["102", "progress"] == "1 / 1"
    assert result.loc["102", "status"] == "Complete"


def test_bundle_progression_flags_60_day_stalls_and_not_started_bundles() -> None:
    bundles = pd.DataFrame([
        {
            "bundle_id": "old",
            "bundle_name": "Old",
            "organisation_name": "Org A",
            "configured_session_ids": ["s1", "s2"],
        },
        {
            "bundle_id": "new",
            "bundle_name": "New",
            "organisation_name": "Org B",
            "configured_session_ids": ["s1"],
        },
    ])
    completions = pd.DataFrame([{
        "visit_id": "v1", "bundle_id": "old", "session_id": "s1",
        "completion_date": "2026-01-01",
    }])

    result = merger.build_bundle_progression(
        bundles, completions, as_of_date=date(2026, 3, 15)
    ).set_index("bundle_id")

    assert result.loc["old", "status"] == "Stalled 60+ days"
    assert result.loc["new", "status"] == "Not started"
    assert pd.isna(result.loc["new", "days_since_last_completion"])


def test_bundle_progression_counts_completion_when_date_is_missing() -> None:
    bundles = pd.DataFrame([{
        "bundle_id": "101",
        "bundle_name": "Programme",
        "organisation_name": "Org A",
        "configured_session_ids": ["s1", "s2"],
    }])
    completions = pd.DataFrame([{
        "visit_id": "v1", "bundle_id": "101", "session_id": "s1",
        "completion_date": None,
    }])

    result = merger.build_bundle_progression(
        bundles, completions, as_of_date=date(2026, 3, 15)
    ).iloc[0]

    assert result["progress"] == "1 / 2"
    assert result["status"] == "In progress"
    assert pd.isna(result["days_since_last_completion"])


def test_org_summary_adds_full_programme_positive_indicator() -> None:
    org_summary = pd.DataFrame([
        {"organisation_name": "Org A"},
        {"organisation_name": "Org B"},
    ])
    progression = pd.DataFrame([
        {"organisation_name": "Org A", "status": "Complete"},
        {"organisation_name": "Org A", "status": "Complete"},
        {"organisation_name": "Org B", "status": "In progress"},
    ])

    result = merger.add_bundle_progression_to_org_summary(
        org_summary, progression
    ).set_index("organisation_name")

    assert result.loc["Org A", "full_programmes"] == 2
    assert result.loc["Org B", "full_programmes"] == 0
