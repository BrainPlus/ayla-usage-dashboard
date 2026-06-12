# Streamlit entry point: sidebar region selector, three-tab layout (Global Overview, By Organisation, By User).

import importlib
import inspect
import streamlit as st
from datetime import date, timedelta
from time import monotonic

import pandas as pd

import database
import matomo
import merger
import exporter
from revision import get_deployment_revision

APP_REVISION = get_deployment_revision()

st.set_page_config(page_title="Ayla Usage Dashboard", layout="wide")

_OUTCOME_PROXY_QUESTION = "How do you feel after today's session?"
_OUTCOME_PROXY_CHART_LABEL = (
    f"{_OUTCOME_PROXY_QUESTION} (not a clinical outcome)"
)
_QUESTION_CHART_COLORS = {
    "groups": ["#1f77b4", "#2ca02c", "#17becf"],
    "therapists": ["#9467bd", "#17becf", "#8c564b", "#7f7f7f"],
}
_INTERNAL_ORGANISATION_NAMES = frozenset(
    {"Brain+", "Brain+ Tech Organisation"}
)

_REPORT_DATA_KEYS = (
    "user_detail",
    "org_summary",
    "global_summary",
    "delivery_funnel",
    "monthly_ratings",
    "monthly_bundle_creations",
    "bundle_filter_breakdown",
    "bundle_counts",
    "bundle_progression",
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
    "fetched_skip_last_login",
    "fetched_skip_bundle_history",
    "fetched_exclude_internal_organisations",
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
    "delivery_funnel": (
        "Progression from selecting Deliver (a boundary event emitted before the "
        "mode changes), through at least one high-confidence deliver-mode activity "
        "signal, to a deliver-mode Session Complete event. "
        "Each stage is deduplicated by Matomo visit + bundle + session ID."
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
    "bundle_progression": (
        "Configured CST session progression for each bundle across its full history. "
        "Progress counts unique configured sessions with a deduplicated deliver-mode "
        "Session Complete event. Incomplete bundles are flagged as stalled after 30 days."
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
        "most recent recorded visit found within the last 365 days. Days since last "
        "completed session uses deliver-mode Session Complete events across bundle history."
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


def _excluded_organisation_ids(orgs_df: pd.DataFrame) -> tuple[int, ...]:
    if orgs_df.empty:
        return ()
    excluded = orgs_df[
        orgs_df["organisation_name"]
        .str.strip()
        .str.casefold()
        .isin(name.casefold() for name in _INTERNAL_ORGANISATION_NAMES)
    ]
    return tuple(sorted(excluded["organisation_id"].astype(int).tolist()))


def _organisation_query_scope(
    selected_org_id,
    exclude_internal_organisations: bool,
    excluded_organisation_ids: tuple[int, ...],
):
    if (
        selected_org_id is None
        and exclude_internal_organisations
        and excluded_organisation_ids
    ):
        return excluded_organisation_ids
    return selected_org_id


def _organisation_options(
    orgs_df: pd.DataFrame,
    exclude_internal_organisations: bool,
) -> list[str]:
    organisation_names = orgs_df["organisation_name"].tolist()
    if exclude_internal_organisations:
        internal_names = {
            name.casefold() for name in _INTERNAL_ORGANISATION_NAMES
        }
        organisation_names = [
            name
            for name in organisation_names
            if name.strip().casefold() not in internal_names
        ]
    return (
        ["All organisations"]
        + organisation_names
        + ["Unassigned / No organisation"]
    )


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


def _delivery_funnel_summary(global_summary: dict) -> pd.DataFrame:
    counts = [
        int(global_summary.get("total_deliver_selected_sessions", 0)),
        int(global_summary.get("total_active_delivery_sessions", 0)),
        int(global_summary.get("total_completed_sessions", 0)),
    ]
    rows = []
    for index, (stage, count) in enumerate(
        zip(("Deliver Selected", "Active Delivery", "Completed Session"), counts)
    ):
        previous = counts[index - 1] if index > 0 else None
        dropoff = max(0, previous - count) if previous is not None else None
        dropoff_pct = (
            round(dropoff / previous * 100, 1)
            if previous not in (None, 0)
            else None
        )
        rows.append(
            {
                "Stage": stage,
                "Sessions": count,
                "Drop-off from previous": str(dropoff) if dropoff is not None else "N/A",
                "Drop-off %": f"{dropoff_pct:.1f}%" if dropoff_pct is not None else "N/A",
            }
        )
    return pd.DataFrame(rows)


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


def _get_delivery_funnel_instances(date_range: str, org_id):
    global matomo
    if not hasattr(matomo, "get_delivery_funnel_instances"):
        matomo = importlib.reload(matomo)
    return matomo.get_delivery_funnel_instances(date_range, org_id=org_id)


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
    current_skip_last_login: bool = False,
    current_skip_bundle_history: bool = False,
    current_exclude_internal_organisations: bool = True,
) -> bool:
    if not any(
        key in session_state
        for key in ("user_detail", "org_summary", "global_summary")
    ):
        return False
    fetched_region = session_state.get("fetched_region")
    fetched_org_id = session_state.get("fetched_org_id")
    fetched_date_range = session_state.get("fetched_date_range")
    fetched_skip_last_login = session_state.get("fetched_skip_last_login", False)
    fetched_skip_bundle_history = session_state.get("fetched_skip_bundle_history", False)
    fetched_exclude_internal_organisations = session_state.get(
        "fetched_exclude_internal_organisations", True
    )
    return (
        fetched_region != current_region
        or fetched_org_id != current_org_id
        or fetched_date_range != current_date_range
        or fetched_skip_last_login != current_skip_last_login
        or fetched_skip_bundle_history != current_skip_bundle_history
        or fetched_exclude_internal_organisations
        != current_exclude_internal_organisations
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


def _bundle_history_date_range(
    bundle_configurations: pd.DataFrame,
    as_of_date: date,
) -> str:
    if "created_date" not in bundle_configurations:
        return f"{as_of_date},{as_of_date}"
    created_dates = pd.to_datetime(
        bundle_configurations["created_date"], errors="coerce"
    )
    earliest = created_dates.min()
    start_date = earliest.date() if pd.notna(earliest) else as_of_date
    return f"{start_date},{as_of_date}"


def _format_elapsed(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"


def _skipped_last_login(db_users: pd.DataFrame) -> pd.DataFrame:
    result = db_users.loc[:, ["user_id"]].copy()
    result["user_id"] = result["user_id"].astype(str)
    result["last_login_date"] = "Not fetched"
    return result


# ── cached Matomo wrappers ────────────────────────────────────────────────────
# get_last_login_per_user is intentionally not cached: it drives a live progress bar.

@st.cache_data(ttl=3600)
def _cached_logins(date_range: str):
    return matomo.get_logins_by_date_range(date_range)


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


# ── sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("Ayla Usage Dashboard")

    region = st.selectbox("Region", ["eu", "uk"])

    orgs_df = database.get_organisations(region)
    exclude_internal_organisations = st.session_state.get(
        "exclude_internal_organisations", True
    )
    excluded_organisation_ids = _excluded_organisation_ids(orgs_df)
    org_options = _organisation_options(orgs_df, exclude_internal_organisations)
    organisation_selector_key = (
        f"org_selector_{region}_{exclude_internal_organisations}"
    )
    selected_org_name = st.selectbox(
        "Organisation",
        org_options,
        key=organisation_selector_key,
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

    skip_last_login = st.checkbox(
        "Skip last login lookup",
        help=(
            "Skips one Matomo request per user. Last login fields will show "
            "'Not fetched'. This usually saves around two minutes for all EU users."
        ),
    )
    skip_bundle_history = st.checkbox(
        "Skip bundle history",
        help=(
            "Skips the full-history Matomo and bundle-configuration queries used for "
            "bundle progression, completed-programme counts, and days since the last "
            "completed session. Those fields will show as unavailable."
        ),
    )
    exclude_internal_organisations = st.checkbox(
        "Exclude Brain+ organisations",
        value=True,
        key="exclude_internal_organisations",
        help=(
            "Excludes Brain+ and Brain+ Tech Organisation from all-organisation "
            "report results. Turn this off to pull data for either excluded organisation."
        ),
    )

    pull = st.button("Pull Data", type="primary")
    st.caption("Use the skip options above for a faster selected-period-only pull.")

if start_date > end_date:
    st.error("'From' date must be on or before 'To' date.")
    st.stop()

date_range = f"{start_date},{end_date}"
query_org_scope = _organisation_query_scope(
    selected_org_id,
    exclude_internal_organisations,
    excluded_organisation_ids,
)

if _should_clear_report(
    st.session_state,
    region,
    selected_org_id,
    date_range,
    skip_last_login,
    skip_bundle_history,
    exclude_internal_organisations,
):
    for key in _REPORT_DATA_KEYS:
        st.session_state.pop(key, None)

# ── data fetching ─────────────────────────────────────────────────────────────

if pull:
    pull_started = monotonic()
    pull_status = st.status("Starting data pull...", expanded=True)
    pull_progress = st.progress(0, text="Starting data pull...")

    def _update_pull_progress(value: float, label: str) -> None:
        elapsed = _format_elapsed(monotonic() - pull_started)
        text = f"{label} · elapsed {elapsed}"
        pull_progress.progress(value, text=text)

    try:
        # Step 1 — DB queries. Keep these sequential to avoid exhausting the
        # production database's limited connection slots.
        _update_pull_progress(0.02, "Querying database")
        with st.spinner("Querying database...", show_time=True):
            db_users = database.load_users_and_orgs(region, org_id=query_org_scope)
            org_user_counts = database.get_org_user_counts(
                region, org_id=query_org_scope
            )
            bundle_counts = database.get_bundle_counts_per_org(
                region, org_id=query_org_scope
            )
            bundle_configurations = (
                pd.DataFrame()
                if skip_bundle_history
                else database.get_bundle_configurations(
                    region, org_id=query_org_scope
                )
            )
            monthly_bundle_creations = _get_monthly_bundle_creations(
                region, start_date, end_date, org_id=query_org_scope
            )
            bundle_filter_breakdown = _get_bundle_filter_breakdown(
                region, start_date, end_date, org_id=query_org_scope
            )
            star_ratings = database.get_star_ratings_by_org(
                region, start_date, end_date, org_id=query_org_scope
            )
            feedback_submissions = database.get_feedback_submissions(
                region, start_date, end_date, org_id=query_org_scope
            )
            monthly_ratings = database.get_monthly_star_ratings(
                region, start_date, end_date, org_id=query_org_scope
            )
            bundle_history_date_range = (
                None
                if skip_bundle_history
                else _bundle_history_date_range(bundle_configurations, today)
            )
            database_user_ids = _database_user_ids(db_users)
        _update_pull_progress(0.12, "Database queries complete")

        # Step 2 — Matomo queries
        with st.spinner("Fetching Matomo analytics...", show_time=True):
            _update_pull_progress(0.15, "Fetching login totals")
            logins = _cached_logins(date_range)
            if skip_bundle_history:
                bundle_history_funnel = pd.DataFrame(
                    columns=[
                        "visit_id",
                        "bundle_id",
                        "session_id",
                        "user_id",
                        "completed_session",
                        "completed_session_date",
                    ]
                )
            elif bundle_history_date_range != date_range:
                _update_pull_progress(
                    0.25, "Fetching bundle history (usually the longest stage)"
                )
                bundle_history_funnel = matomo.get_delivery_funnel_instances_streamed(
                    bundle_history_date_range,
                    org_id=query_org_scope,
                )
            else:
                bundle_history_funnel = None

            _update_pull_progress(0.50, "Fetching selected-period Matomo visits")
            # Keep one live copy for this pull. Caching this action-level payload causes
            # Streamlit to retain serialized copies and can exceed Cloud worker memory.
            live_visits = matomo.get_live_visits(date_range)
            _update_pull_progress(0.62, "Calculating Matomo metrics")
            delivery_funnel = matomo.get_delivery_funnel_instances(
                date_range, org_id=query_org_scope, visits=live_visits
            )
            if bundle_history_funnel is None:
                bundle_history_funnel = delivery_funnel
            completed_sessions = delivery_funnel.loc[
                delivery_funnel["completed_session"],
                ["visit_id", "bundle_id", "session_id", "user_id"],
            ].reset_index(drop=True)
            completed_session_history = bundle_history_funnel.loc[
                bundle_history_funnel["completed_session"],
                [
                    "visit_id",
                    "bundle_id",
                    "session_id",
                    "user_id",
                    "completed_session_date",
                ],
            ].rename(columns={"completed_session_date": "completion_date"}).reset_index(
                drop=True
            )
            activity_completions = matomo.get_activity_completions_per_user(
                date_range, org_id=query_org_scope, visits=live_visits
            )
            activity_catalogue = _cached_activity_catalogue()
            activity_usage = matomo.get_activity_usage_by_id(
                date_range,
                database_user_ids,
                query_org_scope,
                visits=live_visits,
            )
            step_completion_depth = matomo.get_step_completion_depth(
                date_range,
                database_user_ids,
                query_org_scope,
                visits=live_visits,
            )
            visit_durations = matomo.get_visit_durations(
                date_range, org_id=query_org_scope, visits=live_visits
            )
            visit_dates = matomo.get_visit_dates(
                date_range, org_id=query_org_scope, visits=live_visits
            )
            talking_point_engagement = matomo.get_talking_point_engagement(
                date_range,
                database_user_ids,
                query_org_scope,
                visits=live_visits,
            )
            media_usage = matomo.get_media_usage(
                date_range,
                database_user_ids,
                query_org_scope,
                visits=live_visits,
            )
            engagement_events = matomo.get_engagement_events(
                date_range,
                database_user_ids,
                query_org_scope,
                visits=live_visits,
            )
        _update_pull_progress(0.72, "Matomo analytics complete")

        # Raw aggregates must be scoped to selected-region DB users before aggregation.
        logins = _filter_to_database_users(logins, database_user_ids)
        completed_sessions = _filter_to_database_users(
            completed_sessions, database_user_ids
        )
        completed_session_history = _filter_to_database_users(
            completed_session_history, database_user_ids
        )
        delivery_funnel = _filter_to_database_users(
            delivery_funnel, database_user_ids
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
        if skip_last_login:
            last_login = _skipped_last_login(db_users)
            _update_pull_progress(0.94, "Last login lookup skipped")
        else:
            all_user_ids = _last_login_user_ids(db_users)

            with st.status("Fetching last login dates...", expanded=True) as status:
                progress_bar = st.progress(0)
                _update_pull_progress(0.74, "Fetching last login dates")

                def _progress(current: int, total: int) -> None:
                    if total > 0:
                        progress_bar.progress(
                            current / total, text=f"{current} / {total} users"
                        )
                        overall_value = 0.74 + (current / total * 0.20)
                        _update_pull_progress(
                            overall_value,
                            f"Fetching last login dates ({current} / {total} users)",
                        )

                last_login = matomo.get_last_login_per_user(all_user_ids, _progress)
                status.update(
                    label=f"Last login dates fetched ({len(all_user_ids)} users)",
                    state="complete",
                    expanded=False,
                )

        # Step 4 — Build merged DataFrames
        _update_pull_progress(0.95, "Building report")
        with st.spinner("Building report...", show_time=True):
            user_detail = merger.build_user_detail(
                db_users, logins, last_login, visit_durations, activity_completions,
                completed_sessions,
            )
            bundle_progression = (
                merger.build_bundle_progression(
                    bundle_configurations,
                    completed_session_history,
                    as_of_date=today,
                )
                if not skip_bundle_history
                else pd.DataFrame()
            )
            org_summary = merger.build_org_summary(
                user_detail, completed_sessions, star_ratings, org_user_counts,
                visit_durations=visit_durations,
                delivery_funnel=delivery_funnel,
                recent_completed_sessions=(
                    completed_session_history if not skip_bundle_history else None
                ),
                as_of_date=today,
                feedback_submissions=feedback_submissions,
            )
            if skip_bundle_history:
                org_summary["days_since_last_completed_session"] = "Not fetched"
                org_summary["full_programmes"] = pd.NA
            else:
                org_summary = merger.add_bundle_progression_to_org_summary(
                    org_summary, bundle_progression
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
            "delivery_funnel": delivery_funnel,
            "monthly_ratings": monthly_ratings,
            "monthly_bundle_creations": monthly_bundle_creations,
            "bundle_filter_breakdown": bundle_filter_breakdown,
            "bundle_counts": bundle_counts,
            "bundle_progression": bundle_progression,
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
            "fetched_skip_last_login": skip_last_login,
            "fetched_skip_bundle_history": skip_bundle_history,
            "fetched_exclude_internal_organisations": exclude_internal_organisations,
        })

        elapsed = _format_elapsed(monotonic() - pull_started)
        pull_progress.progress(1.0, text="")
        pull_status.update(
            label=f"Data pull complete · elapsed {elapsed}",
            state="complete",
            expanded=False,
        )
        st.success("Data loaded successfully.")

    except Exception as e:
        elapsed = _format_elapsed(monotonic() - pull_started)
        pull_status.update(
            label=f"Data pull failed after {elapsed}",
            state="error",
            expanded=True,
        )
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
    bundle_progression = st.session_state.get(
        "bundle_progression",
        pd.DataFrame(),
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
        st.markdown(
            "**Delivery Funnel**",
            help=_SECTION_HELP["delivery_funnel"],
        )
        st.dataframe(
            _delivery_funnel_summary(global_summary),
            use_container_width=True,
            column_config={
                "Sessions": st.column_config.NumberColumn(format="%d"),
                "Drop-off from previous": st.column_config.TextColumn(),
                "Drop-off %": st.column_config.TextColumn(),
            },
            hide_index=True,
        )

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

        st.markdown("**Media Interactions by Activity**")
        _media_usage_tab1 = st.session_state.get("media_usage", pd.DataFrame())
        if _media_usage_tab1.empty:
            st.info("No audio or video interaction events recorded in the selected scope.")
        else:
            _media_by_activity = merger.build_media_usage_by_activity(
                _media_usage_tab1, _activity_catalogue
            )
            if _media_by_activity.empty:
                st.info("No audio or video interaction events recorded in the selected scope.")
            else:
                st.dataframe(
                    _media_by_activity,
                    use_container_width=True,
                    column_config=_column_config_for(
                        _media_by_activity,
                        {
                            "Activity Name": st.column_config.TextColumn("Activity Name"),
                            "Audio Interactions": st.column_config.NumberColumn(
                                "Audio Interactions",
                                format="%d",
                                help="Total Audio Button/Play/Pause clicks in deliver mode",
                            ),
                            "Video Interactions": st.column_config.NumberColumn(
                                "Video Interactions",
                                format="%d",
                                help="Total Video Button/Play/Pause clicks in deliver mode",
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
                "deliver_selected_sessions": st.column_config.NumberColumn(
                    help=(
                        "Prepare/Deliver dialog - Deliver Click boundary events, "
                        "deduplicated by Matomo visit + bundle + session ID."
                    ),
                ),
                "active_delivery_sessions": st.column_config.NumberColumn(
                    help=(
                        "Deliver-selected session instances with at least one "
                        "high-confidence deliver-mode activity signal."
                    ),
                ),
                "completed_sessions": st.column_config.NumberColumn(
                    help=(
                        "Deliver-mode Session Complete events in the selected period, "
                        "deduplicated by Matomo visit + bundle + session ID. Repeat "
                        "deliveries in separate visits are counted separately."
                    ),
                ),
                "full_programmes": st.column_config.NumberColumn(
                    "Full programmes",
                    help=(
                        "Bundles that completed every configured CST session across "
                        "their full history. A value above zero is a positive indicator."
                    ),
                ),
                "group_feedback_coverage": st.column_config.TextColumn(
                    "Group feedback coverage",
                    help=(
                        "Unique bundle + CST session pairs with group feedback divided "
                        "by unique completed bundle + CST session pairs in the selected period."
                    ),
                ),
                "therapist_feedback_coverage": st.column_config.TextColumn(
                    "Therapist feedback coverage",
                    help=(
                        "Unique bundle + CST session pairs with therapist feedback divided "
                        "by unique completed bundle + CST session pairs in the selected period."
                    ),
                ),
                "therapist_comment_rate": st.column_config.TextColumn(
                    "Therapist comment rate",
                    help=(
                        "Therapist feedback submissions with a non-empty comment divided "
                        "by all therapist feedback submissions in the selected period."
                    ),
                ),
                "days_since_last_completed_session": st.column_config.TextColumn(
                    "Days since last completed session",
                    help=(
                        "Calendar days since the organisation's most recent deliver-mode "
                        "Session Complete event across bundle history. Organisations without "
                        "one show No recent session."
                    ),
                ),
                "deliver_to_active_dropoff": st.column_config.NumberColumn(
                    help="Deliver Selected minus Active Delivery.",
                ),
                "deliver_to_active_dropoff_pct": st.column_config.NumberColumn(
                    help="Drop-off from Deliver Selected to Active Delivery.",
                    format="%.1f%%",
                ),
                "active_to_completed_dropoff": st.column_config.NumberColumn(
                    help="Active Delivery minus Completed Sessions.",
                ),
                "active_to_completed_dropoff_pct": st.column_config.NumberColumn(
                    help="Drop-off from Active Delivery to Completed Sessions.",
                    format="%.1f%%",
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
            "**Bundle Progression**",
            help=_SECTION_HELP["bundle_progression"],
        )
        if st.session_state.get("fetched_skip_bundle_history"):
            st.info(
                "Bundle history was skipped. Pull data again without "
                "**Skip bundle history** to view progression."
            )
        elif bundle_progression.empty:
            st.info("No bundles are available for the selected organisation scope.")
        else:
            st.dataframe(
                bundle_progression,
                column_config=_column_config_for(bundle_progression, {
                    "organisation_name": st.column_config.TextColumn("Organisation"),
                    "bundle_name": st.column_config.TextColumn("Bundle"),
                    "bundle_id": st.column_config.TextColumn("Bundle ID"),
                    "completed_configured_sessions": st.column_config.NumberColumn(
                        "Completed configured sessions",
                        help=(
                            "Unique configured sessions with at least one deduplicated "
                            "deliver-mode Session Complete event."
                        ),
                    ),
                    "total_configured_sessions": st.column_config.NumberColumn(
                        "Configured sessions",
                        help="Actual number of sessions configured for this bundle.",
                    ),
                    "progress": st.column_config.TextColumn(
                        "Progress",
                        help="Completed configured sessions / total configured sessions.",
                    ),
                    "status": st.column_config.TextColumn(
                        "Status",
                        help=(
                            "Incomplete bundles with no newly completed configured "
                            "session in 30 or 60 days are flagged as stalled."
                        ),
                    ),
                    "days_since_last_completion": st.column_config.NumberColumn(
                        "Days since last completion",
                    ),
                    "avg_days_between_completions": st.column_config.NumberColumn(
                        "Avg days between completions",
                        help=(
                            "Average calendar days between first completions of unique "
                            "configured sessions."
                        ),
                        format="%.1f",
                    ),
                }),
                hide_index=True,
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
        bundle_progression=st.session_state.get("bundle_progression", pd.DataFrame()),
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
