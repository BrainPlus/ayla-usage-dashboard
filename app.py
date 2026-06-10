# Streamlit entry point: sidebar region selector, three-tab layout (Global Overview, By Organisation, By User).

import importlib
import inspect
import streamlit as st
from datetime import date, timedelta

import pandas as pd

import database
import matomo
import merger
import exporter

APP_REVISION = "2026-06-10-dashboard-foundation"

st.set_page_config(page_title="Ayla Usage Dashboard", layout="wide")

_OUTCOME_PROXY_QUESTION = "How do you feel after today's session?"
_OUTCOME_PROXY_CHART_LABEL = (
    f"{_OUTCOME_PROXY_QUESTION} (not a clinical outcome)"
)
_QUESTION_CHART_COLORS = {
    "groups": ["#1f77b4", "#2ca02c", "#17becf"],
    "therapists": ["#9467bd", "#17becf", "#8c564b", "#7f7f7f"],
}

_REPORT_DATA_KEYS = (
    "user_detail",
    "org_summary",
    "global_summary",
    "monthly_ratings",
    "monthly_bundle_creations",
    "bundle_filter_breakdown",
    "bundle_counts",
    "activity_catalogue",
    "activity_usage",
    "step_completion_depth",
    "talking_point_engagement",
    "media_usage",
    "engagement_events",
    "daily_visit_activity",
    "region",
    "date_range",
    "fetched_region",
    "fetched_org_id",
    "fetched_org_name",
    "fetched_date_range",
)

_OVERVIEW_METRICS = (
    (
        "total_organisations",
        "Organisations",
        "Current number of organisations represented in the report. "
        "This is not limited by the selected date range.",
    ),
    (
        "total_users",
        "Total Users",
        "Current number of registered users represented in the report. "
        "This is not limited by the selected date range.",
    ),
    (
        "total_groups_created",
        "Groups Created",
        "Current total number of groups stored for the selected organisation scope. "
        "This is not limited by the selected date range.",
    ),
    (
        "total_completed_sessions",
        "Completed Sessions",
        "Deliver-mode Session Complete events during the selected date range, "
        "deduplicated by Matomo visit + bundle + session ID.",
    ),
    (
        "overall_groups_avg_rating",
        "Avg Group Rating",
        "Response-weighted average of group ratings submitted during the selected date range.",
    ),
    (
        "overall_therapists_avg_rating",
        "Avg Therapist Rating",
        "Response-weighted average of therapist ratings submitted during the selected date range.",
    ),
)

_SECTION_HELP = {
    "overview": (
        "Summary for the selected organisation scope. Sessions and ratings use the "
        "selected date range; organisations, users, and groups are current totals."
    ),
    "logins_by_organisation": (
        "Number of Matomo visits, grouped by organisation, during the selected date "
        "range. A visit is treated as a login/browser session."
    ),
    "monthly_average_star_ratings": (
        "Response-weighted average group and therapist ratings submitted during the "
        "selected date range, grouped by calendar month."
    ),
    "monthly_bundle_creations": (
        "Bundles created during the selected reporting period, grouped by calendar "
        "month. Uses the database bundle creation timestamp."
    ),
    "bundle_filter_breakdown": (
        "Severity, age, and physical requirement preferences selected for bundles "
        "created during the reporting period. Missing preferences are shown as Not set."
    ),
    "group_feedback_by_question": (
        "Monthly response-weighted ratings for each question answered by groups. "
        "The highlighted post-session feeling question is a feedback proxy, not a "
        "clinical outcome."
    ),
    "therapist_feedback_by_question": (
        "Monthly response-weighted ratings for each question answered by therapists."
    ),
    "activity_usage": (
        "Activity Complete events recorded during the selected date range and "
        "organisation scope. Only activities completed in deliver mode are counted. "
        "Activity names come from the current Squidex catalogue."
    ),
    "step_completion_depth": (
        "How far facilitators progressed through each activity during the selected "
        "reporting period and organisation scope, based on deliver-mode Step Complete "
        "events. Low reach is a signal to investigate, not proof of a content problem."
    ),
    "by_organisation": (
        "Organisation-level details. Logins, active users, session-duration metrics, "
        "completed sessions, activity averages, and ratings use the selected date "
        "range. Total users is the current registered-user count. Last login is the "
        "most recent recorded visit found within the last 365 days."
    ),
    "talking_point_engagement": (
        "Approximate ratio of Talking Point Expand Clicks to Step Forward Clicks "
        "per activity, in deliver mode. Step Forward Click is used as a denominator "
        "proxy because Matomo does not record every talking-point shown. Activities "
        "with fewer than 10 forward-clicks in the period are excluded."
    ),
    "media_usage_by_org": (
        "Audio and video interaction events per completed session for each "
        "organisation, in deliver mode. Organisations with zero media interactions "
        "in the period are shown explicitly. Low usage may reflect connectivity, "
        "device setup, or content preferences — not necessarily a problem."
    ),
    "engagement_events_by_org": (
        "Additional-activity acceptance and activity-replacement rates per "
        "completed session for each organisation, in deliver mode. "
        "'Additional activity' fires when a facilitator accepts the prompt to run "
        "another main activity. Replacement rates track how often the default "
        "activity was swapped for an alternative. The two metrics are separate."
    ),
    "by_user": (
        "User-level details. Logins, session-duration metrics, completed sessions, "
        "and completed activities use the selected date range. User, email, and "
        "organisation are current database details. Last login is the most recent "
        "recorded visit found within the last 365 days."
    ),
    "daily_visit_activity": (
        "Daily number of Matomo visits and unique users during the selected reporting period. "
        "A Matomo visit represents one continuous browser session."
    ),
}


