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

1. **DB queries** (fast, ~1–2s) — `database.py` runs five SQL queries against the selected region's PostgreSQL database: users+orgs, user counts per org, bundle counts per org, star ratings by org, monthly star ratings.

2. **Matomo bulk queries** (medium, ~5–15s, cached 1h) — `matomo.py` makes four `Live.getLastVisitsDetails` calls: logins for 30-day window, logins for 90-day window, sessions delivered for both windows, and activity completions. One additional `UserId.getUsers` call fetches the login list.

3. **Last login per user** (slow, ~1–5 min) — one `Live.getLastVisitsDetails` call per user, sequentially. This is the bottleneck. A progress bar is shown. Not cached because caching would skip the progress callback.

4. **Avg session duration** (fast, 1 API call, cached 1h) — a single `Live.getLastVisitsDetails` call; duration is extracted and averaged per user in pandas.

5. **Merge** — `merger.py` left-joins all Matomo DataFrames onto the DB user list and aggregates up to org and global level.

---

## Matomo API Methods Used

| Method | Used by | Why |
|--------|---------|-----|
| `UserId.getUsers` | `get_logins_by_date_range` | Fastest way to get visit counts per user ID; CSV format handles large result sets reliably |
| `Live.getLastVisitsDetails` | `get_last_login_per_user`, `get_avg_visit_duration_by_user`, `get_sessions_delivered`, `get_activity_completions_per_user` | Only method that exposes raw visit and action detail including custom dimensions as `dimensionN` keys |
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

This filter is applied in:
- `matomo.get_sessions_delivered` — per action, before recording a `(bundle_id, session_id)` pair
- `matomo.get_activity_completions_per_user` — per action, before counting an "Activity Complete" event

It is **not** applied in:
- `get_logins_by_date_range` — login counts are visit-level, not action-level
- `get_last_login_per_user` — last login date is visit-level
- `get_avg_visit_duration_by_user` — visit duration is visit-level; both modes count as time spent in the app
