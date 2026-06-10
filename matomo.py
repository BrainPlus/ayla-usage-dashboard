# All Matomo API calls: visits, session events, activity completions, custom dimension queries.
# Deliver-mode filtering checks dimension10 on fetched actions in Python — dimension10=="false"
# is never used as a Matomo source segment because the Live API returns custom dimensions as
# bare `dimensionN` keys, and the segment engine cannot match them on this instance (returns
# 0 results). Python-level filtering via _extract_dimension is the authoritative filter.
# Do not apply dimension13 as a source-side Matomo segment.

import io
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st

REAL_SESSION_MIN_DURATION_SECONDS = 20 * 60
_DELIVER_SELECTED_EVENT = "Prepare/Deliver dialog - Deliver Click"
_ACTIVE_DELIVERY_EVENTS = frozenset(
    {
        "Step Complete",
        "Activity Complete",
        "Reality Orientation Date Set",
        "Reality Orientation Time Set",
        "Reality Orientation Song Set",
        "Reality Orientation Group Name Set",
        "Reality Orientation YouTube Playlist Changed",
        "Main Activity Card Start Click",
    }
)

# Keep org_id on bulk-query signatures for caller/cache compatibility. Do not
# send dimension13 as a source segment: production checks found 56-78% undercounting.


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


def _fetch_all_live_visits(base_params: dict, page_size: int = 5000) -> list:
    """Paginate Live.getLastVisitsDetails until all visits in the date range are fetched."""
    all_visits: list = []
    offset = 0
    while True:
        data = matomo_get({**base_params, "filter_limit": page_size, "filter_offset": offset})
        if not isinstance(data, list):
            raise RuntimeError(
                f"Matomo returned a non-list response (type {type(data).__name__!r}) "
                f"at offset {offset}."
            )
        if not data:
            break  # empty page → all pages consumed
        all_visits.extend(data)
        if len(data) < page_size:
            break  # partial page → last page
        offset += len(data)
    return all_visits


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


def get_login_form_outcomes(
    date_range: str,
    allowed_user_ids: frozenset[str],
) -> dict[str, int]:
    """
    Count login form attempts, successes, and failures in a date range.

    Attempts and failures happen before authentication, so they cannot be
    reliably filtered by region. Successes are restricted to identified users
    in the selected region.
    """
    outcomes = {"attempts": 0, "successes": 0, "failures": 0}
    event_keys = {
        "Submit Login Form": "attempts",
        "Submit Login Form Success": "successes",
        "Submit Login Form Failure": "failures",
    }
    data = _fetch_all_live_visits(
        {
            "method": "Live.getLastVisitsDetails",
            "period": "range",
            "date": date_range,
        }
    )

    for visit in data:
        user_id = str(visit.get("userId", ""))
        for action in visit.get("actionDetails", []):
            if action.get("type") != "event":
                continue
            outcome = event_keys.get(action.get("eventAction"))
            if outcome is None:
                continue
            if outcome == "successes" and user_id not in allowed_user_ids:
                continue
            outcomes[outcome] += 1

    return outcomes


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


def get_visit_durations(date_range: str, org_id=None) -> pd.DataFrame:
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
    data = _fetch_all_live_visits(
        {
            "method": "Live.getLastVisitsDetails",
            "period": "range",
            "date": date_range,
        }
    )

    if not data:
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