def _column_config_for(dataframe, column_config):
    return {
        column_name: config
        for column_name, config in column_config.items()
        if column_name in dataframe.columns
    }


def _overview_metrics(fetched_org_id):
    if fetched_org_id is None:
        return _OVERVIEW_METRICS
    return tuple(
        metric for metric in _OVERVIEW_METRICS if metric[0] != "total_organisations"
    )


def _show_logins_by_organisation(fetched_org_id) -> bool:
    return fetched_org_id is None


def _show_user_organisation_filter(fetched_org_id) -> bool:
    return fetched_org_id is None


def _show_global_bundle_creation_chart(fetched_org_id) -> bool:
    return fetched_org_id is None


def _show_organisation_bundle_creation_chart(fetched_org_id) -> bool:
    return fetched_org_id is not None


def _monthly_bundle_creation_chart(
    monthly_bundle_creations: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    summary = _build_monthly_bundle_creation_summary(
        monthly_bundle_creations, start_date, end_date
    )
    return summary.set_index("month").rename(
        columns={"bundles_created": "Bundles created"}
    )


def _bundle_filter_chart(
    bundle_filter_breakdown: pd.DataFrame,
    filter_type: str,
) -> pd.DataFrame:
    if bundle_filter_breakdown.empty:
        return pd.DataFrame(columns=["Bundles"])
    return (
        bundle_filter_breakdown[
            bundle_filter_breakdown["filter_type"] == filter_type
        ]
        .sort_values(["bundle_count", "filter_value"], ascending=[False, True])
        .set_index("filter_value")[["bundle_count"]]
        .rename(columns={"bundle_count": "Bundles"})
    )


def _render_bundle_filter_breakdown(bundle_filter_breakdown: pd.DataFrame) -> None:
    st.markdown(
        "**Bundle Filter Preferences**",
        help=_SECTION_HELP["bundle_filter_breakdown"],
    )
    if bundle_filter_breakdown.empty:
        st.info("No bundles were created in the selected reporting period.")
        return

    columns = st.columns(3)
    for column, (filter_type, label) in zip(
        columns,
        (
            ("severity", "Severity"),
            ("age", "Age"),
            ("physical_requirement", "Physical requirement"),
        ),
    ):
        column.markdown(f"**{label}**")
        column.bar_chart(_bundle_filter_chart(bundle_filter_breakdown, filter_type))


def _monthly_question_chart(monthly_ratings: pd.DataFrame, target: str):
    summary = _build_monthly_question_rating_summary(monthly_ratings)
    target_ratings = summary[summary["target"] == target]
    if target_ratings.empty:
        return pd.DataFrame(), []

    chart = target_ratings.pivot(
        index="month", columns="question_label", values="avg_rating"
    )
    chart.columns.name = None
    if _OUTCOME_PROXY_QUESTION in chart.columns:
        chart = chart.rename(
            columns={_OUTCOME_PROXY_QUESTION: _OUTCOME_PROXY_CHART_LABEL}
        )

    default_colors = _QUESTION_CHART_COLORS[target]
    colors = [
        "#ff7f0e"
        if question == _OUTCOME_PROXY_CHART_LABEL
        else default_colors[index % len(default_colors)]
        for index, question in enumerate(chart.columns)
    ]
    return chart, colors


# ── deploy-compatibility helpers ──────────────────────────────────────────────
# These wrappers guard against Streamlit's module-caching during hot deploys.
# Stale cached module objects may lack new functions or accept fewer arguments.
# Commits 18d5df5, c814074, 44be948 document when each guard was needed.

def _build_monthly_bundle_creation_summary(
    monthly_bundle_creations,
    start_date,
    end_date,
):
    global merger
    if not hasattr(merger, "build_monthly_bundle_creation_summary"):
        merger = importlib.reload(merger)
    return merger.build_monthly_bundle_creation_summary(
        monthly_bundle_creations, start_date, end_date
    )


def _get_monthly_bundle_creations(region, start_date, end_date, org_id):
    global database
    if not hasattr(database, "get_monthly_bundle_creations"):
        database = importlib.reload(database)
    return database.get_monthly_bundle_creations(
        region, start_date, end_date, org_id=org_id
    )


def _get_bundle_filter_breakdown(region, start_date, end_date, org_id):
    global database
    if not hasattr(database, "get_bundle_filter_breakdown"):
        database = importlib.reload(database)
    return database.get_bundle_filter_breakdown(
        region, start_date, end_date, org_id=org_id
    )


def _build_monthly_question_rating_summary(monthly_ratings):
    global merger
    if not hasattr(merger, "build_monthly_question_rating_summary"):
        merger = importlib.reload(merger)
    return merger.build_monthly_question_rating_summary(monthly_ratings)


def _get_activity_usage_by_id(
    date_range: str,
    allowed_user_ids: frozenset[str] | None = None,
    org_id=None,
):
    # commit 18d5df5: reload matomo if the function or its new argument was added
    # after the cached import.
    global matomo
    if (
        not hasattr(matomo, "get_activity_usage_by_id")
        or len(inspect.signature(matomo.get_activity_usage_by_id).parameters) < 3
    ):
        matomo = importlib.reload(matomo)
    parameter_count = len(inspect.signature(matomo.get_activity_usage_by_id).parameters)
    if parameter_count >= 3:
        return matomo.get_activity_usage_by_id(date_range, allowed_user_ids, org_id)
    if parameter_count >= 2:
        return matomo.get_activity_usage_by_id(date_range, allowed_user_ids)
    return matomo.get_activity_usage_by_id(date_range)


def _build_global_summary(org_summary, bundle_counts, star_ratings):
    # commit c814074: stale merger may only accept 2 args — check signature before calling
    # so unrelated TypeErrors inside build_global_summary are not silently swallowed.
    sig = inspect.signature(merger.build_global_summary)
    if len(sig.parameters) >= 3:
        summary = merger.build_global_summary(org_summary, bundle_counts, star_ratings)
    else:
        summary = merger.build_global_summary(org_summary, bundle_counts)
    # Always recompute response-weighted ratings here so a stale merger cannot
    # return wrong values (commit 44be948).
    summary["overall_groups_avg_rating"] = _weighted_rating_average(star_ratings, "groups")
    summary["overall_therapists_avg_rating"] = _weighted_rating_average(star_ratings, "therapists")
    return summary


def _build_monthly_rating_summary(monthly_ratings):
    # commit 44be948: local copy so the chart renders even when merger is stale
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
        .agg(
            rating_total=("rating_total", "sum"),
            total_responses=("total_responses", "sum"),
        )
    )
    summary["avg_rating"] = (
        summary["rating_total"] / summary["total_responses"]
    ).round(2)
    return summary[columns]


