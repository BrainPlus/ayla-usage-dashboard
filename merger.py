# Pandas joins and aggregations: merges Matomo analytics with PostgreSQL user/org data.
# No database or Matomo calls here — all inputs are DataFrames.

from datetime import date

import pandas as pd

_NO_USAGE = "No tracked usage"
_NO_ORG = "Unassigned / No organisation"
_UNKNOWN = "Unknown"
_REAL_SESSION_MIN_SECONDS = 20 * 60


def build_user_detail(
    db_users: pd.DataFrame,
    logins: pd.DataFrame,
    last_login: pd.DataFrame,
    visit_durations: pd.DataFrame,
    activity_completions: pd.DataFrame,
) -> pd.DataFrame:
    """
    Builds the per-user detail table by left-joining all Matomo metrics onto the
    canonical user list from the database.

    Args:
        db_users:              user_id, email, organisation_name, country, sector
        logins:                user_id, visits
        last_login:            user_id, last_login_date
        visit_durations:       user_id, visit_duration_seconds, has_deliver_action
        activity_completions:  user_id, activities_completed

    Returns:
        DataFrame with columns:
            user_id, email, organisation_name, country, sector, last_login_date,
            logins, avg_real_session_minutes,
            median_prepare_minutes, short_visit_count, activities_completed
    """
    df = db_users.copy()
    for column in ("country", "sector"):
        if column not in df:
            df[column] = _UNKNOWN
        df[column] = df[column].fillna(_UNKNOWN)
    duration_metrics = _build_visit_duration_metrics(visit_durations)

    df = df.merge(
        logins.rename(columns={"visits": "logins"}),
        on="user_id", how="left",
    )
    df = df.merge(last_login, on="user_id", how="left")
    df = df.merge(duration_metrics, on="user_id", how="left")
    df = df.merge(activity_completions, on="user_id", how="left")

    df["logins"] = df["logins"].fillna(0).astype(int)
    df["last_login_date"] = df["last_login_date"].fillna(_NO_USAGE)
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
    df["activities_completed"] = df["activities_completed"].fillna(0).astype(int)

    df = df.sort_values(["organisation_name", "email"]).reset_index(drop=True)

    return df[[
        "user_id",
        "email",
        "organisation_name",
        "country",
        "sector",
        "last_login_date",
        "logins",
        "avg_real_session_minutes",
        "median_prepare_minutes",
        "short_visit_count",
        "activities_completed",
    ]]


def build_org_summary(
    user_detail: pd.DataFrame,
    sessions_delivered: pd.DataFrame,
    star_ratings: pd.DataFrame,
    org_user_counts: pd.DataFrame,
    visit_durations: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Builds the per-organisation summary table.

    Sessions delivered are counted as unique (bundle_id, session_id) pairs —
    deduplicate before passing in if needed.

    Args:
        user_detail:            output of build_user_detail
        sessions_delivered:     bundle_id, session_id, user_id
        star_ratings:           organisation_name, target, avg_rating, total_responses
        org_user_counts:        organisation_name, user_count
        visit_durations:        user_id, visit_duration_seconds, has_deliver_action
                                (raw visits — used for org-level min/max real session time)

    Returns:
        DataFrame with columns:
            organisation_name, country, sector, total_users, active_users,
            logins, avg_real_session_minutes,
            median_prepare_minutes, min_real_session_minutes, max_real_session_minutes,
            short_visit_count, sessions_delivered,
            last_login_date, groups_avg_rating, therapists_avg_rating
    """
    # --- aggregate user_detail by org ---
    # Exclude sentinel before taking max so real dates win
    real_logins = user_detail[user_detail["last_login_date"] != _NO_USAGE]
    org_dimensions = ["organisation_name", "country", "sector"]
    last_login_by_org = (
        real_logins.groupby(org_dimensions)["last_login_date"]
        .max()
        .reset_index()
    )

    agg = user_detail.groupby(org_dimensions).agg(
        logins=("logins", "sum"),
        median_prepare_minutes=("median_prepare_minutes", lambda s: s[s > 0].median()),
        short_visit_count=("short_visit_count", "sum"),
        active_users=("logins", lambda s: (s >= 2).sum()),
    ).reset_index()

    agg["median_prepare_minutes"] = agg["median_prepare_minutes"].round(1)
    agg = agg.merge(last_login_by_org, on=org_dimensions, how="left")
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

    session_counts = _session_counts(sessions_delivered).rename(
        columns={"sessions": "sessions_delivered"}
    )
    agg = agg.merge(session_counts, on="organisation_name", how="left")

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
        "sessions_delivered",
    ]
    agg[numeric_cols] = agg[numeric_cols].fillna(0).astype(int)
    agg["median_prepare_minutes"] = agg["median_prepare_minutes"].fillna(0.0)
    agg["groups_avg_rating"] = agg["groups_avg_rating"].fillna(0.0).round(2)
    agg["therapists_avg_rating"] = agg["therapists_avg_rating"].fillna(0.0).round(2)

    denom = agg["sessions_delivered"].replace(0, pd.NA)
    agg["avg_activities_per_session"] = (
        (agg["total_activities_completed"] / denom).fillna(0.0).round(1)
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
        "country",
        "sector",
        "total_users",
        "active_users",
        "logins",
        "avg_real_session_minutes",
        "median_prepare_minutes",
        "min_real_session_minutes",
        "max_real_session_minutes",
        "short_visit_count",
        "sessions_delivered",
        "avg_activities_per_session",
        "last_login_date",
        "groups_avg_rating",
        "therapists_avg_rating",
    ]]


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
            total_sessions_delivered (int)
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
        "total_sessions_delivered": int(org_summary["sessions_delivered"].sum()),
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