def get_completed_sessions(date_range: str, org_id=None) -> pd.DataFrame:
    """
    Fetches completed session instances.

    Matomo method: Live.getLastVisitsDetails (no segment — filtered per action in Python)
    Counts Session Complete events where dimension10 == "false". Prepare-mode
    Session Complete events and non-completion deliver-mode actions are skipped.
    Repeated events for the same CST session within one Matomo visit are
    deduplicated, while completions in separate visits are counted separately.

    bundle_id comes from dimension14 (customBundleId — the DB integer bundle ID).
    session_id comes from dimension5.

    Args:
        date_range: "YYYY-MM-DD,YYYY-MM-DD"

    Returns:
        DataFrame with columns: visit_id, bundle_id, session_id, user_id
        Deduplicated on (visit_id, bundle_id, session_id).
    """
    columns = ["visit_id", "bundle_id", "session_id", "user_id"]
    data = _fetch_all_live_visits(
        {
            "method": "Live.getLastVisitsDetails",
            "period": "range",
            "date": date_range,
        }
    )

    if not data:
        return pd.DataFrame(columns=columns)

    instances = _delivery_session_instances_from_visits(data)
    return instances.loc[
        instances["completed_session"], columns
    ].reset_index(drop=True)


def get_delivery_funnel_instances(date_range: str, org_id=None) -> pd.DataFrame:
    """
    Fetch delivery funnel signals deduplicated per CST session instance.

    Active Delivery requires both a Deliver Selected event and at least one
    high-confidence event from the #28 allowlist for the same
    (visit_id, bundle_id, session_id). Completed Session uses the same
    deliver-mode Session Complete definition as get_completed_sessions.
    """
    columns = [
        "visit_id",
        "bundle_id",
        "session_id",
        "user_id",
        "deliver_selected",
        "active_delivery",
        "completed_session",
        "completed_session_date",
    ]
    data = _fetch_all_live_visits(
        {
            "method": "Live.getLastVisitsDetails",
            "period": "range",
            "date": date_range,
        }
    )
    if not data:
        return pd.DataFrame(columns=columns)
    return _delivery_session_instances_from_visits(data)


def get_visit_dates(date_range: str, org_id=None) -> pd.DataFrame:
    """
    Fetches individual visit dates for all identified users.

    Matomo method: Live.getLastVisitsDetails (no segment filter — visit-level)
    Uses serverDate to bucket each visit to the day it started. Visits without
    a userId or without serverDate are skipped.
    org_id is accepted for caller/cache compatibility but not used as a segment.

    Args:
        date_range: "YYYY-MM-DD,YYYY-MM-DD"

    Returns:
        DataFrame with columns: user_id (str), visit_date (str "YYYY-MM-DD")
    """
    columns = ["user_id", "visit_date"]
    data = _fetch_all_live_visits(
        {
            "method": "Live.getLastVisitsDetails",
            "period": "range",
            "date": date_range,
            "doNotFetchActions": 1,
        }
    )

    if not data:
        return pd.DataFrame(columns=columns)

    records = []
    for visit in data:
        user_id = visit.get("userId")
        if not user_id:
            continue
        visit_date = visit.get("serverDate", "")
        if not visit_date:
            continue
        records.append({"user_id": str(user_id), "visit_date": str(visit_date)})

    return pd.DataFrame(records, columns=columns)


def get_activity_completions_per_user(date_range: str, org_id=None) -> pd.DataFrame:
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
    data = _fetch_all_live_visits(
        {
            "method": "Live.getLastVisitsDetails",
            "period": "range",
            "date": date_range,
        }
    )

    if not data:
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