def _weighted_rating_average(star_ratings, target):
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


def _should_clear_report(
    session_state: dict,
    current_region: str,
    current_org_id,
    current_date_range: str,
) -> bool:
    if not any(
        key in session_state
        for key in ("user_detail", "org_summary", "global_summary")
    ):
        return False
    fetched_region = session_state.get("fetched_region")
    fetched_org_id = session_state.get("fetched_org_id")
    fetched_date_range = session_state.get("fetched_date_range")
    return (
        fetched_region != current_region
        or fetched_org_id != current_org_id
        or fetched_date_range != current_date_range
    )


def _database_user_ids(db_users: pd.DataFrame) -> frozenset[str]:
    return frozenset(db_users["user_id"].astype(str))


def _filter_to_database_users(
    df: pd.DataFrame,
    database_user_ids: frozenset[str],
) -> pd.DataFrame:
    """Apply the selected database scope before aggregating raw Matomo rows."""
    if "user_id" not in df.columns:
        return df
    return df[df["user_id"].astype(str).isin(database_user_ids)].reset_index(drop=True)


def _last_login_user_ids(
    db_users: pd.DataFrame,
) -> list[str]:
    return sorted(set(db_users["user_id"].astype(str)))


# ── cached Matomo wrappers ────────────────────────────────────────────────────
# get_last_login_per_user is intentionally not cached: it drives a live progress bar.

@st.cache_data(ttl=3600)
def _cached_logins(date_range: str):
    return matomo.get_logins_by_date_range(date_range)


@st.cache_data(ttl=3600)
def _cached_completed_sessions(date_range: str, region: str, org_id):
    return matomo.get_completed_sessions(date_range, org_id=org_id)


@st.cache_data(ttl=3600)
def _cached_activity_completions(date_range: str, region: str, org_id):
    return matomo.get_activity_completions_per_user(date_range, org_id=org_id)


@st.cache_data(ttl=3600)
def _cached_activity_catalogue() -> dict:
    import squidex
    settings = squidex.get_settings_from_secrets(st.secrets)
    if settings is None:
        return {}
    base_url, project, client_id, client_secret = settings
    try:
        token = squidex.get_access_token(base_url, client_id, client_secret)
        return squidex.get_activity_catalogue(base_url, project, token)
    except Exception:
        return {}


@st.cache_data(ttl=3600)
def _cached_activity_usage(
    date_range: str,
    region: str,
    org_id,
    allowed_user_ids: frozenset[str] | None,
):
    return _get_activity_usage_by_id(date_range, allowed_user_ids, org_id)


@st.cache_data(ttl=3600)
def _cached_step_completion_depth(
    date_range: str,
    region: str,
    org_id,
    allowed_user_ids: frozenset[str] | None,
):
    return matomo.get_step_completion_depth(date_range, allowed_user_ids, org_id)


@st.cache_data(ttl=3600)
def _cached_visit_durations(date_range: str, region: str, org_id):
    return matomo.get_visit_durations(date_range, org_id=org_id)


@st.cache_data(ttl=3600)
def _cached_visit_dates(date_range: str, region: str, org_id):
    return matomo.get_visit_dates(date_range, org_id=org_id)


@st.cache_data(ttl=3600)
def _cached_talking_point_engagement(
    date_range: str,
    region: str,
    org_id,
    allowed_user_ids: frozenset[str] | None,
):
    return matomo.get_talking_point_engagement(date_range, allowed_user_ids, org_id)


@st.cache_data(ttl=3600)
def _cached_media_usage(
    date_range: str,
    region: str,
    org_id,
    allowed_user_ids: frozenset[str] | None,
):
    return matomo.get_media_usage(date_range, allowed_user_ids, org_id)


