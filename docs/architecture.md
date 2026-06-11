# Architecture

## Data Flow

The dashboard pulls from two independent sources — Matomo (usage analytics) and PostgreSQL (user/org identity) — merges them in memory, and renders the result in Streamlit.

```
┌─────────────────────────────────────────────────────────────────┐
│                          app.py (UI)                            │
│  sidebar: region selector, date pickers, Pull Data button       │
└───────────┬─────────────────────────┬───────────────────────────┘
            │                         │
            ▼                         ▼
┌───────────────────┐       ┌───────────────────┐
│    matomo.py      │       │   database.py     │
│  Matomo HTTP API  │       │  PostgreSQL via   │
│  (shared, 1 inst) │       │  SQLAlchemy       │
└───────────┬───────┘       └─────────┬─────────┘
            │                         │
            │   DataFrames            │   DataFrames
            └────────────┬────────────┘
                         ▼
              ┌─────────────────────┐
              │     merger.py       │
              │  pandas joins and   │
              │  aggregations       │
              └──────────┬──────────┘
                         │
              ┌──────────▼──────────┐
              │      app.py (tabs)  │
              │  Global Overview    │
              │  By Organisation    │
              │  By User            │
              └──────────┬──────────┘
                         │
              ┌──────────▼──────────┐
              │     exporter.py     │
              │  .xlsx download     │
              └─────────────────────┘
```

### Step-by-step pull sequence (triggered by "Pull Data")

1. **DB queries** — `database.py` runs the PostgreSQL queries sequentially to stay within the production database's limited connection slots.

2. **Matomo bulk queries** (medium, cached 1h) — `matomo.py` fetches the full action-level Live visit payload once for the selected reporting period and, when required for bundle progression, once for bundle history. All selected-period metrics derive from the shared payload rather than downloading the same visits independently. Before any raw Matomo rows are aggregated directly, `app.py` restricts them to user IDs loaded from the selected region's database.

3. **Last login per user** (slow, ~30–60 s for 100 users) — one `Live.getLastVisitsDetails` call per user, parallelised with up to 10 concurrent workers. Progress is collected via `as_completed` on the calling thread so Streamlit UI updates stay on the main thread. Not cached because caching would skip the progress callback.

4. **Avg session duration** (fast, 1 API call, cached 1h) — a single `Live.getLastVisitsDetails` call; duration is extracted and averaged per user in pandas.

5. **Merge** — `merger.py` left-joins all Matomo DataFrames onto the DB user list and aggregates up to org and global level.

The sidebar can skip the full-history bundle-progression pull and/or the per-user
last-login lookup. Skipped history-dependent fields are marked unavailable rather
than being reported as zero or not started.

### Regional boundary for raw Matomo aggregates

Matomo is shared by the UK and EU deployments, so a raw Matomo result is not region-scoped by default. Any chart or metric that aggregates raw Matomo data without first joining it to the selected region's database users must receive or apply the `database_user_ids` allowlist before aggregation.

- `Activity Usage` passes the allowlist into `matomo.get_activity_usage_by_id`, because that function aggregates events internally.
- `Daily Visit Activity` filters the raw `get_visit_dates` rows in `app.py` before `merger.build_daily_visit_activity` aggregates them.
- Organisation and user summaries are already region-scoped by their joins to the selected database user list.

New raw Matomo aggregate paths must follow the same pattern. The selected organisation, when present, is already reflected in the database user allowlist.

---

## Matomo API Methods Used

| Method | Used by | Why |
|--------|---------|-----|
| `UserId.getUsers` | `get_logins_by_date_range` | Fastest way to get visit counts per user ID; CSV format handles large result sets reliably |
| `Live.getLastVisitsDetails` | `get_last_login_per_user`, `get_visit_durations`, `get_completed_sessions`, `get_activity_completions_per_user`, `get_activity_usage_by_id`, `get_step_completion_depth`, `get_talking_point_engagement`, `get_media_usage`, `get_engagement_events` | Only method that exposes raw visit and action detail including custom dimensions as `dimensionN` keys |
| `VisitsSummary.get` | *(removed)* | Was used for avg duration but returned 0 for many users; replaced by bulk `Live.getLastVisitsDetails` |

`Live.getLastVisitsDetails` is used for most calls because it returns the full visit object including `actionDetails`, which is where custom dimensions (`dimensionN`) are set per event. The other aggregate endpoints (`Events.getCategory`, `VisitsSummary.get`) do not expose per-action dimension values.

---

## Database Tables Queried

| Table | Columns selected | Purpose |
|-------|-----------------|---------|
| `users` | `id`, `email`, `organisation_id` | User identity and org membership |
| `organisations` | `id`, `name` | Org names |
| `bundles` | `id`, `user_id` | Group counts per org (`SELECT *` is never used — table is too large) |
| `feedback_answers` | `id`, `feedback_question_id`, `user_id`, `answers`, `created_at` | Star rating data |
| `feedback_questions` | `id`, `target` | Whether a rating is from a group (`"groups"`) or therapist (`"therapists"`) |

### Key join relationships

```
users.organisation_id ──► organisations.id
bundles.user_id ──────► users.id ──► organisations.id (no direct org FK on bundles)
feedback_answers.user_id ──► users.id ──► organisations.id
feedback_answers.feedback_question_id ──► feedback_questions.id
```

Star ratings are stored as a jsonb array in `feedback_answers.answers->'answers'`. Each element is an object like `{"answer": 4}`. The SQL queries use `CROSS JOIN LATERAL jsonb_array_elements(...)` to unnest before aggregating.

---

## The dimension10 Filter

### What it is

Matomo custom dimension 10 (`editMode`) is set by the Ayla frontend on every tracked event:
- `"true"` — the therapist is in **Prepare mode** (editing/reviewing a session)
- `"false"` — the therapist is in **Deliver mode** (running a live session with patients)

Only deliver-mode events represent real sessions. Without this filter, all preparation and review activity would be counted as sessions delivered and activities completed, inflating every metric.

### Why it is applied in Python, not as a Matomo segment

The natural approach would be to add `segment=customDimension10==false` to the Matomo API request. This was attempted and returned 0 results.

The root cause: the Matomo Live API (`Live.getLastVisitsDetails`) returns custom dimension values as bare `dimensionN` keys on each action object (e.g. `"dimension10": "false"`), not as `customDimension10`. The segment engine operates on a different internal representation and the `customDimension10` segment name does not match the bare key format used in the Live API response for this Matomo Cloud instance.

The fix is to fetch all visits unfiltered and check `dimension10` in Python using `_extract_dimension(action, "10") == "false"` before including any action in the results.

This filter is applied in every matomo.py function that processes individual actions, using `_extract_dimension(action, "10") == "false"` before including any action in the results. It is **not** applied in visit-level functions (`get_logins_by_date_range`, `get_last_login_per_user`, `get_visit_durations`, `get_visit_dates`) where the unit of measurement is the visit itself.

Affected action-level functions: `get_completed_sessions`, `get_activity_completions_per_user`, `get_activity_usage_by_id`, `get_step_completion_depth`, `get_talking_point_engagement`, `get_media_usage`, `get_engagement_events`.
