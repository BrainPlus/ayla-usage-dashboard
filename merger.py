# Pandas joins and aggregations: merges Matomo analytics with PostgreSQL user/org data.
# No database or Matomo calls here — all inputs are DataFrames.

import pandas as pd

_NO_USAGE = "No tracked usage"
_NO_ORG = "Unassigned / No organisation"
_REAL_SESSION_MIN_SECONDS = 20 * 60


def build_user_detail(
    db_users: pd.DataFrame,
    logins_30: pd.DataFrame,
    logins_90: pd.DataFrame,
    last_login: pd.DataFrame,
    visit_durations: pd.DataFrame,
    activity_completions: pd.DataFrame,
) -> pd.DataFrame:
    """
    Builds the per-user detail table by left-joining all Matomo metrics onto the
    canonical user list from the database.

    Args:
        db_users:              user_id, email, organisation_name
        logins_30:             user_id, visits  (30-day window)
        logins_90:             user_id, visits  (90-day window)
        last_login:            user_id, last_login_date
        visit_durations:       user_id, visit_duration_seconds, has_deliver_action
        activity_completions:  user_id, activities_completed

    Returns:
        DataFrame with columns:
            user_id, email, organisation_name, last_login_date,
            logins_30_days, logins_90_days, avg_real_session_minutes,
            avg_prepare_minutes, short_visit_count, activities_completed
    """
    df = db_users.copy()
    duration_metrics = _build_visit_duration_metrics(visit_durations)

    df = df.merge(
        logins_30.rename(columns={"visits": "logins_30_days"}),
        on="user_id", how="left",
    )
    df = df.merge(
        logins_90.rename(columns={"visits": "logins_90_days"}),
        on="user_id", how="left",
    )
    df = df.merge(last_login, on="user_id", how="left")
    df = df.merge(duration_metrics, on="user_id", how="left")
    df = df.merge(activity_completions, on="user_id", how="left")

    df["logins_30_days"] = df["logins_30_days"].fillna(0).astype(int)
    df["logins_90_days"] = df["logins_90_days"].fillna(0).astype(int)
    df["last_login_date"] = df["last_login_date"].fillna(_NO_USAGE)
    df["avg_real_session_minutes"] = (
        pd.to_numeric(df["avg_real_session_minutes"], errors="coerce")
        .fillna(0.0)
        .astype(float)
    )
    df["avg_prepare_minutes"] = (
        pd.to_numeric(df["avg_prepare_minutes"], errors="coerce")
        .fillna(0.0)
        .astype(float)
    )
    df["short_visit_count"] = df["short_visit_count"].fillna(0).astype(int)
    df["activities_completed"] = df["activities_completed"].fillna(0).astype(int)

    df = df.sort_values(["organisation_name", "email"]).reset_index(drop=True)

    return df[[
        "user_id",
        "email",
        "organisation_name",
        "last_login_date",
        "logins_30_days",
        "logins_90_days",
        "avg_real_session_minutes",
        "avg_prepare_minutes",
        "short_visit_count",
        "activities_completed",
    ]]