def get_activity_usage_by_id(
    date_range: str,
    allowed_user_ids: frozenset[str] | None = None,
    org_id=None,
) -> pd.DataFrame:
    """
    Counts Activity Complete events per activityId and language in delivered sessions only.

    Matomo method: Live.getLastVisitsDetails (no segment filter — filtered in Python)
    Counts actions where type="event", eventCategory="Activity",
    eventAction="Activity Complete", AND dimension10=="false" (deliver mode only).
    activityId comes from dimension6.
    language comes from dimension2.

    Args:
        date_range: "YYYY-MM-DD,YYYY-MM-DD"
        allowed_user_ids: optional set of Matomo user IDs to include

    Returns:
        DataFrame with columns: activity_id (str), language (str), completion_count (int)
    """
    empty = pd.DataFrame(columns=["activity_id", "language", "completion_count"])
    data = _fetch_all_live_visits(
        {
            "method": "Live.getLastVisitsDetails",
            "period": "range",
            "date": date_range,
        },
        page_size=10000,
    )

    if not data:
        return empty

    counts: dict[tuple[str, str], int] = {}
    for visit in data:
        if (
            allowed_user_ids is not None
            and str(visit.get("userId", "")) not in allowed_user_ids
        ):
            continue
        for action in visit.get("actionDetails", []):
            if (
                _extract_dimension(action, "10") == "false"
                and action.get("type") == "event"
                and action.get("eventCategory") == "Activity"
                and action.get("eventAction") == "Activity Complete"
            ):
                activity_id = _extract_dimension(action, "6")
                if activity_id:
                    language = _extract_dimension(action, "2")
                    key = (activity_id, language)
                    counts[key] = counts.get(key, 0) + 1

    if not counts:
        return empty
    df = pd.DataFrame(
        [
            {
                "activity_id": activity_id,
                "language": language,
                "completion_count": count,
            }
            for (activity_id, language), count in counts.items()
        ]
    )
    df["activity_id"] = df["activity_id"].astype(str)
    df["language"] = df["language"].astype(str)
    df["completion_count"] = df["completion_count"].astype(int)
    return df


def get_step_completion_depth(
    date_range: str,
    allowed_user_ids: frozenset[str] | None = None,
    org_id=None,
) -> pd.DataFrame:
    """
    Fetches unique completed steps for delivered activity occurrences.

    Matomo method: Live.getLastVisitsDetails (no segment — filtered per action in Python)
    Counts Step Complete events where dimension10 == "false". Repeated events for
    the same step within one activity occurrence are deduplicated.

    An activity occurrence is identified by visit, bundle, session, and activity.
    dimension7 contains UUID step IDs. Step numbers are derived from the
    chronological order in which unique steps are completed within each activity
    occurrence, so repeated completions after backtracking do not inflate depth.

    Args:
        date_range: "YYYY-MM-DD,YYYY-MM-DD"
        allowed_user_ids: optional set of Matomo user IDs to include

    Returns:
        DataFrame with columns: activity_instance_id, user_id, activity_id,
        language, step_number
    """
    columns = [
        "activity_instance_id",
        "user_id",
        "activity_id",
        "language",
        "step_number",
    ]
    data = _fetch_all_live_visits(
        {
            "method": "Live.getLastVisitsDetails",
            "period": "range",
            "date": date_range,
        },
        page_size=10000,
    )

    if not data:
        return pd.DataFrame(columns=columns)

    records = []
    for visit_index, visit in enumerate(data):
        user_id = str(visit.get("userId", ""))
        if allowed_user_ids is not None and user_id not in allowed_user_ids:
            continue

        visit_id = str(visit.get("idVisit") or f"missing-{visit_index}")
        activity_events: dict[str, list[tuple[float, int, str, str, str]]] = {}
        for action_index, action in enumerate(visit.get("actionDetails", [])):
            if (
                _extract_dimension(action, "10") != "false"
                or action.get("type") != "event"
                or action.get("eventCategory") != "Step"
                or action.get("eventAction") != "Step Complete"
            ):
                continue

            activity_id = _extract_dimension(action, "6")
            step_id = _extract_dimension(action, "7")
            if not activity_id or not step_id:
                continue

            language = _extract_dimension(action, "2")
            bundle_id = _extract_dimension(action, "14")
            session_id = _extract_dimension(action, "5")
            if not bundle_id or not session_id:
                continue
            activity_instance_id = "|".join(
                [visit_id, bundle_id, session_id, activity_id]
            )
            try:
                timestamp = float(action.get("timestamp"))
            except (TypeError, ValueError):
                timestamp = float(action_index)
            activity_events.setdefault(activity_instance_id, []).append(
                (timestamp, action_index, step_id, activity_id, language)
            )

        for activity_instance_id, events in activity_events.items():
            seen_step_ids = set()
            step_number = 0
            for _, _, step_id, activity_id, language in sorted(events):
                if step_id in seen_step_ids:
                    continue
                seen_step_ids.add(step_id)
                step_number += 1
                records.append(
                    {
                        "activity_instance_id": activity_instance_id,
                        "user_id": user_id,
                        "activity_id": activity_id,
                        "language": language,
                        "step_number": step_number,
                    }
                )

    return pd.DataFrame(records, columns=columns)