@st.cache_data(ttl=3600)
def _cached_engagement_events(
    date_range: str,
    region: str,
    org_id,
    allowed_user_ids: frozenset[str] | None,
):
    return matomo.get_engagement_events(date_range, allowed_user_ids, org_id)


@st.cache_data(ttl=3600)
def _cached_organisations(region: str) -> pd.DataFrame:
    return database.get_organisations(region)


# ── sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("Ayla Usage Dashboard")

    region = st.selectbox("Region", ["eu", "uk"])

    orgs_df = _cached_organisations(region)
    org_options = (
        ["All organisations"]
        + orgs_df["organisation_name"].tolist()
        + ["Unassigned / No organisation"]
    )
    selected_org_name = st.selectbox(
        "Organisation", org_options, key=f"org_selector_{region}"
    )
    if selected_org_name == "All organisations":
        selected_org_id = None
    elif selected_org_name == "Unassigned / No organisation":
        selected_org_id = "unassigned"
    else:
        selected_org_id = int(
            orgs_df.loc[
                orgs_df["organisation_name"] == selected_org_name,
                "organisation_id",
            ].iloc[0]
        )

    today = date.today()

    start_date = st.date_input("From", today - timedelta(days=90), key="start_date")
    end_date = st.date_input("To", today, key="end_date")

    pull = st.button("Pull Data", type="primary")
    st.caption("Pulling last login data may take a few minutes")

if start_date > end_date:
    st.error("'From' date must be on or before 'To' date.")
    st.stop()

date_range = f"{start_date},{end_date}"

if _should_clear_report(
    st.session_state,
    region,
    selected_org_id,
    date_range,
):
    for key in _REPORT_DATA_KEYS:
        st.session_state.pop(key, None)

# ── data fetching ─────────────────────────────────────────────────────────────

if pull:
    try:
        # Step 1 — DB queries (fast)
        with st.spinner("Querying database..."):
            db_users = database.load_users_and_orgs(
                region,
                org_id=selected_org_id,
            )
            org_user_counts = database.get_org_user_counts(
                region, org_id=selected_org_id
            )
            bundle_counts = database.get_bundle_counts_per_org(
                region, org_id=selected_org_id
            )
            monthly_bundle_creations = _get_monthly_bundle_creations(
                region, start_date, end_date, org_id=selected_org_id,
            )
            bundle_filter_breakdown = _get_bundle_filter_breakdown(
                region, start_date, end_date, org_id=selected_org_id,
            )
            star_ratings = database.get_star_ratings_by_org(
                region, start_date, end_date, org_id=selected_org_id,
            )
            monthly_ratings = database.get_monthly_star_ratings(
                region, start_date, end_date, org_id=selected_org_id,
            )
            database_user_ids = _database_user_ids(db_users)

        # Step 2 — Matomo queries (cached after first run)
        with st.spinner("Fetching Matomo analytics..."):
            logins = _cached_logins(date_range)
            completed_sessions = _cached_completed_sessions(
                date_range, region, selected_org_id
            )
            activity_completions = _cached_activity_completions(
                date_range, region, selected_org_id
            )
            activity_catalogue = _cached_activity_catalogue()
            activity_usage = _cached_activity_usage(
                date_range, region, selected_org_id, database_user_ids
            )
            step_completion_depth = _cached_step_completion_depth(
                date_range, region, selected_org_id, database_user_ids
            )
            visit_durations = _cached_visit_durations(
                date_range, region, selected_org_id
            )
            visit_dates = _cached_visit_dates(date_range, region, selected_org_id)
            talking_point_engagement = _cached_talking_point_engagement(
                date_range, region, selected_org_id, database_user_ids
            )
            media_usage = _cached_media_usage(
                date_range, region, selected_org_id, database_user_ids
            )
            engagement_events = _cached_engagement_events(
                date_range, region, selected_org_id, database_user_ids
            )

        # Raw aggregates must be scoped to selected-region DB users before aggregation.
        logins = _filter_to_database_users(logins, database_user_ids)
        completed_sessions = _filter_to_database_users(
            completed_sessions, database_user_ids
        )
        activity_completions = _filter_to_database_users(
            activity_completions, database_user_ids
        )
        step_completion_depth = _filter_to_database_users(
            step_completion_depth, database_user_ids
        )
        visit_durations = _filter_to_database_users(
            visit_durations, database_user_ids
        )
        visit_dates = _filter_to_database_users(visit_dates, database_user_ids)
        media_usage = _filter_to_database_users(media_usage, database_user_ids)
        engagement_events = _filter_to_database_users(
            engagement_events, database_user_ids
        )

        # Step 3 — Last login per user (slowest — show progress)
        all_user_ids = _last_login_user_ids(db_users)

        with st.status("Fetching last login dates...", expanded=True) as status:
            progress_bar = st.progress(0)

            def _progress(current: int, total: int) -> None:
                if total > 0:
                    progress_bar.progress(current / total, text=f"{current} / {total} users")

            last_login = matomo.get_last_login_per_user(all_user_ids, _progress)
            status.update(
                label=f"Last login dates fetched ({len(all_user_ids)} users)",
                state="complete",
                expanded=False,
            )

        # Step 4 — Build merged DataFrames
        with st.spinner("Building report..."):
            user_detail = merger.build_user_detail(
                db_users, logins, last_login, visit_durations, activity_completions,
                completed_sessions,
            )
            org_summary = merger.build_org_summary(
                user_detail, completed_sessions, star_ratings, org_user_counts,
                visit_durations=visit_durations,
            )
            global_summary = _build_global_summary(
                org_summary, bundle_counts, star_ratings
            )
            daily_visit_activity = merger.build_daily_visit_activity(
                visit_dates, start_date, end_date
            )

        st.session_state.update({
            "user_detail": user_detail,
            "org_summary": org_summary,
            "global_summary": global_summary,
            "monthly_ratings": monthly_ratings,
            "monthly_bundle_creations": monthly_bundle_creations,
            "bundle_filter_breakdown": bundle_filter_breakdown,
            "bundle_counts": bundle_counts,
            "activity_catalogue": activity_catalogue,
            "activity_usage": activity_usage,
            "step_completion_depth": step_completion_depth,
            "talking_point_engagement": talking_point_engagement,
            "media_usage": media_usage,
            "engagement_events": engagement_events,
            "daily_visit_activity": daily_visit_activity,
            "region": region,
            "date_range": date_range,
            "fetched_region": region,
            "fetched_org_id": selected_org_id,
            "fetched_org_name": selected_org_name,
            "fetched_date_range": date_range,
        })

        st.success("Data loaded successfully.")

    except Exception as e:
        st.error(f"Error fetching data [{APP_REVISION}]: {e}")


# ── tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs(["Global Overview", "By Organisation", "By User"])

if "global_summary" not in st.session_state:
    for tab in (tab1, tab2, tab3):
        with tab:
            st.info("Select a region and date range in the sidebar, then click **Pull Data**.")
else:
    global_summary = st.session_state["global_summary"]
    org_summary = st.session_state["org_summary"]
    user_detail = st.session_state["user_detail"]
    monthly_ratings = st.session_state["monthly_ratings"]
    monthly_bundle_creations = st.session_state.get(
        "monthly_bundle_creations",
        pd.DataFrame(columns=["month", "organisation_name", "bundles_created"]),
    )
    bundle_filter_breakdown = st.session_state.get(
        "bundle_filter_breakdown",
        pd.DataFrame(columns=["filter_type", "filter_value", "bundle_count"]),
    )
    fetched_start_date, fetched_end_date = (
        date.fromisoformat(value)
        for value in st.session_state["fetched_date_range"].split(",")
    )

    # ── Tab 1: Global Overview ────────────────────────────────────────────────
    with tab1:
        fetched_org_name = st.session_state.get(
            "fetched_org_name", "All organisations"
        )
        st.subheader(f"Overview — {fetched_org_name}", help=_SECTION_HELP["overview"])
        if st.session_state.get("fetched_org_id") is not None:
            st.info(f"Showing data for {fetched_org_name} only.")

        fetched_org_id = st.session_state.get("fetched_org_id")
        overview_metrics = _overview_metrics(fetched_org_id)
        cols = st.columns(len(overview_metrics))
        for col, (key, label, help_text) in zip(cols, overview_metrics):
            col.metric(label, global_summary[key], help=help_text)

        st.divider()

        if _show_logins_by_organisation(fetched_org_id):
            st.markdown(
                "**Logins by Organisation**",
                help=_SECTION_HELP["logins_by_organisation"],
            )
            chart_data = (
                org_summary.set_index("organisation_name")["logins"]
                .sort_values(ascending=False)
            )
            st.bar_chart(chart_data)

        if _show_global_bundle_creation_chart(fetched_org_id):
            st.markdown(
                "**Monthly Bundle Creations**",
                help=_SECTION_HELP["monthly_bundle_creations"],
            )
            st.bar_chart(
                _monthly_bundle_creation_chart(
                    monthly_bundle_creations, fetched_start_date, fetched_end_date
                )
            )
            _render_bundle_filter_breakdown(bundle_filter_breakdown)

        st.markdown(
            "**Daily Visit Activity**",
            help=_SECTION_HELP["daily_visit_activity"],
        )
        if "daily_visit_activity" in st.session_state:
            _daily = st.session_state["daily_visit_activity"]
            if not _daily.empty and _daily["visits"].sum() > 0:
                _daily_chart = _daily.set_index("date")[["visits", "unique_users"]]
                _daily_chart.columns = ["Visits", "Unique users"]
                st.line_chart(_daily_chart)
            else:
                st.info("No visit activity recorded in the selected reporting period.")

        st.markdown(
            "**Monthly Average Star Ratings**",
            help=_SECTION_HELP["monthly_average_star_ratings"],
        )
        if not monthly_ratings.empty:
            monthly_pivot = (
                _build_monthly_rating_summary(monthly_ratings)
                .pivot(index="month", columns="target", values="avg_rating")
            )
            monthly_pivot.columns.name = None
            monthly_pivot = monthly_pivot.rename(columns={
                "groups": "Group ratings",
                "therapists": "Therapist ratings",
            })
            st.line_chart(monthly_pivot)
        else:
            st.info("No monthly rating data available.")

        st.markdown(
            "**Group Feedback by Question**",
            help=_SECTION_HELP["group_feedback_by_question"],
        )
        group_question_chart, group_question_colors = _monthly_question_chart(
            monthly_ratings, "groups"
        )
        if not group_question_chart.empty:
            st.caption(
                "The highlighted post-session feeling question is the closest "
                "feedback proxy to an outcome measure, but it is not a clinical outcome."
            )
            st.line_chart(group_question_chart, color=group_question_colors)
        else:
            st.info("No group question rating data available.")

        st.markdown(
            "**Therapist Feedback by Question**",
            help=_SECTION_HELP["therapist_feedback_by_question"],
        )
        therapist_question_chart, therapist_question_colors = _monthly_question_chart(
            monthly_ratings, "therapists"
        )
        if not therapist_question_chart.empty:
            st.line_chart(therapist_question_chart, color=therapist_question_colors)
        else:
            st.info("No therapist question rating data available.")

        st.divider()
        st.subheader("Activity Usage", help=_SECTION_HELP["activity_usage"])
        _activity_catalogue = st.session_state.get("activity_catalogue", {})
        if "activity_usage" in st.session_state:
            _activity_usage = st.session_state["activity_usage"]
            _activity_language_options = merger.activity_language_filter_options(_activity_usage)
            _activity_language_filter = (
                st.selectbox(
                    "Activity language",
                    _activity_language_options,
                    format_func=merger.format_activity_language_filter,
                    key="activity_language_filter",
                )
                if len(_activity_language_options) > 1
                else "all"
            )
            _filtered_activity_usage = merger.filter_activity_usage_by_language(
                _activity_usage,
                _activity_language_filter,
            )
            _activity_usage_table = merger.build_activity_usage_table(
                _filtered_activity_usage,
                _activity_catalogue,
            )
            st.dataframe(
                _activity_usage_table,
                use_container_width=True,
                column_config=_column_config_for(
                    _activity_usage_table,
                    {
                        "Activity Name": st.column_config.TextColumn("Activity Name"),
                        "Language": st.column_config.TextColumn("Language"),
                        "Completions": st.column_config.NumberColumn("Completions", format="%d"),
                    },
                ),
                hide_index=True,
            )
            _activity_catalogue_stats = merger.activity_catalogue_match_stats(
                _filtered_activity_usage,
                _activity_catalogue,
            )
            if _activity_catalogue_stats["usage_ids"] > 0:
                if _activity_catalogue_stats["catalogue_ids"] == 0:
                    st.warning(
                        "Activity titles are not available because the Squidex "
                        "catalogue returned 0 activities. Check the Squidex secrets."
                    )
                elif _activity_catalogue_stats["matched_ids"] == 0:
                    st.warning(
                        "Activity titles are not available because none of the "
                        f"{_activity_catalogue_stats['usage_ids']} Matomo activity IDs "
                        f"match the {_activity_catalogue_stats['catalogue_ids']} "
                        "Squidex activity IDs. Check that `squidex_project` points at "
                        "the same Squidex app/environment used by the tracked app."
                    )
                elif _activity_catalogue_stats["unmatched_ids"] > 0:
                    st.warning(
                        f"{_activity_catalogue_stats['unmatched_ids']} of "
                        f"{_activity_catalogue_stats['usage_ids']} Matomo activity IDs "
                        "could not be resolved to Squidex activity titles."
                    )

        st.markdown(
            "**Step Completion Depth**",
            help=_SECTION_HELP["step_completion_depth"],
        )
        _step_completion_depth = st.session_state.get(
            "step_completion_depth", pd.DataFrame()
        )
        if _step_completion_depth.empty:
            st.info("No Step Complete events recorded in the selected scope.")
        else:
            _step_language_options = merger.activity_language_filter_options(
                _step_completion_depth
            )
            _step_language_filter = (
                st.selectbox(
                    "Step completion language",
                    _step_language_options,
                    format_func=merger.format_activity_language_filter,
                    key="step_completion_language_filter",
                )
                if len(_step_language_options) > 1
                else "all"
            )
            _filtered_step_completion_depth = merger.filter_activity_usage_by_language(
                _step_completion_depth,
                _step_language_filter,
            )
            _step_completion_depth_table = merger.build_step_completion_depth_table(
                _filtered_step_completion_depth,
                _activity_catalogue,
            )
            st.dataframe(
                _step_completion_depth_table,
                use_container_width=True,
                column_config=_column_config_for(
                    _step_completion_depth_table,
                    {
                        "Activity Name": st.column_config.TextColumn("Activity Name"),
                        "Language": st.column_config.TextColumn("Language"),
                        "Activity Occurrences": st.column_config.NumberColumn(
                            "Activity Occurrences", format="%d"
                        ),
                        "Avg Last Step Reached": st.column_config.NumberColumn(
                            "Avg Last Step Reached", format="%.1f"
                        ),
                        "Completion Depth Distribution": st.column_config.TextColumn(
                            "Completion Depth Distribution"
                        ),
                        "Least Reached Step(s)": st.column_config.TextColumn(
                            "Least Reached Step(s)"
                        ),
                    },
                ),
                hide_index=True,
            )

        st.markdown(
            "**Talking-Point Engagement (Approximate)**",
            help=_SECTION_HELP["talking_point_engagement"],
        )
        _tp_engagement = st.session_state.get(
            "talking_point_engagement", pd.DataFrame()
        )
        if _tp_engagement.empty:
            st.info(
                "No Talking Point Expand Click or Step Forward Click events "
                "recorded in the selected scope."
            )
        else:
            _tp_table = merger.build_talking_point_engagement_table(
                _tp_engagement, _activity_catalogue
            )
            if _tp_table.empty:
                st.info(
                    "No activities had 10 or more Step Forward Clicks in the "
                    "selected scope. Increase the date range to see results."
                )
            else:
                st.caption(
                    "Ratio of Talking Point Expand Clicks to Step Forward Clicks "
                    "— approximate because Step Forward Click is used as a proxy "
                    "denominator, not the exact number of talking points shown."
                )
                st.dataframe(
                    _tp_table,
                    use_container_width=True,
                    column_config=_column_config_for(
                        _tp_table,
                        {
                            "Activity Name": st.column_config.TextColumn("Activity Name"),
                            "Language": st.column_config.TextColumn("Language"),
                            "Expand Clicks": st.column_config.NumberColumn(
                                "Expand Clicks", format="%d"
                            ),
                            "Step Forward Clicks": st.column_config.NumberColumn(
                                "Step Forward Clicks", format="%d"
                            ),
                            "Approx. Engagement Ratio": st.column_config.NumberColumn(
                                "Approx. Engagement Ratio",
                                format="%.2f",
                                help=(
                                    "Talking Point Expand Clicks ÷ Step Forward Clicks. "
                                    "Approximate: Step Forward Click is a proxy denominator "
                                    "because Matomo does not record every talking point shown."
                                ),
                            ),
                        },
                    ),
                    hide_index=True,
                )

    # ── Tab 2: By Organisation ────────────────────────────────────────────────
    with tab2:
        st.subheader("By Organisation", help=_SECTION_HELP["by_organisation"])
        if _show_organisation_bundle_creation_chart(
            st.session_state.get("fetched_org_id")
        ):
            st.markdown(
                "**Monthly Bundle Creations**",
                help=_SECTION_HELP["monthly_bundle_creations"],
            )
            st.bar_chart(
                _monthly_bundle_creation_chart(
                    monthly_bundle_creations, fetched_start_date, fetched_end_date
                )
            )
            _render_bundle_filter_breakdown(bundle_filter_breakdown)
        st.dataframe(
            org_summary,
            column_config=_column_config_for(org_summary, {
                "organisation_name": st.column_config.TextColumn(
                    help="Name of the care provider organisation",
                ),
                "total_users": st.column_config.NumberColumn(
                    help="Total number of registered users in this organisation",
                ),
                "active_users": st.column_config.NumberColumn(
                    help="Users with 2 or more logins in the selected period",
                ),
                "logins": st.column_config.NumberColumn(
                    help="Number of Matomo visits (browser sessions) in the selected period",
                ),
                "avg_real_session_minutes": st.column_config.NumberColumn(
                    help=(
                        "Mean duration (minutes) of deliver-mode visits over 20 minutes "
                        "— treated as genuine CST session deliveries"
                    ),
                    format="%.1f",
                ),
                "median_prepare_minutes": st.column_config.NumberColumn(
                    help="Median duration (minutes) of prepare-only visits (no deliver-mode actions)",
                    format="%.1f",
                ),
                "min_real_session_minutes": st.column_config.NumberColumn(
                    help="Shortest individual real session (deliver visit >20 min) for any user in this organisation",
                    format="%.1f",
                ),
                "max_real_session_minutes": st.column_config.NumberColumn(
                    help="Longest individual real session (deliver visit >20 min) for any user in this organisation",
                    format="%.1f",
                ),
                "short_visit_count": st.column_config.NumberColumn(
                    help=(
                        "Count of deliver-mode visits 20 minutes or under — treated as check-ins "
                        "or browsing, not real sessions"
                    ),
                ),
                "completed_sessions": st.column_config.NumberColumn(
                    help=(
                        "Deliver-mode Session Complete events in the selected period, "
                        "deduplicated by Matomo visit + bundle + session ID. Repeat "
                        "deliveries in separate visits are counted separately."
                    ),
                ),
                "avg_activities_per_session": st.column_config.NumberColumn(
                    help=(
                        "Total Activity Complete events divided by completed sessions in the "
                        "selected period. Note: the Activity Complete event fires on "
                        "forward navigation, so rapid click-through may inflate this count."
                    ),
                    format="%.1f",
                ),
                "last_login_date": st.column_config.TextColumn(
                    help="Most recent Matomo visit date for any user in this organisation",
                ),
                "groups_avg_rating": st.column_config.NumberColumn(
                    help="Average 1–5 star rating submitted by patient groups at end of session",
                    format="%.2f",
                ),
                "therapists_avg_rating": st.column_config.NumberColumn(
                    help="Average 1–5 star rating submitted by therapists after session",
                    format="%.2f",
                ),
            }),
            use_container_width=True,
        )

        st.divider()
        st.markdown(
            "**Media Usage by Organisation**",
            help=_SECTION_HELP["media_usage_by_org"],
        )
        _media_usage_raw = st.session_state.get("media_usage", pd.DataFrame())
        _org_session_counts = org_summary[["organisation_name", "completed_sessions"]]
        _media_table = merger.build_media_usage_by_org(
            _media_usage_raw,
            user_detail,
            _org_session_counts,
        )
        st.dataframe(
            _media_table,
            use_container_width=True,
            column_config=_column_config_for(
                _media_table,
                {
                    "organisation_name": st.column_config.TextColumn("Organisation"),
                    "completed_sessions": st.column_config.NumberColumn(
                        "Completed Sessions", format="%d"
                    ),
                    "audio_clicks": st.column_config.NumberColumn(
                        "Audio Interactions", format="%d",
                        help="Total Audio Button/Play/Pause clicks in deliver mode"
                    ),
                    "video_clicks": st.column_config.NumberColumn(
                        "Video Interactions", format="%d",
                        help="Total Video Button/Play/Pause clicks in deliver mode"
                    ),
                    "audio_rate": st.column_config.NumberColumn(
                        "Audio / Session",
                        format="%.2f",
                        help="Audio interactions per completed session",
                    ),
                    "video_rate": st.column_config.NumberColumn(
                        "Video / Session",
                        format="%.2f",
                        help="Video interactions per completed session",
                    ),
                },
            ),
            hide_index=True,
        )

        st.divider()
        st.markdown(
            "**Activity Engagement by Organisation**",
            help=_SECTION_HELP["engagement_events_by_org"],
        )
        _engagement_events_raw = st.session_state.get("engagement_events", pd.DataFrame())
        _engagement_table = merger.build_engagement_events_by_org(
            _engagement_events_raw,
            user_detail,
            _org_session_counts,
        )
        st.dataframe(
            _engagement_table,
            use_container_width=True,
            column_config=_column_config_for(
                _engagement_table,
                {
                    "organisation_name": st.column_config.TextColumn("Organisation"),
                    "completed_sessions": st.column_config.NumberColumn(
                        "Completed Sessions", format="%d"
                    ),
                    "additional_activity_rate": st.column_config.NumberColumn(
                        "Additional Activity / Session",
                        format="%.2f",
                        help=(
                            "How often facilitators accepted the prompt to run an "
                            "additional main activity, per completed session."
                        ),
                    ),
                    "main_replacement_rate": st.column_config.NumberColumn(
                        "Main Activity Replacements / Session",
                        format="%.2f",
                        help="Change Main Activity Click events per completed session",
                    ),
                    "warmup_replacement_rate": st.column_config.NumberColumn(
                        "Warmup Replacements / Session",
                        format="%.2f",
                        help="Change Warmup Activity Click events per completed session",
                    ),
                    "ro_replacement_rate": st.column_config.NumberColumn(
                        "RO Replacements / Session",
                        format="%.2f",
                        help=(
                            "Change Reality Orientation Activity Click events "
                            "per completed session"
                        ),
                    ),
                },
            ),
            hide_index=True,
        )

    # ── Tab 3: By User ────────────────────────────────────────────────────────
    with tab3:
        st.subheader("By User", help=_SECTION_HELP["by_user"])
        org_filter = (
            st.text_input("Filter by organisation name")
            if _show_user_organisation_filter(
                st.session_state.get("fetched_org_id")
            )
            else ""
        )
        filtered = (
            user_detail
            if not org_filter
            else user_detail[
                user_detail["organisation_name"].str.contains(org_filter, case=False, na=False)
            ]
        )
        st.dataframe(
            filtered,
            column_config=_column_config_for(filtered, {
                "user_id": st.column_config.TextColumn(
                    help="Internal user ID",
                ),
                "email": st.column_config.TextColumn(
                    help="User email address",
                ),
                "organisation_name": st.column_config.TextColumn(
                    help="Organisation this user belongs to",
                ),
                "last_login_date": st.column_config.TextColumn(
                    help="Most recent recorded Matomo visit date",
                ),
                "logins": st.column_config.NumberColumn(
                    help="Number of Matomo visits (browser sessions) in the selected period",
                ),
                "avg_real_session_minutes": st.column_config.NumberColumn(
                    help=(
                        "Mean duration (minutes) of deliver-mode visits over 20 minutes "
                        "— treated as genuine CST session deliveries"
                    ),
                    format="%.1f",
                ),
                "median_prepare_minutes": st.column_config.NumberColumn(
                    help="Median duration (minutes) of prepare-only visits (no deliver-mode actions)",
                    format="%.1f",
                ),
                "short_visit_count": st.column_config.NumberColumn(
                    help=(
                        "Count of deliver-mode visits 20 minutes or under — treated as check-ins "
                        "or browsing"
                    ),
                ),
                "completed_sessions": st.column_config.NumberColumn(
                    help=(
                        "Deliver-mode Session Complete events in the selected period, "
                        "deduplicated by Matomo visit + bundle + session ID."
                    ),
                ),
                "activities_completed": st.column_config.NumberColumn(
                    help="Count of Activity Complete events in deliver-mode sessions",
                ),
            }),
            use_container_width=True,
        )


# ── download button ───────────────────────────────────────────────────────────

if "user_detail" in st.session_state:
    st.divider()
    _download_activity_usage = st.session_state.get("activity_usage", pd.DataFrame())
    _download_activity_language_filter = st.session_state.get("activity_language_filter", "all")
    _download_activity_usage = merger.filter_activity_usage_by_language(
        _download_activity_usage,
        _download_activity_language_filter,
    )
    excel_bytes = exporter.build_excel_report(
        st.session_state["user_detail"],
        st.session_state["org_summary"],
        st.session_state["monthly_ratings"],
        st.session_state["region"],
        st.session_state["date_range"],
        activity_usage_table=merger.build_activity_usage_table(
            _download_activity_usage,
            st.session_state.get("activity_catalogue", {}),
        ),
        org_filter_name=(
            None
            if st.session_state.get("fetched_org_id") is None
            else st.session_state.get("fetched_org_name")
        ),
    )
    st.download_button(
        label="Download Excel Report",
        data=excel_bytes,
        file_name=f"ayla_usage_{st.session_state['region']}_{date.today()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
