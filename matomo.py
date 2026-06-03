# All Matomo API calls: visits, session events, activity completions, custom dimension queries.
# ALWAYS include segment=customDimension10==false for session/activity/step event queries.

import io

import pandas as pd
import requests
import streamlit as st

REAL_SESSION_MIN_DURATION_SECONDS = 20 * 60


def _base_params() -> dict:
    return {
        "module": "API",
        "idSite": st.secrets["matomo_site_id"],
        "token_auth": st.secrets["matomo_token"],
    }


def matomo_get(params: dict, expect_csv: bool = False):
    """Make a Matomo API GET request, merging base params. Returns parsed JSON or raw CSV text."""
    merged = {**_base_params(), **params}
    if expect_csv:
        merged["format"] = "CSV"
    else:
        merged.setdefault("format", "JSON")

    response = requests.get(st.secrets["matomo_url"], params=merged, timeout=60)
    response.raise_for_status()

    if expect_csv:
        return response.text
    return response.json()


def get_logins_by_date_range(date_range: str) -> pd.DataFrame:
    """
    Fetches unique user logins within a date range.

    Matomo method: UserId.getUsers
    Segment: none (visit-level query — dimension10 filter does not apply)

    Args:
        date_range: "YYYY-MM-DD,YYYY-MM-DD"

    Returns:
        DataFrame with columns: user_id (str), visits (int)
    """
    csv_text = matomo_get(
        {
            "method": "UserId.getUsers",
            "period": "range",
            "date": date_range,
            "filter_limit": 10000,
        },
        expect_csv=True,
    )

    df = pd.read_csv(io.StringIO(csv_text))
    # Matomo CSV uses "label" for the user identifier and "nb_visits" for visit count
    df = df.rename(columns={"label": "user_id", "nb_visits": "visits"})
    df["user_id"] = df["user_id"].astype(str)
    df["visits"] = pd.to_numeric(df["visits"], errors="coerce").fillna(0).astype(int)

    return df[["user_id", "visits"]].reset_index(drop=True)


def get_last_login_per_user(
    user_ids: list[str], progress_callback=None
) -> pd.DataFrame:
    """
    Fetches the most recent login date for each user.

    Matomo method: Live.getLastVisitsDetails (one call per user)
    Segment: userId=={user_id} — visit-level, no dimension10 filter needed.

    Args:
        user_ids: list of user ID strings
        progress_callback: optional callable(current: int, total: int)

    Returns:
        DataFrame with columns: user_id (str), last_login_date (str "YYYY-MM-DD")
    """
    records = []
    total = len(user_ids)

    for i, user_id in enumerate(user_ids):
        if progress_callback:
            progress_callback(i, total)

        data = matomo_get(
            {
                "method": "Live.getLastVisitsDetails",
                "period": "range",
                "date": "last365",
                "segment": f"userId=={user_id}",
                "countVisitorsToFetch": 1,
                "doNotFetchActions": 1,
                "filter_limit": 1,
            }
        )

        last_login_date = ""
        if isinstance(data, list) and data:
            visit = data[0]
            raw = visit.get("lastActionDateTime") or visit.get("serverDate", "")
            last_login_date = raw[:10] if raw else ""

        records.append({"user_id": str(user_id), "last_login_date": last_login_date})

    if progress_callback:
        progress_callback(total, total)

    return pd.DataFrame(records, columns=["user_id", "last_login_date"])


def get_visit_durations(date_range: str) -> pd.DataFrame:
    """
    Fetches raw visit durations over a date range.

    Matomo method: Live.getLastVisitsDetails (single bulk call)
    Segment: none — visit-level data, dimension10 filter does not apply.
    visitDuration (seconds) is read directly from each visit object.

    Args:
        date_range: "YYYY-MM-DD,YYYY-MM-DD"

    Returns:
        DataFrame with columns:
            user_id (str), visit_duration_seconds (float), has_deliver_action (bool)
    """
    columns = ["user_id", "visit_duration_seconds", "has_deliver_action"]
    data = matomo_get(
        {
            "method": "Live.getLastVisitsDetails",
            "period": "range",
            "date": date_range,
            "filter_limit": 10000,
        }
    )

    if not isinstance(data, list):
        return pd.DataFrame(columns=columns)

    records = []
    for visit in data:
        user_id = visit.get("userId")
        if not user_id:
            continue
        has_deliver_action = any(
            _extract_dimension(action, "10") == "false"
            for action in visit.get("actionDetails", [])
        )
        records.append(
            {
                "user_id": str(user_id),
                "visit_duration_seconds": float(visit.get("visitDuration") or 0),
                "has_deliver_action": has_deliver_action,
            }
        )

    return pd.DataFrame(records, columns=columns)