def get_talking_point_engagement(
    date_range: str,
    allowed_user_ids: frozenset[str] | None = None,
    org_id=None,
) -> pd.DataFrame:
    """
    Counts Talking Point Expand Click and Step Forward Click events per activity
    in deliver-mode sessions only (dimension10 == false).

    Matomo method: Live.getLastVisitsDetails (no segment — filtered per action in Python)

    Args:
        date_range: "YYYY-MM-DD,YYYY-MM-DD"
        allowed_user_ids: optional set of Matomo user IDs to include

    Returns:
        DataFrame with columns: activity_id (str), language (str),
        expand_clicks (int), forward_clicks (int)
    """
    columns = ["activity_id", "language", "expand_clicks", "forward_clicks"]
    data = _fetch_all_live_visits(
        {
            "method": "Live.getLastVisitsDetails",
            "period": "range",
            "date": date_range,
        },
        page_size=10000,
    )

    if not data:
        return pd.DataFrame(columns=columns)

    expand_counts: dict[tuple[str, str], int] = {}
    forward_counts: dict[tuple[str, str], int] = {}

    for visit in data:
        if (
            allowed_user_ids is not None
            and str(visit.get("userId", "")) not in allowed_user_ids
        ):
            continue
        for action in visit.get("actionDetails", []):
            if (
                _extract_dimension(action, "10") != "false"
                or action.get("type") != "event"
            ):
                continue
            event_action = action.get("eventAction", "")
            if event_action not in ("Talking Point Expand Click", "Step Forward Click"):
                continue
            activity_id = _extract_dimension(action, "6")
            if not activity_id:
                continue
            language = _extract_dimension(action, "2")
            key = (activity_id, language)
            if event_action == "Talking Point Expand Click":
                expand_counts[key] = expand_counts.get(key, 0) + 1
            else:
                forward_counts[key] = forward_counts.get(key, 0) + 1

    all_keys = set(expand_counts) | set(forward_counts)
    if not all_keys:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(
        [
            {
                "activity_id": k[0],
                "language": k[1],
                "expand_clicks": expand_counts.get(k, 0),
                "forward_clicks": forward_counts.get(k, 0),
            }
            for k in all_keys
        ]
    )
    df["activity_id"] = df["activity_id"].astype(str)
    df["language"] = df["language"].astype(str)
    df["expand_clicks"] = df["expand_clicks"].astype(int)
    df["forward_clicks"] = df["forward_clicks"].astype(int)
    return df


