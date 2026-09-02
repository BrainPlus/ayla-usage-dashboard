"""
Streamlit-side mirror of the Rails `usage_analytics:validate` task.

Prints the same fields, in the same layout, computed from this repo's own
database.py / matomo.py / merger.py — so you can run both and eyeball them
side by side. See ../cst-backend/docs/usage_dashboard_validation.md.

    python validate.py                       # the standard cases (mirror of Rails)
    python validate.py --org "Long Eaton View" --from 2026-05-19 --to 2026-08-17
    python validate.py --no-history          # skip the full-history Matomo pull
    python validate.py --region uk

Notes
-----
* Reads credentials from .streamlit/secrets.toml (same as the app).
* The rating and feedback numbers come from Postgres only.
* Sessions delivered, the funnel, groups delivered, latest delivery, status and
  top groups come from the Matomo API. If the Matomo token is missing or
  rejected those rows print "MATOMO UNAVAILABLE" and the rest still works.
* "Status" is derived with the Rails thresholds (active <= 14 days since last
  completion, slowing <= 59) so it lines up with the Rails task; Streamlit's own
  UI does not show an org-level active/slowing/inactive value.
"""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from datetime import date

import pandas as pd

logging.getLogger("streamlit").setLevel(logging.CRITICAL)
logging.disable(logging.WARNING)  # silence "No runtime found" cache warnings from bare imports
warnings.filterwarnings("ignore")

import database  # noqa: E402
import matomo  # noqa: E402
import merger  # noqa: E402

ACTIVE_DAYS = 14
SLOWING_DAYS = 59

# Mirror of UsageAnalytics::ValidationReport::STANDARD_CASES in cst-backend.
STANDARD_CASES = [
    ("TLC report period", "Home Instead Trainers", "2026-05-19", "2026-08-17"),
    ("No delivery in range", "Willow Bank", "2026-05-19", "2026-08-17"),
    ("Active site", "Long Eaton View", "2026-05-19", "2026-08-17"),
    ("Slowing site", "Oakland Court", "2026-05-19", "2026-08-17"),
    ("Short range (week/month edge)", "Long Eaton View", "2026-06-28", "2026-07-06"),
    ("Repeat completions in separate visits", "Brain+", "2026-05-19", "2026-08-17"),
    ("Duplicate completion in one visit", "Cambridge Manor", "2026-05-19", "2026-08-17"),
]

FIELDS = [
    "Sessions delivered",
    "Latest delivery",
    "Status",
    "Group rating (avg)",
    "Group rating (responses)",
    "Feedback: groups",
    "Feedback: therapists",
    "Groups delivered",
    "Funnel: Deliver Selected",
    "Funnel: Active Delivery",
    "Funnel: Completed Session",
    "Top groups",
]

_MATOMO_UNAVAILABLE = "MATOMO UNAVAILABLE (check matomo_token in .streamlit/secrets.toml)"

# Cache the Matomo-wide visit pull per date range across cases in one run.
_visit_cache: dict[str, list | None] = {}


def _live_visits(date_range: str) -> list | None:
    if date_range not in _visit_cache:
        try:
            _visit_cache[date_range] = matomo.get_live_visits(date_range)
        except Exception as exc:  # noqa: BLE001 - surface any Matomo failure as unavailable
            print(f"  ! Matomo pull for {date_range} failed: {exc}", file=sys.stderr)
            _visit_cache[date_range] = None
    return _visit_cache[date_range]


def _resolve_org_id(region: str, name: str) -> int | None:
    orgs = database.get_organisations(region)
    hit = orgs[orgs["organisation_name"].str.lower() == name.strip().lower()]
    if hit.empty:
        hit = orgs[orgs["organisation_name"].str.lower().str.contains(name.strip().lower())]
    return None if hit.empty else int(hit.iloc[0]["organisation_id"])


def _status_from_days(days: float | None) -> str:
    if days is None:
        return "inactive"
    if days <= ACTIVE_DAYS:
        return "active"
    if days <= SLOWING_DAYS:
        return "slowing"
    return "inactive"


def _funnel_for_org(date_range: str, user_ids: set[str]) -> pd.DataFrame | None:
    visits = _live_visits(date_range)
    if visits is None:
        return None
    funnel = matomo.get_delivery_funnel_instances(date_range, visits=visits)
    return funnel[funnel["user_id"].astype(str).isin(user_ids)].reset_index(drop=True)


def _history_completions_for_org(
    region: str, org_id: int, user_ids: set[str], bundle_configs: pd.DataFrame, today: date
) -> pd.DataFrame | None:
    if bundle_configs.empty or "created_date" not in bundle_configs:
        return pd.DataFrame(columns=["visit_id", "bundle_id", "session_id", "user_id", "completion_date"])
    earliest = pd.to_datetime(bundle_configs["created_date"], errors="coerce").min()
    start = earliest.date() if pd.notna(earliest) else today
    try:
        history = matomo.get_delivery_funnel_instances_streamed(f"{start},{today}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ! Matomo history pull failed: {exc}", file=sys.stderr)
        return None
    completed = history[
        history["completed_session"] & history["user_id"].astype(str).isin(user_ids)
    ]
    return completed[
        ["visit_id", "bundle_id", "session_id", "user_id", "completed_session_date"]
    ].rename(columns={"completed_session_date": "completion_date"}).reset_index(drop=True)