def build_org_summary(
    user_detail: pd.DataFrame,
    sessions_delivered_30: pd.DataFrame,
    sessions_delivered_90: pd.DataFrame,
    star_ratings: pd.DataFrame,
    org_user_counts: pd.DataFrame,
) -> pd.DataFrame:
    """
    Builds the per-organisation summary table.

    Sessions delivered are counted as unique (bundle_id, session_id) pairs —
    deduplicate before passing in if needed.

    Args:
        user_detail:            output of build_user_detail
        sessions_delivered_30:  bundle_id, session_id, user_id  (30-day window)
        sessions_delivered_90:  bundle_id, session_id, user_id  (90-day window)
        star_ratings:           organisation_name, target, avg_rating, total_responses
        org_user_counts:        organisation_name, user_count

    Returns:
        DataFrame with columns:
            organisation_name, total_users, active_users_30,
            logins_30_days, logins_90_days, avg_real_session_minutes,
            avg_prepare_minutes, short_visit_count,
            sessions_delivered_30_days, sessions_delivered_90_days,
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
        logins_30_days=("logins_30_days", "sum"),
        logins_90_days=("logins_90_days", "sum"),
        avg_real_session_minutes=("avg_real_session_minutes", lambda s: s[s > 0].mean()),
        avg_prepare_minutes=("avg_prepare_minutes", lambda s: s[s > 0].mean()),
        short_visit_count=("short_visit_count", "sum"),
        active_users_30=("logins_30_days", lambda s: (s >= 2).sum()),
    ).reset_index()

    agg["avg_real_session_minutes"] = agg["avg_real_session_minutes"].round(1)
    agg["avg_prepare_minutes"] = agg["avg_prepare_minutes"].round(1)
    agg = agg.merge(last_login_by_org, on="organisation_name", how="left")
    agg["last_login_date"] = agg["last_login_date"].fillna(_NO_USAGE)

    # --- total users per org ---
    agg = agg.merge(
        org_user_counts.rename(columns={"user_count": "total_users"}),
        on="organisation_name", how="left",
    )

    # --- sessions delivered: unique (bundle_id, session_id) pairs per org ---
    def _session_counts(sessions_df: pd.DataFrame) -> pd.DataFrame:
        if sessions_df.empty:
            return pd.DataFrame(columns=["organisation_name", "sessions"])
        # Attach org name via user_detail
        enriched = sessions_df.merge(
            user_detail[["user_id", "organisation_name"]].drop_duplicates(),
            on="user_id", how="left",
        )
        return (
            enriched.drop_duplicates(subset=["organisation_name", "bundle_id", "session_id"])
            .groupby("organisation_name")
            .size()
            .reset_index(name="sessions")
        )

    s30 = _session_counts(sessions_delivered_30).rename(columns={"sessions": "sessions_delivered_30_days"})
    s90 = _session_counts(sessions_delivered_90).rename(columns={"sessions": "sessions_delivered_90_days"})

    agg = agg.merge(s30, on="organisation_name", how="left")
    agg = agg.merge(s90, on="organisation_name", how="left")

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
        "total_users", "active_users_30",
        "logins_30_days", "logins_90_days",
        "short_visit_count",
        "sessions_delivered_30_days", "sessions_delivered_90_days",
    ]
    agg[numeric_cols] = agg[numeric_cols].fillna(0).astype(int)
    agg["avg_real_session_minutes"] = agg["avg_real_session_minutes"].fillna(0.0)
    agg["avg_prepare_minutes"] = agg["avg_prepare_minutes"].fillna(0.0)
    agg["groups_avg_rating"] = agg["groups_avg_rating"].fillna(0.0).round(2)
    agg["therapists_avg_rating"] = agg["therapists_avg_rating"].fillna(0.0).round(2)

    # --- sort: alphabetical, "Unassigned / No organisation" last ---
    is_unassigned = agg["organisation_name"] == _NO_ORG
    agg = pd.concat([
        agg[~is_unassigned].sort_values("organisation_name"),
        agg[is_unassigned],
    ]).reset_index(drop=True)

    return agg[[
        "organisation_name",
        "total_users",
        "active_users_30",
        "logins_30_days",
        "logins_90_days",
        "avg_real_session_minutes",
        "avg_prepare_minutes",
        "short_visit_count",
        "sessions_delivered_30_days",
        "sessions_delivered_90_days",
        "last_login_date",
        "groups_avg_rating",
        "therapists_avg_rating",
    ]]


def _build_visit_duration_metrics(visit_durations: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "user_id",
        "avg_real_session_minutes",
        "avg_prepare_minutes",
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
        (prepare_visits.groupby("user_id")["visit_duration_seconds"].mean() / 60)
        .round(1)
        .reset_index(name="avg_prepare_minutes")
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
    metrics["avg_prepare_minutes"] = metrics["avg_prepare_minutes"].fillna(0.0)
    metrics["short_visit_count"] = metrics["short_visit_count"].fillna(0).astype(int)
    return metrics[columns]


def build_global_summary(org_summary: pd.DataFrame, bundle_counts: pd.DataFrame) -> dict:
    """
    Computes scalar totals for the Global Overview tab.

    Args:
        org_summary:    output of build_org_summary
        bundle_counts:  organisation_name, total_groups  (from database.get_bundle_counts_per_org)

    Returns:
        dict with keys:
            total_organisations (int)
            total_users (int)
            total_groups_created (int)
            total_sessions_delivered_30 (int)
            total_sessions_delivered_90 (int)
            overall_groups_avg_rating (float)
            overall_therapists_avg_rating (float)
    """
    # Exclude "Unassigned" from org count — not a real organisation
    real_orgs = org_summary[org_summary["organisation_name"] != _NO_ORG]

    # Weighted average across orgs: use 0-rated orgs only if they have responses
    groups_rated = org_summary[org_summary["groups_avg_rating"] > 0]["groups_avg_rating"]
    therapists_rated = org_summary[org_summary["therapists_avg_rating"] > 0]["therapists_avg_rating"]

    return {
        "total_organisations": int(len(real_orgs)),
        "total_users": int(org_summary["total_users"].sum()),
        "total_groups_created": int(bundle_counts["total_groups"].sum()) if not bundle_counts.empty else 0,
        "total_sessions_delivered_30": int(org_summary["sessions_delivered_30_days"].sum()),
        "total_sessions_delivered_90": int(org_summary["sessions_delivered_90_days"].sum()),
        "overall_groups_avg_rating": round(float(groups_rated.mean()), 2) if not groups_rated.empty else 0.0,
        "overall_therapists_avg_rating": round(float(therapists_rated.mean()), 2) if not therapists_rated.empty else 0.0,
    }