def get_media_usage(
    date_range: str,
    allowed_user_ids: frozenset[str] | None = None,
    org_id=None,
) -> pd.DataFrame:
    """
    Counts audio and video interaction events per user and activity in
    deliver-mode sessions only (dimension10 == false).

    Matomo method: Live.getLastVisitsDetails (no segment — filtered per action in Python)
    eventCategory: Activity

    Audio events: Audio Button Click, Audio Play Click, Audio Pause Click
    Video events: Video Button Click, Video Play Click, Video Pause Click

    Args:
        date_range: "YYYY-MM-DD,YYYY-MM-DD"
        allowed_user_ids: optional set of Matomo user IDs to include

    Returns:
        DataFrame with columns: user_id (str), activity_id (str),
        audio_clicks (int), video_clicks (int)
    """
    columns = ["user_id", "activity_id", "audio_clicks", "video_clicks"]
    _AUDIO = frozenset(
        {"Audio Button Click", "Audio Play Click", "Audio Pause Click"}
    )
    _VIDEO = frozenset(
        {"Video Button Click", "Video Play Click", "Video Pause Click"}
    )

    data = _fetch_all_live_visits(
        {
            "method": "Live.getLastVisitsDetails",
            "period": "range",
            "date": date_range,
        },
        page_size=10000,
    )

    if not data:
        return pd.DataFrame(columns=columns)

    audio_counts: dict[tuple[str, str], int] = {}
    video_counts: dict[tuple[str, str], int] = {}

    for visit in data:
        user_id = str(visit.get("userId", ""))
        if allowed_user_ids is not None and user_id not in allowed_user_ids:
            continue
        for action in visit.get("actionDetails", []):
            if (
                _extract_dimension(action, "10") != "false"
                or action.get("type") != "event"
                or action.get("eventCategory") != "Activity"
            ):
                continue
            event_action = action.get("eventAction", "")
            activity_id = _extract_dimension(action, "6")
            key = (user_id, activity_id)
            if event_action in _AUDIO:
                audio_counts[key] = audio_counts.get(key, 0) + 1
            elif event_action in _VIDEO:
                video_counts[key] = video_counts.get(key, 0) + 1

    all_keys = set(audio_counts) | set(video_counts)
    if not all_keys:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(
        [
            {
                "user_id": k[0],
                "activity_id": k[1],
                "audio_clicks": audio_counts.get(k, 0),
                "video_clicks": video_counts.get(k, 0),
            }
            for k in all_keys
        ]
    )
    df["user_id"] = df["user_id"].astype(str)
    df["activity_id"] = df["activity_id"].astype(str)
    df["audio_clicks"] = df["audio_clicks"].astype(int)
    df["video_clicks"] = df["video_clicks"].astype(int)
    return df


def get_engagement_events(
    date_range: str,
    allowed_user_ids: frozenset[str] | None = None,
    org_id=None,
) -> pd.DataFrame:
    """
    Counts additional-activity acceptance and activity-replacement events per user
    in deliver-mode sessions only (dimension10 == false).

    Matomo method: Live.getLastVisitsDetails (no segment — filtered per action in Python)
    eventCategory: Activity

    Additional activity: Additional activity
    Main replacement: Change Main Activity Click
    Warmup replacement: Change Warmup Activity Click
    Reality orientation replacement: Change Reality Orientation Activity Click

    Args:
        date_range: "YYYY-MM-DD,YYYY-MM-DD"
        allowed_user_ids: optional set of Matomo user IDs to include

    Returns:
        DataFrame with columns: user_id (str), additional_activity_count (int),
        main_replacements (int), warmup_replacements (int), ro_replacements (int)
    """
    columns = [
        "user_id",
        "additional_activity_count",
        "main_replacements",
        "warmup_replacements",
        "ro_replacements",
    ]
    _ADDITIONAL = "Additional activity"
    _REPLACE_MAIN = "Change Main Activity Click"
    _REPLACE_WARMUP = "Change Warmup Activity Click"
    _REPLACE_RO = "Change Reality Orientation Activity Click"

    data = _fetch_all_live_visits(
        {
            "method": "Live.getLastVisitsDetails",
            "period": "range",
            "date": date_range,
        },
        page_size=10000,
    )

    if not data:
        return pd.DataFrame(columns=columns)

    additional: dict[str, int] = {}
    replace_main: dict[str, int] = {}
    replace_warmup: dict[str, int] = {}
    replace_ro: dict[str, int] = {}

    for visit in data:
        user_id = str(visit.get("userId", ""))
        if allowed_user_ids is not None and user_id not in allowed_user_ids:
            continue
        for action in visit.get("actionDetails", []):
            if (
                _extract_dimension(action, "10") != "false"
                or action.get("type") != "event"
                or action.get("eventCategory") != "Activity"
            ):
                continue
            event_action = action.get("eventAction", "")
            if event_action == _ADDITIONAL:
                additional[user_id] = additional.get(user_id, 0) + 1
            elif event_action == _REPLACE_MAIN:
                replace_main[user_id] = replace_main.get(user_id, 0) + 1
            elif event_action == _REPLACE_WARMUP:
                replace_warmup[user_id] = replace_warmup.get(user_id, 0) + 1
            elif event_action == _REPLACE_RO:
                replace_ro[user_id] = replace_ro.get(user_id, 0) + 1

    all_users = (
        set(additional) | set(replace_main) | set(replace_warmup) | set(replace_ro)
    )
    if not all_users:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(
        [
            {
                "user_id": uid,
                "additional_activity_count": additional.get(uid, 0),
                "main_replacements": replace_main.get(uid, 0),
                "warmup_replacements": replace_warmup.get(uid, 0),
                "ro_replacements": replace_ro.get(uid, 0),
            }
            for uid in all_users
        ]
    )
    df["user_id"] = df["user_id"].astype(str)
    for col in (
        "additional_activity_count",
        "main_replacements",
        "warmup_replacements",
        "ro_replacements",
    ):
        df[col] = df[col].astype(int)
    return df


