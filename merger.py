# Pandas joins and aggregations: merges Matomo analytics with PostgreSQL user/org data.
# No database or Matomo calls here — all inputs are DataFrames.

from datetime import date

import pandas as pd

_NO_USAGE = "No tracked usage"
_NO_RECENT_SESSION = "No recent session"
_NO_SESSIONS = "No sessions"
_NO_ORG = "Unassigned / No organisation"
_REAL_SESSION_MIN_SECONDS = 20 * 60


def build_user_detail(
    db_users: pd.DataFrame,
    logins: pd.DataFrame,
    last_login: pd.DataFrame,
    visit_durations: pd.DataFrame,
    activity_completions: pd.DataFrame,
    completed_sessions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Builds the per-user detail table by left-joining all Matomo metrics onto the
    canonical user list from the database.

    Args:
        db_users:              user_id, email, organisation_name
        logins:                user_id, visits
        last_login:            user_id, last_login_date
        visit_durations:       user_id, visit_duration_seconds, has_deliver_action
        activity_completions:  user_id, activities_completed
        completed_sessions:    visit_id, bundle_id, session_id, user_id

    Returns:
        DataFrame with columns:
            user_id, email, organisation_name, last_login_date,
            logins, avg_real_session_minutes,
            median_prepare_minutes, short_visit_count, completed_sessions,
            activities_completed
    """
    df = db_users.copy()
    duration_metrics = _build_visit_duration_metrics(visit_durations)

    df = df.merge(
        logins.rename(columns={"visits": "logins"}),
        on="user_id", how="left",
    )
    df = df.merge(last_login, on="user_id", how="left")
    df = df.merge(duration_metrics, on="user_id", how="left")
    df = df.merge(activity_completions, on="user_id", how="left")
    if completed_sessions is not None:
        completed_by_user = (
            _deduplicate_completed_sessions(completed_sessions)
            .groupby("user_id")
            .size()
            .reset_index(name="completed_sessions")
        )
        df = df.merge(completed_by_user, on="user_id", how="left")
    else:
        df["completed_sessions"] = 0

    df["logins"] = df["logins"].fillna(0).astype(int)
    df["last_login_date"] = df["last_login_date"].replace("", pd.NA).fillna(_NO_USAGE)
    df["avg_real_session_minutes"] = (
        pd.to_numeric(df["avg_real_session_minutes"], errors="coerce")
        .fillna(0.0)
        .astype(float)
    )
    df["median_prepare_minutes"] = (
        pd.to_numeric(df["median_prepare_minutes"], errors="coerce")
        .fillna(0.0)
        .astype(float)
    )
    df["short_visit_count"] = df["short_visit_count"].fillna(0).astype(int)
    df["completed_sessions"] = df["completed_sessions"].fillna(0).astype(int)
    df["activities_completed"] = df["activities_completed"].fillna(0).astype(int)

    df = df.sort_values(["organisation_name", "email"]).reset_index(drop=True)

    return df[[
        "user_id",
        "email",
        "organisation_name",
        "last_login_date",
        "logins",
        "avg_real_session_minutes",
        "median_prepare_minutes",
        "short_visit_count",
        "completed_sessions",
        "activities_completed",
    ]]


def build_org_summary(
    user_detail: pd.DataFrame,
    completed_sessions: pd.DataFrame,
    star_ratings: pd.DataFrame,
    org_user_counts: pd.DataFrame,
    visit_durations: pd.DataFrame | None = None,
    delivery_funnel: pd.DataFrame | None = None,
    recent_completed_sessions: pd.DataFrame | None = None,
    as_of_date: date | None = None,
    feedback_submissions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Builds the per-organisation summary table.

    Completed sessions are deduplicated by (visit_id, bundle_id, session_id).

    Args:
        user_detail:            output of build_user_detail
        completed_sessions:     visit_id, bundle_id, session_id, user_id
        star_ratings:           organisation_name, target, avg_rating, total_responses
        org_user_counts:        organisation_name, user_count
        visit_durations:        user_id, visit_duration_seconds, has_deliver_action
                                (raw visits — used for org-level min/max real session time)
        delivery_funnel:        session instances with deliver_selected,
                                active_delivery, and completed_session signals
        recent_completed_sessions:
                                last-365-day completed sessions with completion_date
        as_of_date:              date used to calculate session recency (defaults to today)
        feedback_submissions:    organisation_name, target, bundle_id, session_id,
                                 has_comment

    Returns:
        DataFrame with columns:
            organisation_name, total_users, active_users,
            logins, avg_real_session_minutes,
            median_prepare_minutes, min_real_session_minutes, max_real_session_minutes,
            short_visit_count, completed_sessions,
            last_login_date, groups_avg_rating, therapists_avg_rating
    """
    # --- aggregate user_detail by org ---
    # Exclude sentinel before taking max so real dates win
    real_logins = user_detail[user_detail["last_login_date"] != _NO_USAGE]
    last_login_by_org = (
        real_logins.groupby("organisation_name")["last_login_date"]
        .max()
        .reset_index()
    )

    agg = user_detail.groupby("organisation_name").agg(
        logins=("logins", "sum"),
        median_prepare_minutes=("median_prepare_minutes", lambda s: s[s > 0].median()),
        short_visit_count=("short_visit_count", "sum"),
        active_users=("logins", lambda s: (s >= 2).sum()),
    ).reset_index()

    agg["median_prepare_minutes"] = agg["median_prepare_minutes"].round(1)
    agg = agg.merge(last_login_by_org, on="organisation_name", how="left")
    agg["last_login_date"] = agg["last_login_date"].fillna(_NO_USAGE)

    # --- total users per org ---
    agg = agg.merge(
        org_user_counts.rename(columns={"user_count": "total_users"}),
        on="organisation_name", how="left",
    )

    # --- completed sessions: unique (visit_id, bundle_id, session_id) per org ---
    def _session_counts(sessions_df: pd.DataFrame) -> pd.DataFrame:
        if sessions_df.empty:
            return pd.DataFrame(columns=["organisation_name", "sessions"])
        # Attach org name via user_detail
        enriched = _deduplicate_completed_sessions(sessions_df).merge(
            user_detail[["user_id", "organisation_name"]].drop_duplicates(),
            on="user_id", how="left",
        )
        return (
            enriched.groupby("organisation_name")
            .size()
            .reset_index(name="sessions")
        )

    session_counts = _session_counts(completed_sessions).rename(
        columns={"sessions": "completed_sessions"}
    )
    agg = agg.merge(session_counts, on="organisation_name", how="left")

    # --- feedback coverage: unique bundle/session pairs per org ---
    completed_pairs = completed_sessions.merge(
        user_detail[["user_id", "organisation_name"]].drop_duplicates(),
        on="user_id",
        how="left",
    ).drop_duplicates(
        subset=["organisation_name", "bundle_id", "session_id"]
    )
    completed_pair_counts = (
        completed_pairs.groupby("organisation_name")
        .size()
        .to_dict()
    )
    submission_columns = [
        "organisation_name",
        "target",
        "bundle_id",
        "session_id",
        "has_comment",
    ]
    submissions = (
        feedback_submissions.reindex(columns=submission_columns).copy()
        if feedback_submissions is not None
        else pd.DataFrame(columns=submission_columns)
    )
    for target, column in (
        ("groups", "group_feedback_coverage"),
        ("therapists", "therapist_feedback_coverage"),
    ):
        target_submissions = submissions[submissions["target"] == target]
        feedback_pair_counts = (
            target_submissions.dropna(subset=["bundle_id", "session_id"])
            .drop_duplicates(
                subset=["organisation_name", "bundle_id", "session_id"]
            )
            .groupby("organisation_name")
            .size()
            .to_dict()
        )
        agg[column] = agg["organisation_name"].map(
            lambda org: _format_coverage_rate(
                feedback_pair_counts.get(org, 0),
                completed_pair_counts.get(org, 0),
            )
        )

    therapist_submissions = submissions[submissions["target"] == "therapists"].copy()
    if not therapist_submissions.empty:
        therapist_submissions["has_comment"] = (
            therapist_submissions["has_comment"].fillna(False).astype(bool)
        )
        therapist_comment_counts = (
            therapist_submissions.groupby("organisation_name")["has_comment"]
            .agg(["sum", "count"])
            .to_dict("index")
        )
    else:
        therapist_comment_counts = {}
    agg["therapist_comment_rate"] = agg["organisation_name"].map(
        lambda org: (
            _NO_SESSIONS
            if completed_pair_counts.get(org, 0) == 0
            else _format_percentage(
                therapist_comment_counts.get(org, {}).get("sum", 0),
                therapist_comment_counts.get(org, {}).get("count", 0),
            )
        )
    )

    # --- days since last completed session: same deduplication as completed sessions ---
    if recent_completed_sessions is not None and not recent_completed_sessions.empty:
        recent = recent_completed_sessions.copy()
        recent["completion_date"] = pd.to_datetime(
            recent["completion_date"], errors="coerce"
        ).dt.normalize()
        recent = _deduplicate_completed_sessions(
            recent.sort_values("completion_date", ascending=False)
        ).merge(
            user_detail[["user_id", "organisation_name"]].drop_duplicates(),
            on="user_id",
            how="left",
        )
        last_completed_by_org = (
            recent.dropna(subset=["completion_date"])
            .groupby("organisation_name", as_index=False)["completion_date"]
            .max()
        )
        reference_date = pd.Timestamp(as_of_date or date.today())
        last_completed_by_org["days_since_last_completed_session"] = (
            reference_date - last_completed_by_org["completion_date"]
        ).dt.days.clip(lower=0)
        agg = agg.merge(
            last_completed_by_org[
                ["organisation_name", "days_since_last_completed_session"]
            ],
            on="organisation_name",
            how="left",
        )
    else:
        agg["days_since_last_completed_session"] = pd.NA
    agg["days_since_last_completed_session"] = (
        agg["days_since_last_completed_session"]
        .astype("Int64")
        .astype("string")
        .fillna(_NO_RECENT_SESSION)
    )

    # --- delivery funnel: unique (visit_id, bundle_id, session_id) per org ---
    if delivery_funnel is not None and not delivery_funnel.empty:
        funnel = delivery_funnel.drop_duplicates(
            subset=["visit_id", "bundle_id", "session_id"]
        ).merge(
            user_detail[["user_id", "organisation_name"]].drop_duplicates(),
            on="user_id",
            how="left",
        )
        funnel_counts = (
            funnel.groupby("organisation_name", as_index=False)
            .agg(
                deliver_selected_sessions=("deliver_selected", "sum"),
                active_delivery_sessions=("active_delivery", "sum"),
            )
        )
        agg = agg.merge(funnel_counts, on="organisation_name", how="left")
    else:
        agg["deliver_selected_sessions"] = 0
        agg["active_delivery_sessions"] = 0

    # --- avg activities per session ---
    activities_by_org = (
        user_detail.groupby("organisation_name")["activities_completed"]
        .sum()
        .reset_index(name="total_activities_completed")
    )
    agg = agg.merge(activities_by_org, on="organisation_name", how="left")
    agg["total_activities_completed"] = agg["total_activities_completed"].fillna(0).astype(int)

    # --- star ratings: pivot target → groups_avg_rating / therapists_avg_rating ---
    if not star_ratings.empty:
        ratings_pivot = (
            star_ratings.pivot_table(
                index="organisation_name",
                columns="target",
                values="avg_rating",
                aggfunc="mean",
            )
            .reset_index()
        )
        ratings_pivot.columns.name = None
        ratings_pivot = ratings_pivot.rename(columns={
            "groups": "groups_avg_rating",
            "therapists": "therapists_avg_rating",
        })
        # Ensure both columns exist even if one target has no data
        for col in ("groups_avg_rating", "therapists_avg_rating"):
            if col not in ratings_pivot.columns:
                ratings_pivot[col] = float("nan")
        agg = agg.merge(ratings_pivot[["organisation_name", "groups_avg_rating", "therapists_avg_rating"]],
                        on="organisation_name", how="left")
    else:
        agg["groups_avg_rating"] = float("nan")
        agg["therapists_avg_rating"] = float("nan")

    # --- fill missing numerics ---
    numeric_cols = [
        "total_users", "active_users",
        "logins",
        "short_visit_count",
        "completed_sessions",
        "deliver_selected_sessions",
        "active_delivery_sessions",
    ]
    agg[numeric_cols] = agg[numeric_cols].fillna(0).astype(int)
    agg["deliver_to_active_dropoff"] = (
        agg["deliver_selected_sessions"] - agg["active_delivery_sessions"]
    )
    agg["deliver_to_active_dropoff_pct"] = _dropoff_percentage(
        agg["deliver_to_active_dropoff"], agg["deliver_selected_sessions"]
    )
    agg["active_to_completed_dropoff"] = (
        agg["active_delivery_sessions"] - agg["completed_sessions"]
    )
    agg["active_to_completed_dropoff_pct"] = _dropoff_percentage(
        agg["active_to_completed_dropoff"], agg["active_delivery_sessions"]
    )
    agg["median_prepare_minutes"] = agg["median_prepare_minutes"].fillna(0.0)
    agg["groups_avg_rating"] = agg["groups_avg_rating"].fillna(0.0).round(2)
    agg["therapists_avg_rating"] = agg["therapists_avg_rating"].fillna(0.0).round(2)

    denom = agg["completed_sessions"].replace(0, pd.NA)
    agg["avg_activities_per_session"] = (
        pd.to_numeric(agg["total_activities_completed"] / denom, errors="coerce")
        .fillna(0.0)
        .round(1)
    )
    agg = agg.drop(columns=["total_activities_completed"])

    # --- org-level avg/min/max real session duration from raw visits ---
    # Computed directly from individual visit durations (not from per-user averages)
    # so the org mean is properly visit-count-weighted.
    if visit_durations is not None and not visit_durations.empty:
        vd = visit_durations.copy()
        vd["user_id"] = vd["user_id"].astype(str)
        vd["visit_duration_seconds"] = pd.to_numeric(vd["visit_duration_seconds"], errors="coerce").fillna(0.0)
        vd["has_deliver_action"] = vd["has_deliver_action"].fillna(False).astype(bool)
        real_vd = vd[vd["has_deliver_action"] & (vd["visit_duration_seconds"] > _REAL_SESSION_MIN_SECONDS)]
        if not real_vd.empty:
            real_vd = real_vd.merge(
                user_detail[["user_id", "organisation_name"]].drop_duplicates(),
                on="user_id", how="left",
            )
            real_stats = (
                real_vd.groupby("organisation_name")["visit_duration_seconds"]
                .agg(
                    avg_real_session_minutes="mean",
                    min_real_session_minutes="min",
                    max_real_session_minutes="max",
                )
                .reset_index()
            )
            real_stats["avg_real_session_minutes"] = (real_stats["avg_real_session_minutes"] / 60).round(1)
            real_stats["min_real_session_minutes"] = (real_stats["min_real_session_minutes"] / 60).round(1)
            real_stats["max_real_session_minutes"] = (real_stats["max_real_session_minutes"] / 60).round(1)
            agg = agg.merge(real_stats, on="organisation_name", how="left")
        else:
            agg["avg_real_session_minutes"] = 0.0
            agg["min_real_session_minutes"] = 0.0
            agg["max_real_session_minutes"] = 0.0
    else:
        # No raw visit data: fall back to mean of per-user averages from user_detail.
        # min/max require individual visit durations and cannot be derived here.
        avg_fallback = (
            user_detail.groupby("organisation_name")["avg_real_session_minutes"]
            .apply(lambda s: s[s > 0].mean())
            .round(1)
            .reset_index(name="avg_real_session_minutes")
        )
        agg = agg.merge(avg_fallback, on="organisation_name", how="left")
        agg["min_real_session_minutes"] = 0.0
        agg["max_real_session_minutes"] = 0.0
    agg["avg_real_session_minutes"] = agg["avg_real_session_minutes"].fillna(0.0)
    agg["min_real_session_minutes"] = agg["min_real_session_minutes"].fillna(0.0)
    agg["max_real_session_minutes"] = agg["max_real_session_minutes"].fillna(0.0)

    # --- sort: alphabetical, "Unassigned / No organisation" last ---
    is_unassigned = agg["organisation_name"] == _NO_ORG
    agg = pd.concat([
        agg[~is_unassigned].sort_values("organisation_name"),
        agg[is_unassigned],
    ]).reset_index(drop=True)

    return agg[[
        "organisation_name",
        "total_users",
        "active_users",
        "logins",
        "avg_real_session_minutes",
        "median_prepare_minutes",
        "min_real_session_minutes",
        "max_real_session_minutes",
        "short_visit_count",
        "deliver_selected_sessions",
        "active_delivery_sessions",
        "completed_sessions",
        "group_feedback_coverage",
        "therapist_feedback_coverage",
        "therapist_comment_rate",
        "days_since_last_completed_session",
        "deliver_to_active_dropoff",
        "deliver_to_active_dropoff_pct",
        "active_to_completed_dropoff",
        "active_to_completed_dropoff_pct",
        "avg_activities_per_session",
        "last_login_date",
        "groups_avg_rating",
        "therapists_avg_rating",
    ]]


def _dropoff_percentage(dropoff: pd.Series, previous_stage: pd.Series) -> pd.Series:
    denominator = previous_stage.replace(0, pd.NA)
    return (
        pd.to_numeric(dropoff / denominator * 100, errors="coerce")
        .fillna(0.0)
        .round(1)
    )


def _format_coverage_rate(numerator: int, completed_pairs: int) -> str:
    if completed_pairs == 0:
        return _NO_SESSIONS
    return _format_percentage(numerator, completed_pairs)


def _format_percentage(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "0%"
    return f"{int(numerator / denominator * 100 + 0.5)}%"


def _deduplicate_completed_sessions(completed_sessions: pd.DataFrame) -> pd.DataFrame:
    """Return one completed CST session per Matomo visit, bundle, and session."""
    if completed_sessions.empty:
        return completed_sessions.copy()
    return completed_sessions.drop_duplicates(
        subset=["visit_id", "bundle_id", "session_id"]
    )


def _build_visit_duration_metrics(visit_durations: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "user_id",
        "avg_real_session_minutes",
        "median_prepare_minutes",
        "short_visit_count",
    ]
    if visit_durations.empty:
        return pd.DataFrame(columns=columns)

    visits = visit_durations.copy()
    visits["user_id"] = visits["user_id"].astype(str)
    visits["visit_duration_seconds"] = (
        pd.to_numeric(visits["visit_duration_seconds"], errors="coerce")
        .fillna(0.0)
    )
    visits["has_deliver_action"] = visits["has_deliver_action"].fillna(False).astype(bool)

    metrics = pd.DataFrame({"user_id": visits["user_id"].drop_duplicates()})

    deliver_visits = visits[visits["has_deliver_action"]]
    real_sessions = deliver_visits[
        deliver_visits["visit_duration_seconds"] > _REAL_SESSION_MIN_SECONDS
    ]
    short_visits = deliver_visits[
        deliver_visits["visit_duration_seconds"] <= _REAL_SESSION_MIN_SECONDS
    ]
    prepare_visits = visits[~visits["has_deliver_action"]]

    real_averages = (
        (real_sessions.groupby("user_id")["visit_duration_seconds"].mean() / 60)
        .round(1)
        .reset_index(name="avg_real_session_minutes")
    )
    prepare_averages = (
        (prepare_visits.groupby("user_id")["visit_duration_seconds"].median() / 60)
        .round(1)
        .reset_index(name="median_prepare_minutes")
    )
    short_counts = (
        short_visits.groupby("user_id")
        .size()
        .reset_index(name="short_visit_count")
    )

    metrics = metrics.merge(real_averages, on="user_id", how="left")
    metrics = metrics.merge(prepare_averages, on="user_id", how="left")
    metrics = metrics.merge(short_counts, on="user_id", how="left")
    metrics["avg_real_session_minutes"] = metrics["avg_real_session_minutes"].fillna(0.0)
    metrics["median_prepare_minutes"] = metrics["median_prepare_minutes"].fillna(0.0)
    metrics["short_visit_count"] = metrics["short_visit_count"].fillna(0).astype(int)
    return metrics[columns]


def build_global_summary(
    org_summary: pd.DataFrame,
    bundle_counts: pd.DataFrame,
    star_ratings: pd.DataFrame | None = None,
) -> dict:
    """
    Computes scalar totals for the Global Overview tab.

    Args:
        org_summary:    output of build_org_summary
        bundle_counts:  organisation_name, total_groups  (from database.get_bundle_counts_per_org)
        star_ratings:   optional organisation_name, target, avg_rating,
                        total_responses (from database.get_star_ratings_by_org)

    Returns:
        dict with keys:
            total_organisations (int)
            total_users (int)
            total_groups_created (int)
            total_completed_sessions (int)
            overall_groups_avg_rating (float)
            overall_therapists_avg_rating (float)
    """
    # Exclude "Unassigned" from org count — not a real organisation
    real_orgs = org_summary[org_summary["organisation_name"] != _NO_ORG]

    if star_ratings is not None:
        groups_average = _weighted_rating_average(star_ratings, "groups")
        therapists_average = _weighted_rating_average(star_ratings, "therapists")
    else:
        groups_rated = org_summary[org_summary["groups_avg_rating"] > 0]["groups_avg_rating"]
        therapists_rated = org_summary[org_summary["therapists_avg_rating"] > 0]["therapists_avg_rating"]
        groups_average = (
            round(float(groups_rated.mean()), 2) if not groups_rated.empty else 0.0
        )
        therapists_average = (
            round(float(therapists_rated.mean()), 2)
            if not therapists_rated.empty
            else 0.0
        )

    return {
        "total_organisations": int(len(real_orgs)),
        "total_users": int(org_summary["total_users"].sum()),
        "total_groups_created": int(bundle_counts["total_groups"].sum()) if not bundle_counts.empty else 0,
        "total_completed_sessions": int(org_summary["completed_sessions"].sum()),
        "total_deliver_selected_sessions": int(
            org_summary["deliver_selected_sessions"].sum()
        ) if "deliver_selected_sessions" in org_summary else 0,
        "total_active_delivery_sessions": int(
            org_summary["active_delivery_sessions"].sum()
        ) if "active_delivery_sessions" in org_summary else 0,
        "overall_groups_avg_rating": groups_average,
        "overall_therapists_avg_rating": therapists_average,
    }


def build_monthly_rating_summary(monthly_ratings: pd.DataFrame) -> pd.DataFrame:
    """Build response-weighted monthly ratings across all organisations."""
    columns = ["month", "target", "avg_rating"]
    if monthly_ratings.empty:
        return pd.DataFrame(columns=columns)

    ratings = monthly_ratings.copy()
    ratings["avg_rating"] = pd.to_numeric(ratings["avg_rating"], errors="coerce")
    ratings["total_responses"] = pd.to_numeric(
        ratings["total_responses"], errors="coerce"
    ).fillna(0)
    ratings = ratings[
        ratings["avg_rating"].notna() & (ratings["total_responses"] > 0)
    ].copy()
    if ratings.empty:
        return pd.DataFrame(columns=columns)

    ratings["rating_total"] = ratings["avg_rating"] * ratings["total_responses"]
    summary = (
        ratings.groupby(["month", "target"], as_index=False)
        .agg(rating_total=("rating_total", "sum"), total_responses=("total_responses", "sum"))
    )
    summary["avg_rating"] = (summary["rating_total"] / summary["total_responses"]).round(2)
    return summary[columns]


def build_monthly_bundle_creation_summary(
    monthly_bundle_creations: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Aggregate bundle creations across the selected scope and zero-fill months."""
    columns = ["month", "bundles_created"]
    months = pd.period_range(start=start_date, end=end_date, freq="M").astype(str)
    summary = pd.DataFrame({"month": months})

    if monthly_bundle_creations.empty:
        summary["bundles_created"] = 0
        return summary[columns]

    creations = monthly_bundle_creations.copy()
    creations["bundles_created"] = pd.to_numeric(
        creations["bundles_created"], errors="coerce"
    ).fillna(0)
    totals = (
        creations.groupby("month", as_index=False)["bundles_created"]
        .sum()
    )
    summary = summary.merge(totals, on="month", how="left")
    summary["bundles_created"] = summary["bundles_created"].fillna(0).astype(int)
    return summary[columns]


def build_monthly_question_rating_summary(monthly_ratings: pd.DataFrame) -> pd.DataFrame:
    """Build response-weighted monthly ratings for each feedback question."""
    columns = ["month", "target", "question_label", "avg_rating"]
    if monthly_ratings.empty or "question_label" not in monthly_ratings.columns:
        return pd.DataFrame(columns=columns)

    ratings = monthly_ratings.copy()
    ratings["avg_rating"] = pd.to_numeric(ratings["avg_rating"], errors="coerce")
    ratings["total_responses"] = pd.to_numeric(
        ratings["total_responses"], errors="coerce"
    ).fillna(0)
    ratings = ratings[
        ratings["question_label"].notna()
        & ratings["avg_rating"].notna()
        & (ratings["total_responses"] > 0)
    ].copy()
    if ratings.empty:
        return pd.DataFrame(columns=columns)

    ratings["rating_total"] = ratings["avg_rating"] * ratings["total_responses"]
    summary = (
        ratings.groupby(["month", "target", "question_label"], as_index=False)
        .agg(
            rating_total=("rating_total", "sum"),
            total_responses=("total_responses", "sum"),
        )
    )
    summary["avg_rating"] = (
        summary["rating_total"] / summary["total_responses"]
    ).round(2)
    return summary[columns]


def _weighted_rating_average(star_ratings: pd.DataFrame, target: str) -> float:
    if star_ratings.empty:
        return 0.0

    ratings = star_ratings[star_ratings["target"] == target].copy()
    ratings["avg_rating"] = pd.to_numeric(ratings["avg_rating"], errors="coerce")
    ratings["total_responses"] = pd.to_numeric(
        ratings["total_responses"], errors="coerce"
    ).fillna(0)
    ratings = ratings[
        ratings["avg_rating"].notna() & (ratings["total_responses"] > 0)
    ]
    if ratings.empty:
        return 0.0

    weighted_total = (ratings["avg_rating"] * ratings["total_responses"]).sum()
    return round(float(weighted_total / ratings["total_responses"].sum()), 2)


def build_activity_usage_table(
    activity_usage: pd.DataFrame,
    activity_catalogue: dict,
) -> pd.DataFrame:
    """
    Join activity usage counts with catalogue titles.

    Unknown IDs (not in catalogue) use the raw ID string as fallback.
    Returns a DataFrame sorted by Completions descending.

    Args:
        activity_usage:    DataFrame with columns: activity_id (str), completion_count (int),
                           optionally language (str)
        activity_catalogue: dict mapping activity_id → title from Squidex

    Returns:
        DataFrame with columns: Activity Name (str), optional Language (str),
        Completions (int)
    """
    if activity_usage.empty:
        columns = ["Activity Name", "Completions"]
        if "language" in activity_usage.columns:
            columns.insert(1, "Language")
        return pd.DataFrame(columns=columns)

    df = activity_usage.copy()
    group_columns = ["activity_id"]
    output_columns = ["Activity Name"]
    if "language" in df.columns:
        df["Language"] = df["language"].map(_normalise_activity_language)
        group_columns.append("Language")
        output_columns.append("Language")

    df["completion_count"] = pd.to_numeric(
        df["completion_count"], errors="coerce",
    ).fillna(0).astype(int)
    df = (
        df.groupby(group_columns, dropna=False)["completion_count"]
        .sum()
        .reset_index()
    )
    if "Language" in df.columns:
        df["Language"] = df["Language"].map(format_activity_language_filter)
    df["Activity Name"] = df["activity_id"].map(activity_catalogue).fillna(df["activity_id"])
    df = df.rename(columns={"completion_count": "Completions"})
    output_columns.append("Completions")
    return (
        df[output_columns]
        .sort_values("Completions", ascending=False)
        .reset_index(drop=True)
    )


def build_step_completion_depth_table(
    step_completions: pd.DataFrame,
    activity_catalogue: dict,
) -> pd.DataFrame:
    """
    Summarise completion depth for activities with recorded Step Complete events.

    Completion depth is the highest completed step number in each activity
    occurrence. Least-reached steps are calculated from unique observed step
    completions per occurrence.
    """
    columns = [
        "Activity Name",
        "Language",
        "Activity Occurrences",
        "Avg Last Step Reached",
        "Completion Depth Distribution",
        "Least Reached Step(s)",
    ]
    if step_completions.empty:
        return pd.DataFrame(columns=columns)

    df = step_completions.copy()
    df["step_number"] = pd.to_numeric(df["step_number"], errors="coerce")
    df = df.dropna(subset=["activity_instance_id", "activity_id", "step_number"])
    if df.empty:
        return pd.DataFrame(columns=columns)

    df["step_number"] = df["step_number"].astype(int)
    df["Language"] = df["language"].map(_normalise_activity_language)
    df = df.drop_duplicates(
        ["activity_instance_id", "activity_id", "Language", "step_number"]
    )

    rows = []
    for (activity_id, language), activity_rows in df.groupby(
        ["activity_id", "Language"], dropna=False
    ):
        last_steps = activity_rows.groupby("activity_instance_id")["step_number"].max()
        occurrence_count = int(last_steps.size)
        depth_counts = last_steps.value_counts().sort_index()
        reach_counts = (
            activity_rows.groupby("step_number")["activity_instance_id"]
            .nunique()
            .sort_index()
        )
        least_reached_count = int(reach_counts.min())
        least_reached_steps = reach_counts[reach_counts == least_reached_count].index

        rows.append(
            {
                "Activity Name": activity_catalogue.get(str(activity_id), str(activity_id)),
                "Language": format_activity_language_filter(language),
                "Activity Occurrences": occurrence_count,
                "Avg Last Step Reached": round(float(last_steps.mean()), 1),
                "Completion Depth Distribution": "; ".join(
                    f"Step {step}: {count} ({count / occurrence_count:.0%})"
                    for step, count in depth_counts.items()
                ),
                "Least Reached Step(s)": ", ".join(
                    f"Step {step} ({least_reached_count}/{occurrence_count}, "
                    f"{least_reached_count / occurrence_count:.0%})"
                    for step in least_reached_steps
                ),
            }
        )

    return (
        pd.DataFrame(rows, columns=columns)
        .sort_values(
            ["Activity Occurrences", "Activity Name", "Language"],
            ascending=[False, True, True],
        )
        .reset_index(drop=True)
    )


def activity_language_filter_options(activity_usage: pd.DataFrame) -> list[str]:
    """Return available activity language filter values, with all languages first."""
    if activity_usage.empty or "language" not in activity_usage.columns:
        return ["all"]

    languages = {
        _normalise_activity_language(value)
        for value in activity_usage["language"].dropna()
    }
    if not languages:
        return ["all"]

    preferred_order = ["uk", "dk", "de"]
    known_languages = [
        language for language in preferred_order if language in languages
    ]
    known_languages.extend(
        sorted(
            language
            for language in languages
            if language != "unknown" and language not in preferred_order
        )
    )
    if "unknown" in languages:
        known_languages.append("unknown")
    return ["all", *known_languages]


def filter_activity_usage_by_language(
    activity_usage: pd.DataFrame,
    language_filter: str,
) -> pd.DataFrame:
    """Filter activity usage rows by normalised Matomo language code."""
    if (
        activity_usage.empty
        or language_filter == "all"
        or "language" not in activity_usage.columns
    ):
        return activity_usage.copy()

    df = activity_usage.copy()
    normalised = df["language"].map(_normalise_activity_language)
    return df[normalised == language_filter].reset_index(drop=True)


def format_activity_language_filter(language_filter: str) -> str:
    """Format activity language filter values for Streamlit controls."""
    if language_filter == "all":
        return "All"
    if language_filter == "unknown":
        return "Unknown"
    return language_filter.upper()


def activity_catalogue_match_stats(
    activity_usage: pd.DataFrame,
    activity_catalogue: dict,
) -> dict[str, int]:
    """Return match counts between Matomo activity IDs and Squidex catalogue IDs."""
    usage_ids = (
        set(activity_usage["activity_id"].dropna().astype(str))
        if "activity_id" in activity_usage.columns
        else set()
    )
    catalogue_ids = {str(key) for key in activity_catalogue.keys()}
    matched_ids = usage_ids & catalogue_ids
    return {
        "usage_ids": len(usage_ids),
        "catalogue_ids": len(catalogue_ids),
        "matched_ids": len(matched_ids),
        "unmatched_ids": len(usage_ids - catalogue_ids),
    }


def build_daily_visit_activity(
    visits: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """
    Aggregates per-visit rows into daily counts, zero-filling missing dates.

    Args:
        visits:     DataFrame with columns: user_id (str), visit_date (str "YYYY-MM-DD")
        start_date: inclusive start of the reporting period
        end_date:   inclusive end of the reporting period

    Returns:
        DataFrame with columns: date (str), visits (int), unique_users (int)
        One row per calendar day in the reporting period.
    """
    all_dates = (
        pd.date_range(start=start_date, end=end_date, freq="D")
        .strftime("%Y-%m-%d")
        .tolist()
    )
    skeleton = pd.DataFrame({"date": all_dates})

    if visits.empty:
        skeleton["visits"] = 0
        skeleton["unique_users"] = 0
        return skeleton

    df = visits.copy()
    df["visit_date"] = df["visit_date"].astype(str)
    agg = (
        df.groupby("visit_date")
        .agg(visits=("user_id", "count"), unique_users=("user_id", "nunique"))
        .reset_index()
        .rename(columns={"visit_date": "date"})
    )

    result = skeleton.merge(agg, on="date", how="left")
    result["visits"] = result["visits"].fillna(0).astype(int)
    result["unique_users"] = result["unique_users"].fillna(0).astype(int)
    return result


def build_talking_point_engagement_table(
    engagement: pd.DataFrame,
    activity_catalogue: dict,
    min_forward_clicks: int = 10,
) -> pd.DataFrame:
    """
    Build per-activity talking-point engagement ratio table.

    Ratio = Talking Point Expand Clicks / Step Forward Clicks.
    Activities with fewer than min_forward_clicks forward-clicks are excluded
    to avoid noisy ratios. The ratio is an approximation because Step Forward Click
    is used as a denominator proxy, not the true talking-points-shown count.

    Args:
        engagement:          activity_id, language, expand_clicks, forward_clicks
        activity_catalogue:  dict mapping activity_id → title
        min_forward_clicks:  minimum Step Forward Click count to include

    Returns:
        DataFrame with columns: Activity Name, Language, Expand Clicks,
        Step Forward Clicks, Approx. Engagement Ratio
    """
    columns = [
        "Activity Name",
        "Language",
        "Expand Clicks",
        "Step Forward Clicks",
        "Approx. Engagement Ratio",
    ]
    if engagement.empty:
        return pd.DataFrame(columns=columns)

    df = engagement.copy()
    df["Language"] = df["language"].map(_normalise_activity_language)
    agg = (
        df.groupby(["activity_id", "Language"], dropna=False)
        .agg(
            expand_clicks=("expand_clicks", "sum"),
            forward_clicks=("forward_clicks", "sum"),
        )
        .reset_index()
    )
    agg = agg[agg["forward_clicks"] >= min_forward_clicks].copy()
    if agg.empty:
        return pd.DataFrame(columns=columns)

    agg["Activity Name"] = (
        agg["activity_id"].map(activity_catalogue).fillna(agg["activity_id"])
    )
    agg["Language"] = agg["Language"].map(format_activity_language_filter)
    agg["Approx. Engagement Ratio"] = (
        agg["expand_clicks"] / agg["forward_clicks"]
    ).round(2)
    return (
        agg.rename(
            columns={
                "expand_clicks": "Expand Clicks",
                "forward_clicks": "Step Forward Clicks",
            }
        )[columns]
        .sort_values("Step Forward Clicks", ascending=False)
        .reset_index(drop=True)
    )


def build_media_usage_by_activity(
    media_usage: pd.DataFrame,
    activity_catalogue: dict,
) -> pd.DataFrame:
    """
    Aggregate total audio and video interactions per activity in deliver mode.

    Args:
        media_usage:        user_id, activity_id, audio_clicks, video_clicks
        activity_catalogue: dict mapping activity_id → title

    Returns:
        DataFrame with columns: Activity Name, Audio Interactions, Video Interactions
        Sorted by total interactions descending.
    """
    columns = ["Activity Name", "Audio Interactions", "Video Interactions"]
    if media_usage.empty or "activity_id" not in media_usage.columns:
        return pd.DataFrame(columns=columns)

    df = media_usage.copy()
    agg = (
        df.groupby("activity_id", dropna=False)
        .agg(
            audio_interactions=("audio_clicks", "sum"),
            video_interactions=("video_clicks", "sum"),
        )
        .reset_index()
    )
    agg = agg[(agg["audio_interactions"] > 0) | (agg["video_interactions"] > 0)]
    if agg.empty:
        return pd.DataFrame(columns=columns)

    agg["Activity Name"] = (
        agg["activity_id"].astype(str).map(activity_catalogue).fillna(agg["activity_id"])
    )
    return (
        agg.rename(columns={
            "audio_interactions": "Audio Interactions",
            "video_interactions": "Video Interactions",
        })[columns]
        .assign(_total=lambda d: d["Audio Interactions"] + d["Video Interactions"])
        .sort_values("_total", ascending=False)
        .drop(columns="_total")
        .reset_index(drop=True)
    )


def build_media_usage_by_org(
    media_usage: pd.DataFrame,
    user_detail: pd.DataFrame,
    org_session_counts: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build per-organisation audio and video interaction rates.

    All organisations from user_detail are included; those with zero media
    interactions are shown explicitly rather than excluded.

    Rate = interactions / completed sessions (0.0 when no sessions recorded).

    Args:
        media_usage:        user_id, activity_id, audio_clicks, video_clicks
        user_detail:        output of build_user_detail (must contain organisation_name)
        org_session_counts: organisation_name, completed_sessions (from org_summary)

    Returns:
        DataFrame with columns: organisation_name, completed_sessions,
        audio_clicks, video_clicks, audio_rate, video_rate
    """
    columns = [
        "organisation_name",
        "completed_sessions",
        "audio_clicks",
        "video_clicks",
        "audio_rate",
        "video_rate",
    ]
    all_orgs = user_detail[["organisation_name"]].drop_duplicates().copy()
    org_user_map = (
        user_detail[["user_id", "organisation_name"]]
        .drop_duplicates()
        .assign(user_id=lambda d: d["user_id"].astype(str))
    )

    result = all_orgs.merge(
        org_session_counts[["organisation_name", "completed_sessions"]],
        on="organisation_name", how="left",
    )
    result["completed_sessions"] = result["completed_sessions"].fillna(0).astype(int)

    if media_usage is not None and not media_usage.empty:
        media = media_usage.copy()
        media["user_id"] = media["user_id"].astype(str)
        media_with_org = media.merge(org_user_map, on="user_id", how="left")
        media_by_org = (
            media_with_org.groupby("organisation_name")
            .agg(
                audio_clicks=("audio_clicks", "sum"),
                video_clicks=("video_clicks", "sum"),
            )
            .reset_index()
        )
        result = result.merge(media_by_org, on="organisation_name", how="left")

    for col in ("audio_clicks", "video_clicks"):
        if col not in result.columns:
            result[col] = 0
        result[col] = result[col].fillna(0).astype(int)

    denom = result["completed_sessions"].replace(0, pd.NA)
    result["audio_rate"] = (result["audio_clicks"] / denom).fillna(0.0).round(2)
    result["video_rate"] = (result["video_clicks"] / denom).fillna(0.0).round(2)

    is_unassigned = result["organisation_name"] == _NO_ORG
    return (
        pd.concat([
            result[~is_unassigned].sort_values("organisation_name"),
            result[is_unassigned],
        ])
        .reset_index(drop=True)[columns]
    )


def build_engagement_events_by_org(
    engagement_events: pd.DataFrame,
    user_detail: pd.DataFrame,
    org_session_counts: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build per-organisation additional-activity and activity-replacement rates.

    All organisations from user_detail are included. Rates are expressed as
    events per completed session so organisations with different session volumes
    are comparable.

    Args:
        engagement_events:  user_id, additional_activity_count, main_replacements,
                            warmup_replacements, ro_replacements
        user_detail:        output of build_user_detail
        org_session_counts: organisation_name, completed_sessions (from org_summary)

    Returns:
        DataFrame with columns: organisation_name, completed_sessions,
        additional_activity_rate, main_replacement_rate,
        warmup_replacement_rate, ro_replacement_rate
    """
    columns = [
        "organisation_name",
        "completed_sessions",
        "additional_activity_rate",
        "main_replacement_rate",
        "warmup_replacement_rate",
        "ro_replacement_rate",
    ]
    all_orgs = user_detail[["organisation_name"]].drop_duplicates().copy()
    org_user_map = (
        user_detail[["user_id", "organisation_name"]]
        .drop_duplicates()
        .assign(user_id=lambda d: d["user_id"].astype(str))
    )

    result = all_orgs.merge(
        org_session_counts[["organisation_name", "completed_sessions"]],
        on="organisation_name", how="left",
    )
    result["completed_sessions"] = result["completed_sessions"].fillna(0).astype(int)

    raw_cols = (
        "additional_activity_count",
        "main_replacements",
        "warmup_replacements",
        "ro_replacements",
    )

    if engagement_events is not None and not engagement_events.empty:
        events = engagement_events.copy()
        events["user_id"] = events["user_id"].astype(str)
        events_with_org = events.merge(org_user_map, on="user_id", how="left")
        events_by_org = (
            events_with_org.groupby("organisation_name")
            .agg(**{c: (c, "sum") for c in raw_cols})
            .reset_index()
        )
        result = result.merge(events_by_org, on="organisation_name", how="left")

    for col in raw_cols:
        if col not in result.columns:
            result[col] = 0
        result[col] = result[col].fillna(0).astype(int)

    denom = result["completed_sessions"].replace(0, pd.NA)
    result["additional_activity_rate"] = (
        result["additional_activity_count"] / denom
    ).fillna(0.0).round(2)
    result["main_replacement_rate"] = (
        result["main_replacements"] / denom
    ).fillna(0.0).round(2)
    result["warmup_replacement_rate"] = (
        result["warmup_replacements"] / denom
    ).fillna(0.0).round(2)
    result["ro_replacement_rate"] = (
        result["ro_replacements"] / denom
    ).fillna(0.0).round(2)
    result = result.drop(columns=list(raw_cols))

    is_unassigned = result["organisation_name"] == _NO_ORG
    return (
        pd.concat([
            result[~is_unassigned].sort_values("organisation_name"),
            result[is_unassigned],
        ])
        .reset_index(drop=True)[columns]
    )


def _normalise_activity_language(value: object) -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    if not raw or raw in {"none", "nan"}:
        return "unknown"

    mappings = {
        "da": "dk",
        "da-dk": "dk",
        "dk": "dk",
        "de": "de",
        "de-de": "de",
        "en": "uk",
        "en-gb": "uk",
        "gb": "uk",
        "uk": "uk",
    }
    if raw in mappings:
        return mappings[raw]

    if "-" in raw:
        return raw.rsplit("-", 1)[-1]

    return raw
