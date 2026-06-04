#!/usr/bin/env python3
"""
One-off: time spent per talking point during delivered sessions (all regions).

Method: delta between consecutive 'Step Forward Click' events (category='Activity',
dimension10=='false') within the same visit, sorted by serverTimestamp.

Outputs talking_point_times.csv + prints a summary to stdout.

Usage:
    python explore_talking_point_time.py

Requires .streamlit/secrets.toml with matomo_url, matomo_token, matomo_site_id
at the top level.
"""

import csv
import sys
import tomllib
from datetime import date, timedelta
from pathlib import Path

import requests

import squidex

# --- config ---

SECRETS_PATH = Path(__file__).parent / ".streamlit" / "secrets.toml"
DATE_RANGE = f"{date.today() - timedelta(days=90)},{date.today()}"
QUICK_THRESHOLD_S = 10   # below this = "skipping through"
IDLE_THRESHOLD_S = 600   # above this = left the app open, exclude from stats
OUTPUT_CSV = Path(__file__).parent / "talking_point_times.csv"

# --- load secrets ---

with open(SECRETS_PATH, "rb") as f:
    _secrets = tomllib.load(f)

_MATOMO_URL = _secrets["matomo_url"]
_MATOMO_SITE_ID = _secrets["matomo_site_id"]
_MATOMO_TOKEN = _secrets["matomo_token"]


# --- helpers ---

def _matomo_get(params: dict) -> list | dict:
    r = requests.get(
        _MATOMO_URL,
        params={"module": "API", "format": "JSON", "idSite": _MATOMO_SITE_ID,
                "token_auth": _MATOMO_TOKEN, **params},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


def _dim(action: dict, n: str) -> str:
    """Extract custom dimension from a Matomo actionDetail object."""
    v = action.get(f"dimension{n}", "")
    if v:
        return str(v)
    v = action.get(f"customDimension{n}", "")
    if v:
        return str(v)
    dims = action.get("customDimensions")
    if not dims:
        return ""
    if isinstance(dims, dict):
        entry = dims.get(n, {})
        return entry.get("value", "") if isinstance(entry, dict) else str(entry)
    if isinstance(dims, list):
        for item in dims:
            if str(item.get("index", "")) == n:
                return str(item.get("value", ""))
    return ""


def _percentile(sorted_values: list[int | float], p: int) -> int | float:
    if not sorted_values:
        return 0
    idx = max(0, int(len(sorted_values) * p / 100) - 1)
    return sorted_values[idx]


# --- fetch ---

print(f"Fetching visits for {DATE_RANGE} (all regions)...", flush=True)

raw = _matomo_get({
    "method": "Live.getLastVisitsDetails",
    "period": "range",
    "date": DATE_RANGE,
    "filter_limit": 10000,
})

if not isinstance(raw, list):
    print(f"Unexpected response: {raw}", file=sys.stderr)
    sys.exit(1)

print(f"Got {len(raw)} visits.", flush=True)

# --- fetch activity names from Squidex ---

print("Fetching activity catalogue from Squidex...", flush=True)
_squidex_settings = squidex.get_settings_from_secrets(_secrets)
if _squidex_settings:
    base_url, project, client_id, client_secret = _squidex_settings
    token = squidex.get_access_token(base_url, client_id, client_secret)
    activity_names: dict[str, str] = squidex.get_activity_catalogue(base_url, project, token)
    print(f"Got {len(activity_names)} activity names.", flush=True)
else:
    activity_names = {}
    print("Squidex secrets not configured — activity_name column will be empty.", flush=True)

# --- extract forward-click events and compute deltas ---

rows = []

for visit in raw:
    # Collect all deliver-mode "Step Forward Click" events with timestamps
    clicks = []
    for action in visit.get("actionDetails", []):
        if (
            _dim(action, "10") != "false"
            or action.get("eventCategory") != "Activity"
            or action.get("eventAction") != "Step Forward Click"
        ):
            continue
        ts = action.get("timestamp")
        if ts is None:
            continue
        clicks.append({
            "ts": int(ts),
            "session_id": _dim(action, "5"),
            "activity_id": _dim(action, "6"),
            "step_id": _dim(action, "7"),
            "bundle_id": _dim(action, "14"),
            "route": _dim(action, "11"),
        })

    if len(clicks) < 2:
        continue

    clicks.sort(key=lambda x: x["ts"])

    # Delta between click N and click N+1 = time the therapist spent on talking point N
    for i in range(len(clicks) - 1):
        curr = clicks[i]
        delta = clicks[i + 1]["ts"] - curr["ts"]
        rows.append({
            "bundle_id": curr["bundle_id"],
            "session_id": curr["session_id"],
            "activity_id": curr["activity_id"],
            "activity_name": activity_names.get(curr["activity_id"], ""),
            "step_id": curr["step_id"],
            "route": curr["route"],
            "duration_seconds": delta,
            "is_quick": delta < QUICK_THRESHOLD_S,
            "is_idle": delta > IDLE_THRESHOLD_S,
        })

# --- write CSV ---

fieldnames = ["bundle_id", "session_id", "activity_id", "activity_name",
              "step_id", "route", "duration_seconds", "is_quick", "is_idle"]

with open(OUTPUT_CSV, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"\nCSV written to {OUTPUT_CSV}  ({len(rows)} rows)")

# --- summary stats ---

active = [r["duration_seconds"] for r in rows if not r["is_idle"]]
active.sort()
quick = [d for d in active if d < QUICK_THRESHOLD_S]

print(f"\n--- Summary (excluding idle gaps > {IDLE_THRESHOLD_S}s) ---")
print(f"Total talking-point transitions:  {len(rows)}")
print(f"Active transitions:               {len(active)}")
print(f"Quick (< {QUICK_THRESHOLD_S}s):                   "
      f"{len(quick)}  ({100 * len(quick) / len(active):.1f}% of active)" if active else "n/a")

if active:
    print(f"\nDuration distribution (seconds):")
    print(f"  min:    {active[0]}")
    print(f"  p10:    {_percentile(active, 10)}")
    print(f"  p25:    {_percentile(active, 25)}")
    print(f"  median: {_percentile(active, 50)}")
    print(f"  p75:    {_percentile(active, 75)}")
    print(f"  p90:    {_percentile(active, 90)}")
    print(f"  max:    {active[-1]}")

# Breakdown by route (activity type)
if rows:
    from collections import defaultdict
    by_route: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        if not r["is_idle"]:
            by_route[r["route"] or "(unknown)"].append(r["duration_seconds"])

    print(f"\nMedian duration by route (active only):")
    for route, durations in sorted(by_route.items()):
        durations.sort()
        med = _percentile(durations, 50)
        quick_pct = 100 * sum(1 for d in durations if d < QUICK_THRESHOLD_S) / len(durations)
        print(f"  {route:<55} n={len(durations):>5}  median={med:>4}s  quick={quick_pct:.0f}%")