# --- helpers ---


def _delivery_session_instances_from_visits(visits: list[dict]) -> pd.DataFrame:
    columns = [
        "visit_id",
        "bundle_id",
        "session_id",
        "user_id",
        "deliver_selected",
        "active_delivery",
        "completed_session",
        "completed_session_date",
    ]
    instances: dict[tuple[str, str, str], dict] = {}

    for visit_index, visit in enumerate(visits):
        visit_id = str(visit.get("idVisit") or f"missing-{visit_index}")
        user_id = str(visit.get("userId", ""))
        for action in visit.get("actionDetails", []):
            if (
                action.get("type") != "event"
                or _extract_dimension(action, "10") != "false"
            ):
                continue
            bundle_id = _extract_dimension(action, "14")
            session_id = _extract_dimension(action, "5")
            if not bundle_id or not session_id:
                continue

            event_action = action.get("eventAction", "")
            if (
                event_action != _DELIVER_SELECTED_EVENT
                and event_action not in _ACTIVE_DELIVERY_EVENTS
                and event_action != "Session Complete"
            ):
                continue

            key = (visit_id, bundle_id, session_id)
            instance = instances.setdefault(
                key,
                {
                    "visit_id": visit_id,
                    "bundle_id": bundle_id,
                    "session_id": session_id,
                    "user_id": user_id,
                    "deliver_selected": False,
                    "has_active_signal": False,
                    "completed_session": False,
                    "completed_session_date": "",
                },
            )
            if event_action == _DELIVER_SELECTED_EVENT:
                instance["deliver_selected"] = True
            elif event_action in _ACTIVE_DELIVERY_EVENTS:
                instance["has_active_signal"] = True
            elif event_action == "Session Complete":
                instance["completed_session"] = True
                completion_date = _event_date(action, visit)
                instance["completed_session_date"] = max(
                    instance["completed_session_date"], completion_date
                )

    records = []
    for instance in instances.values():
        instance["active_delivery"] = (
            instance["deliver_selected"] and instance.pop("has_active_signal")
        )
        records.append(instance)
    return pd.DataFrame(records, columns=columns)


def _event_date(action: dict, visit: dict) -> str:
    """Return an event's YYYY-MM-DD date, falling back to its visit date."""
    timestamp = pd.to_datetime(action.get("timestamp"), unit="s", utc=True, errors="coerce")
    if pd.notna(timestamp):
        return timestamp.date().isoformat()

    raw = (
        action.get("serverDate")
        or action.get("serverDateTime")
        or visit.get("lastActionDateTime")
        or visit.get("serverDate")
        or ""
    )
    return str(raw)[:10]


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
    today = date.today()
    week_ago = today - timedelta(days=7)
    date_range = f"{week_ago},{today}"

    print(f"Fetching logins for {date_range} ...")
    df = get_logins_by_date_range(date_range)
    print(df.head())
