# Streamlit entry point: sidebar region selector, three-tab layout (Global Overview, By Organisation, By User).

import streamlit as st
from datetime import date, timedelta

import database
import matomo
import merger
import exporter

st.set_page_config(page_title="Ayla Usage Dashboard", layout="wide")


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

    st.markdown("**30-day window**")
    start_30 = st.date_input("From", today - timedelta(days=30), key="start_30")
    end_30 = st.date_input("To", today, key="end_30")

    st.markdown("**90-day window**")
    start_90 = st.date_input("From", today - timedelta(days=90), key="start_90")
    end_90 = st.date_input("To", today, key="end_90")

    pull = st.button("Pull Data", type="primary")
    st.caption("Pulling last login data may take a few minutes")

date_range_30 = f"{start_30},{end_30}"
date_range_90 = f"{start_90},{end_90}"


# ── data fetching ─────────────────────────────────────────────────────────────

if pull:
    try:
        # Step 1 — DB queries (fast)
        with st.spinner("Querying database..."):
            db_users = database.load_users_and_orgs(region)
            org_user_counts = database.get_org_user_counts(region)
            bundle_counts = database.get_bundle_counts_per_org(region)
            star_ratings = database.get_star_ratings_by_org(region)
            monthly_ratings = database.get_monthly_star_ratings(region)

        # Step 2 — Matomo queries (cached after first run)
        with st.spinner("Fetching Matomo analytics..."):
            logins_30 = _cached_logins(date_range_30)
            logins_90 = _cached_logins(date_range_90)
            sessions_30 = _cached_sessions_delivered(date_range_30)
            sessions_90 = _cached_sessions_delivered(date_range_90)
            activity_completions = _cached_activity_completions(date_range_30)

        # Step 3 — Last login per user (slowest — show progress)
        all_user_ids = sorted(
            set(db_users["user_id"])
            | set(logins_30["user_id"])
            | set(logins_90["user_id"])
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
            visit_durations = _cached_visit_durations(date_range_30)

        # Step 5 — Build merged DataFrames
        with st.spinner("Building report..."):
            user_detail = merger.build_user_detail(
                db_users, logins_30, logins_90, last_login, visit_durations, activity_completions,
            )
            org_summary = merger.build_org_summary(
                user_detail, sessions_30, sessions_90, star_ratings, org_user_counts,
            )
            global_summary = merger.build_global_summary(org_summary, bundle_counts)

        st.session_state.update({
            "user_detail": user_detail,
            "org_summary": org_summary,
            "global_summary": global_summary,
            "monthly_ratings": monthly_ratings,
            "bundle_counts": bundle_counts,
            "region": region,
            "date_range_30": date_range_30,
            "date_range_90": date_range_90,
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
            "total_sessions_delivered_30":  "Sessions Delivered (30 days)",
            "total_sessions_delivered_90":  "Sessions Delivered (90 days)",
            "overall_groups_avg_rating":    "Avg Group Rating",
            "overall_therapists_avg_rating": "Avg Therapist Rating",
        }
        cols = st.columns(len(metric_labels))
        for col, (key, label) in zip(cols, metric_labels.items()):
            col.metric(label, global_summary[key])

        st.divider()

        st.markdown("**Logins by Organisation (30 days)**")
        chart_data = (
            org_summary.set_index("organisation_name")["logins_30_days"]
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
            org_summary.style.format(
                {
                    "avg_real_session_minutes": "{:.1f}",
                    "avg_prepare_minutes":      "{:.1f}",
                    "groups_avg_rating":        "{:.2f}",
                    "therapists_avg_rating":    "{:.2f}",
                },
                na_rep="—",
            ),
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
        st.dataframe(filtered, use_container_width=True)


# ── download button ───────────────────────────────────────────────────────────

if "user_detail" in st.session_state:
    st.divider()
    excel_bytes = exporter.build_excel_report(
        st.session_state["user_detail"],
        st.session_state["org_summary"],
        st.session_state["monthly_ratings"],
        st.session_state["region"],
        st.session_state["date_range_30"],
        st.session_state["date_range_90"],
    )
    st.download_button(
        label="Download Excel Report",
        data=excel_bytes,
        file_name=f"ayla_usage_{st.session_state['region']}_{date.today()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
