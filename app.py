# Streamlit entry point: sidebar region selector, three-tab layout (Global Overview, By Organisation, By User).

import streamlit as st
from datetime import date, timedelta

import database
import matomo
import merger
import exporter

st.set_page_config(page_title="Ayla Usage Dashboard", layout="wide")

_REPORT_DATA_KEYS = [
    "user_detail",
    "org_summary",
    "global_summary",
    "monthly_ratings",
    "bundle_counts",
    "fetched_region",
    "fetched_date_range",
]


def _column_config_for(dataframe, column_config):
    return {
        column_name: config
        for column_name, config in column_config.items()
        if column_name in dataframe.columns
    }


# ── cached Matomo wrappers ────────────────────────────────────────────────────
# get_last_login_per_user is intentionally not cached: it drives a live progress bar.

@st.cache_data(ttl=3600)
def _cached_logins(date_range: str):
    return matomo.get_logins_by_date_range(date_range)


@st.cache_data(ttl=3600)
def _cached_sessions_delivered(date_range: str):
    return matomo.get_sessions_delivered(date_range)


@st.cache_data(ttl=3600)
def _cached_activity_completions(date_range: str):
    return matomo.get_activity_completions_per_user(date_range)


@st.cache_data(ttl=3600)
def _cached_visit_durations(date_range: str):
    return matomo.get_visit_durations(date_range)


# ── sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("Ayla Usage Dashboard")

    region = st.selectbox("Region", ["eu", "uk"])

    today = date.today()

    start_date = st.date_input("From", today - timedelta(days=90), key="start_date")
    end_date = st.date_input("To", today, key="end_date")

    pull = st.button("Pull Data", type="primary")
    st.caption("Pulling last login data may take a few minutes")

if start_date > end_date:
    st.error("'From' date must be on or before 'To' date.")
    st.stop()

date_range = f"{start_date},{end_date}"

fetched_region = st.session_state.get("fetched_region")
fetched_date_range = st.session_state.get("fetched_date_range")
if (fetched_region is not None or fetched_date_range is not None) and (
    fetched_region != region or fetched_date_range != date_range
):
    for key in _REPORT_DATA_KEYS:
        st.session_state.pop(key, None)


# ── data fetching ─────────────────────────────────────────────────────────────

if pull:
    try:
        # Step 1 — DB queries (fast)
        with st.spinner("Querying database..."):
            db_users = database.load_users_and_orgs(region)
            org_user_counts = database.get_org_user_counts(region)
            bundle_counts = database.get_bundle_counts_per_org(region)
            star_ratings = database.get_star_ratings_by_org(region, start_date, end_date)
            monthly_ratings = database.get_monthly_star_ratings(region, start_date, end_date)

        # Step 2 — Matomo queries (cached after first run)
        with st.spinner("Fetching Matomo analytics..."):
            logins = _cached_logins(date_range)
            sessions = _cached_sessions_delivered(date_range)
            activity_completions = _cached_activity_completions(date_range)

        # Step 3 — Last login per user (slowest — show progress)
        all_user_ids = sorted(
            set(db_users["user_id"])
            | set(logins["user_id"])
        )

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

        # Step 4 — Visit durations
        with st.spinner("Fetching session durations..."):
            visit_durations = _cached_visit_durations(date_range)

        # Step 5 — Build merged DataFrames
        with st.spinner("Building report..."):
            user_detail = merger.build_user_detail(
                db_users, logins, last_login, visit_durations, activity_completions,
            )
            org_summary = merger.build_org_summary(
                user_detail, sessions, star_ratings, org_user_counts,
            )
            global_summary = merger.build_global_summary(org_summary, bundle_counts)

        st.session_state.update({
            "user_detail": user_detail,
            "org_summary": org_summary,
            "global_summary": global_summary,
            "monthly_ratings": monthly_ratings,
            "bundle_counts": bundle_counts,
            "region": region,
            "fetched_region": region,
            "fetched_date_range": date_range,
        })

        st.success("Data loaded successfully.")

    except Exception as e:
        st.error(f"Error fetching data: {e}")


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

    # ── Tab 1: Global Overview ────────────────────────────────────────────────
    with tab1:
        st.subheader("Global Overview")

        metric_labels = {
            "total_organisations":          "Organisations",
            "total_users":                  "Total Users",
            "total_groups_created":         "Groups Created",
            "total_sessions_delivered":     "Sessions Delivered",
            "overall_groups_avg_rating":    "Avg Group Rating",
            "overall_therapists_avg_rating": "Avg Therapist Rating",
        }
        cols = st.columns(len(metric_labels))
        for col, (key, label) in zip(cols, metric_labels.items()):
            col.metric(label, global_summary[key])

        st.divider()

        st.markdown("**Logins by Organisation**")
        chart_data = (
            org_summary.set_index("organisation_name")["logins"]
            .sort_values(ascending=False)
        )
        st.bar_chart(chart_data)

        st.markdown("**Monthly Average Star Ratings**")
        if not monthly_ratings.empty:
            monthly_pivot = (
                monthly_ratings
                .groupby(["month", "target"])["avg_rating"]
                .mean()
                .reset_index()
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

    # ── Tab 2: By Organisation ────────────────────────────────────────────────
    with tab2:
        st.subheader("By Organisation")
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
                    help="Users with 2 or more logins in the reporting period",
                ),
                "logins": st.column_config.NumberColumn(
                    help="Number of Matomo visits (browser sessions) in the reporting period",
                ),
                "avg_real_session_minutes": st.column_config.NumberColumn(
                    help=(
                        "Mean duration (minutes) of deliver-mode visits over 20 minutes "
                        "— treated as genuine CST session deliveries"
                    ),
                    format="%.1f",
                ),
                "avg_prepare_minutes": st.column_config.NumberColumn(
                    help="Mean duration (minutes) of prepare-only visits (no deliver-mode actions)",
                    format="%.1f",
                ),
                "short_visit_count": st.column_config.NumberColumn(
                    help=(
                        "Count of deliver-mode visits 20 minutes or under — treated as check-ins "
                        "or browsing, not real sessions"
                    ),
                ),
                "sessions_delivered": st.column_config.NumberColumn(
                    help=(
                        "Unique CST therapy sessions delivered in the reporting period — counted as "
                        "unique (bundle + session ID) pairs with at least one deliver-mode action. "
                        "Different unit from visit-based duration metrics."
                    ),
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

    # ── Tab 3: By User ────────────────────────────────────────────────────────
    with tab3:
        st.subheader("By User")
        org_filter = st.text_input("Filter by organisation name")
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
                    help="Number of Matomo visits (browser sessions) in the reporting period",
                ),
                "avg_real_session_minutes": st.column_config.NumberColumn(
                    help=(
                        "Mean duration (minutes) of deliver-mode visits over 20 minutes "
                        "— treated as genuine CST session deliveries"
                    ),
                    format="%.1f",
                ),
                "avg_prepare_minutes": st.column_config.NumberColumn(
                    help="Mean duration (minutes) of prepare-only visits (no deliver-mode actions)",
                    format="%.1f",
                ),
                "short_visit_count": st.column_config.NumberColumn(
                    help=(
                        "Count of deliver-mode visits 20 minutes or under — treated as check-ins "
                        "or browsing"
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
    excel_bytes = exporter.build_excel_report(
        st.session_state["user_detail"],
        st.session_state["org_summary"],
        st.session_state["monthly_ratings"],
        st.session_state["region"],
        st.session_state["fetched_date_range"],
    )
    st.download_button(
        label="Download Excel Report",
        data=excel_bytes,
        file_name=f"ayla_usage_{st.session_state['region']}_{date.today()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