def get_sessions_delivered(date_range: str) -> pd.DataFrame:
    """
    Fetches delivered session instances as (bundleId, sessionId, userId) rows.

    Matomo method: Live.getLastVisitsDetails (no segment filter — filtered in Python)
    Real delivered-session filter: only visits longer than 20 minutes are
    eligible, and only actions where dimension10 == "false" are included;
    dimension10 == "true" (prepare/edit mode) actions are skipped.

    bundle_id comes from dimension14 (customBundleId — the DB integer bundle ID).
    session_id comes from dimension5.

    Args:
        date_range: "YYYY-MM-DD,YYYY-MM-DD"

    Returns:
        DataFrame with columns: bundle_id (str), session_id (str), user_id (str)
        Deduplicate on (bundle_id, session_id, user_id) before counting.
    """
    data = matomo_get(
        {
            "method": "Live.getLastVisitsDetails",
            "period": "range",
            "date": date_range,
            "filter_limit": 10000,
        }
    )

    if not isinstance(data, list):
        return pd.DataFrame(columns=["bundle_id", "session_id", "user_id"])

    records = []
    for visit in data:
        user_id = str(visit.get("userId", ""))
        seen = set()
        for action in visit.get("actionDetails", []):
            if _extract_dimension(action, "10") != "false":
                continue
            b = _extract_dimension(action, "14")
            s = _extract_dimension(action, "5")
            if b and s and (b, s) not in seen:
                seen.add((b, s))
                records.append({"bundle_id": b, "session_id": s, "user_id": user_id})

    return pd.DataFrame(records, columns=["bundle_id", "session_id", "user_id"])


def get_activity_completions_per_user(date_range: str) -> pd.DataFrame:
    """
    Counts completed activities per user in delivered sessions only.

    Matomo method: Live.getLastVisitsDetails (no segment filter — filtered in Python)
    Counts actions where type="event", eventCategory="Activity",
    eventAction="Activity Complete", AND dimension10=="false" (deliver mode only).

    Args:
        date_range: "YYYY-MM-DD,YYYY-MM-DD"

    Returns:
        DataFrame with columns: user_id (str), activities_completed (int)
    """
    data = matomo_get(
        {
            "method": "Live.getLastVisitsDetails",
            "period": "range",
            "date": date_range,
            "filter_limit": 10000,
        }
    )

    if not isinstance(data, list):
        return pd.DataFrame(columns=["user_id", "activities_completed"])

    counts: dict[str, int] = {}
    for visit in data:
        user_id = str(visit.get("userId", ""))
        for action in visit.get("actionDetails", []):
            if (
                _extract_dimension(action, "10") == "false"
                and action.get("type") == "event"
                and action.get("eventCategory") == "Activity"
                and action.get("eventAction") == "Activity Complete"
            ):
                counts[user_id] = counts.get(user_id, 0) + 1

    records = [
        {"user_id": uid, "activities_completed": cnt} for uid, cnt in counts.items()
    ]
    return pd.DataFrame(records, columns=["user_id", "activities_completed"])


def get_activity_usage_by_id(date_range: str) -> pd.DataFrame:
    """
    Counts Activity Complete events per activityId in delivered sessions only.

    Matomo method: Live.getLastVisitsDetails (no segment filter — filtered in Python)
    Counts actions where type="event", eventCategory="Activity",
    eventAction="Activity Complete", AND dimension10=="false" (deliver mode only).
    activityId comes from dimension6.

    Args:
        date_range: "YYYY-MM-DD,YYYY-MM-DD"

    Returns:
        DataFrame with columns: activity_id (str), completion_count (int)
    """
    empty = pd.DataFrame(columns=["activity_id", "completion_count"])
    data = matomo_get(
        {
            "method": "Live.getLastVisitsDetails",
            "period": "range",
            "date": date_range,
            "filter_limit": 10000,
        }
    )

    if not isinstance(data, list):
        return empty

    counts: dict[str, int] = {}
    for visit in data:
        for action in visit.get("actionDetails", []):
            if (
                _extract_dimension(action, "10") == "false"
                and action.get("type") == "event"
                and action.get("eventCategory") == "Activity"
                and action.get("eventAction") == "Activity Complete"
            ):
                activity_id = _extract_dimension(action, "6")
                if activity_id:
                    counts[activity_id] = counts.get(activity_id, 0) + 1

    if not counts:
        return empty
    df = pd.DataFrame(
        [{"activity_id": k, "completion_count": v} for k, v in counts.items()]
    )
    df["activity_id"] = df["activity_id"].astype(str)
    df["completion_count"] = df["completion_count"].astype(int)
    return df


# --- helpers ---


def _extract_dimension(obj: dict, dim_number: str) -> str:
    """
    Extract a custom dimension value from a Matomo visit or action dict.

    Handles four response shapes observed in the Live API:
      - Shape 1 (action-level): {"dimension4": "value"}          ← Live API actionDetails
      - Shape 2 (visit-level):  {"customDimension4": "value"}
      - Shape 3 (nested dict):  {"customDimensions": {"4": {"value": "..."}} }
      - Shape 4 (array):        {"customDimensions": [{"index": 4, "value": "..."}]}
    """
    # Shape 1: bare "dimensionN" key — used in Live API actionDetails
    bare = obj.get(f"dimension{dim_number}", "")
    if bare:
        return str(bare)

    # Shape 2: "customDimensionN" flat key
    flat = obj.get(f"customDimension{dim_number}", "")
    if flat:
        return str(flat)

    dims = obj.get("customDimensions")
    if not dims:
        return ""

    # Shape 3: nested dict {"4": {"value": "..."}}
    if isinstance(dims, dict):
        entry = dims.get(dim_number, {})
        return entry.get("value", "") if isinstance(entry, dict) else str(entry)

    # Shape 4: array [{"index": 4, "value": "..."}]
    if isinstance(dims, list):
        for item in dims:
            if str(item.get("index", "")) == dim_number:
                return str(item.get("value", ""))

    return ""


if __name__ == "__main__":
    from datetime import date, timedelta

    today = date.today()
    week_ago = today - timedelta(days=7)
    date_range = f"{week_ago},{today}"

    print(f"Fetching logins for {date_range} ...")
    df = get_logins_by_date_range(date_range)
    print(df.head())