def _top_groups(bundle_progression: pd.DataFrame, limit: int = 5) -> list[str]:
    if bundle_progression.empty:
        return []
    ordered = bundle_progression.sort_values(
        ["completed_configured_sessions", "bundle_name"], ascending=[False, True]
    ).head(limit)
    return [
        f"{row.bundle_name} ({int(row.completed_configured_sessions)}/{int(row.total_configured_sessions)})"
        for row in ordered.itertuples()
    ]


def evaluate(region: str, case_label: str, org_name: str, start: str, end: str, use_history: bool) -> dict:
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    date_range = f"{start},{end}"
    today = date.today()

    org_id = _resolve_org_id(region, org_name)
    row: dict[str, object] = {"name": case_label, "organisation": org_name, "from": start, "to": end}
    if org_id is None:
        row["found"] = False
        return row
    row["found"] = True

    users = database.load_users_and_orgs(region, org_id=org_id)
    user_ids = set(users["user_id"].astype(str))

    star = database.get_star_ratings_by_org(region, start_date, end_date, org_id=org_id)
    groups_rating = star[star["target"] == "groups"]
    feedback = database.get_feedback_submissions(region, start_date, end_date, org_id=org_id)
    bundle_configs = database.get_bundle_configurations(region, org_id=org_id)
    org_bundle_ids = set(bundle_configs["bundle_id"].astype(str))

    fields: dict[str, object] = {
        "Group rating (avg)": round(float(groups_rating["avg_rating"].iloc[0]), 2)
        if not groups_rating.empty
        else None,
        "Group rating (responses)": int(groups_rating["total_responses"].iloc[0])
        if not groups_rating.empty
        else 0,
        "Feedback: groups": int((feedback["target"] == "groups").sum()),
        "Feedback: therapists": int((feedback["target"] == "therapists").sum()),
    }

    period_funnel = _funnel_for_org(date_range, user_ids)
    if period_funnel is None:
        for key in ("Sessions delivered", "Groups delivered", "Funnel: Deliver Selected",
                    "Funnel: Active Delivery", "Funnel: Completed Session"):
            fields[key] = _MATOMO_UNAVAILABLE
    else:
        completed = period_funnel[period_funnel["completed_session"]]
        completed = completed[completed["bundle_id"].astype(str).isin(org_bundle_ids)]
        fields["Sessions delivered"] = int(len(completed))
        fields["Groups delivered"] = int(completed["bundle_id"].nunique())
        fields["Funnel: Deliver Selected"] = int(period_funnel["deliver_selected"].sum())
        fields["Funnel: Active Delivery"] = int(period_funnel["active_delivery"].sum())
        fields["Funnel: Completed Session"] = int(len(completed))

    if not use_history:
        # No history pull: best-effort latest delivery from the period funnel only.
        if period_funnel is None:
            fields["Latest delivery"] = _MATOMO_UNAVAILABLE
        else:
            in_period = period_funnel[
                period_funnel["completed_session"]
                & period_funnel["bundle_id"].astype(str).isin(org_bundle_ids)
            ]
            latest = in_period["completed_session_date"].max() if not in_period.empty else ""
            fields["Latest delivery"] = f"{latest} (period only)" if latest else None
        fields["Status"] = "n/a (--no-history)"
        fields["Top groups"] = "n/a (--no-history)"
    else:
        history_completions = _history_completions_for_org(
            region, org_id, user_ids, bundle_configs, today
        )
        if history_completions is None:
            fields["Latest delivery"] = _MATOMO_UNAVAILABLE
            fields["Status"] = _MATOMO_UNAVAILABLE
            fields["Top groups"] = _MATOMO_UNAVAILABLE
        else:
            completion_dates = pd.to_datetime(history_completions["completion_date"], errors="coerce")
            as_of_end = completion_dates[completion_dates.dt.date <= end_date]
            latest = as_of_end.max() if not as_of_end.empty else pd.NaT
            fields["Latest delivery"] = latest.date().isoformat() if pd.notna(latest) else None
            days = (end_date - latest.date()).days if pd.notna(latest) else None
            fields["Status"] = _status_from_days(days)

            progression = merger.build_bundle_progression(
                bundle_configs, history_completions, as_of_date=end_date
            )
            fields["Top groups"] = _top_groups(progression)

    row["fields"] = {key: fields.get(key) for key in FIELDS}
    return row


def _print_row(row: dict) -> None:
    print("=" * 72)
    print(f"{row['name']} — {row['organisation']}  ({row['from']} to {row['to']})")
    print("-" * 72)
    if not row.get("found"):
        print("  organisation not found in this database")
        return
    for label in FIELDS:
        value = row["fields"].get(label)
        printed = "; ".join(value) if isinstance(value, list) else repr(value)
        print(f"  {label.ljust(26)} {printed}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default="uk", choices=["uk", "eu"])
    parser.add_argument("--org")
    parser.add_argument("--from", dest="from_date")
    parser.add_argument("--to", dest="to_date")
    parser.add_argument("--no-history", action="store_true", help="skip the full-history Matomo pull")
    args = parser.parse_args()

    if args.org:
        if not (args.from_date and args.to_date):
            parser.error("--org requires --from and --to")
        cases = [("Ad-hoc", args.org, args.from_date, args.to_date)]
    else:
        cases = STANDARD_CASES

    for case_label, org, start, end in cases:
        row = evaluate(args.region, case_label, org, start, end, use_history=not args.no_history)
        _print_row(row)

    print("=" * 72)
    print("Compare each number with `bin/rails usage_analytics:validate` in cst-backend.")
    print("Known differences: cst-backend/docs/usage_dashboard_validation.md")


if __name__ == "__main__":
    main()
