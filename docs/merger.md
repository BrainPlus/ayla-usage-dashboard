# merger.py — DataFrame Merge and Aggregation Functions

This module combines DataFrames from `database.py`, `matomo.py`, and `squidex.py` into the final display-ready DataFrames used by the UI. It makes no database, Matomo, or Squidex API calls — all inputs are DataFrames or dicts.

Two sentinel constants are used throughout:
- `_NO_USAGE = "No tracked usage"` — placeholder for users/orgs with no Matomo activity
- `_NO_ORG = "Unassigned / No organisation"` — label for users without an organisation

---

### build_user_detail(db_users, logins_30, logins_90, last_login, visit_durations, activity_completions)

**Purpose:** Builds the per-user detail table by left-joining all Matomo metrics onto the canonical DB user list.

**Parameters:**
- `db_users` *(DataFrame)* — `user_id`, `email`, `organisation_name` from `database.load_users_and_orgs`
- `logins_30` *(DataFrame)* — `user_id`, `visits` from `matomo.get_logins_by_date_range` for the 30-day window
- `logins_90` *(DataFrame)* — `user_id`, `visits` from `matomo.get_logins_by_date_range` for the 90-day window
- `last_login` *(DataFrame)* — `user_id`, `last_login_date` from `matomo.get_last_login_per_user`
- `visit_durations` *(DataFrame)* — `user_id`, `visit_duration_seconds`, `has_deliver_action` from `matomo.get_visit_durations`
- `activity_completions` *(DataFrame)* — `user_id`, `activities_completed` from `matomo.get_activity_completions_per_user`

**Returns:** DataFrame with columns:
- `user_id` (str)
- `email` (str)
- `organisation_name` (str)
- `last_login_date` (str) — `"No tracked usage"` if never seen in Matomo
- `logins_30_days` (int) — 0 if not in Matomo
- `logins_90_days` (int) — 0 if not in Matomo
- `avg_real_session_minutes` (float, 1 decimal) — mean duration of deliver visits >20 min
- `median_prepare_minutes` (float, 1 decimal) — median duration of prepare-only visits
- `short_visit_count` (int) — deliver visits ≤20 min
- `activities_completed` (int) — 0 if not in Matomo

**Notes:** Duration metrics are computed by `_build_visit_duration_metrics`. All joins are left joins on `db_users`, ensuring every DB user has a row even if absent from Matomo. Rows are sorted by `organisation_name` then `email`.

---

### build_org_summary(user_detail, sessions_delivered_30, sessions_delivered_90, star_ratings, org_user_counts, visit_durations)

**Purpose:** Builds the per-organisation summary table by aggregating user_detail and joining session, rating, user-count, and raw visit data.

**Parameters:**
- `user_detail` *(DataFrame)* — output of `build_user_detail`
- `sessions_delivered_30` *(DataFrame)* — `bundle_id`, `session_id`, `user_id` from `matomo.get_sessions_delivered` for the 30-day window
- `sessions_delivered_90` *(DataFrame)* — same structure for the 90-day window
- `star_ratings` *(DataFrame)* — `organisation_name`, `target`, `avg_rating`, `total_responses` from `database.get_star_ratings_by_org`
- `org_user_counts` *(DataFrame)* — `organisation_name`, `user_count` from `database.get_org_user_counts`
- `visit_durations` *(DataFrame)* — `user_id`, `visit_duration_seconds`, `has_deliver_action` from `matomo.get_visit_durations` (raw, not pre-aggregated)

**Returns:** DataFrame with columns:
- `organisation_name` (str)
- `total_users` (int) — from DB, not Matomo
- `active_users_30` (int) — users with 2+ logins in the 30-day window
- `logins_30_days` (int)
- `logins_90_days` (int)
- `avg_real_session_minutes` (float, 1 decimal) — when raw `visit_durations` are provided: visit-count-weighted mean across all deliver visits >20 min in the org; falls back to mean of per-user averages when `visit_durations` is absent
- `median_prepare_minutes` (float, 1 decimal) — median of per-user medians, excluding users with 0
- `min_real_session_minutes` (float, 1 decimal) — shortest individual real session (raw visit >20 min) across all users in the org; 0.0 when `visit_durations` is absent
- `max_real_session_minutes` (float, 1 decimal) — longest individual real session across all users in the org; 0.0 when `visit_durations` is absent
- `short_visit_count` (int) — deliver visits ≤20 min across all users in the org
- `sessions_delivered_30_days` (int)
- `sessions_delivered_90_days` (int)
- `avg_activities_per_session` (float, 1 decimal) — org total `activities_completed` ÷ `sessions_delivered_30_days`; 0.0 if no sessions
- `last_login_date` (str) — most recent login across all users; `"No tracked usage"` if none
- `groups_avg_rating` (float, 2 decimal) — 0.0 if no data
- `therapists_avg_rating` (float, 2 decimal) — 0.0 if no data

**Notes:**
- **Avg/min/max session time:** all three are computed from raw `visit_durations` when available, so `avg` is visit-count-weighted rather than a mean of per-user averages. Joined to org via `user_detail[user_id → organisation_name]`. See ADR-0004.
- **Median prepare time:** median is used (not mean) because prepare visits are skewed by occasional long sessions. See ADR-0003.
- **Sessions delivered:** deduplicated on `(organisation_name, bundle_id, session_id)` — a session delivered by two users in the same org counts once.
- **Star ratings:** pivoted from long to wide; both columns guaranteed to exist even if one target has no data.
- **Sort order:** alphabetical; `"Unassigned / No organisation"` always last.

---

### build_activity_usage_table(activity_usage, activity_catalogue)

**Purpose:** Joins raw activity usage counts with human-readable titles from the Squidex catalogue.

**Parameters:**
- `activity_usage` *(DataFrame)* — `activity_id` (str), `completion_count` (int) from `matomo.get_activity_usage_by_id`
- `activity_catalogue` *(dict)* — `{squidex_id: title}` from `squidex.get_activity_catalogue`; may be empty if Squidex is unavailable

**Returns:** DataFrame with columns:
- `Activity Name` (str) — human-readable title; falls back to raw `activity_id` if not in catalogue
- `Completions` (int)

Sorted descending by `Completions` (most used first).

**Notes:** Unknown IDs (not in catalogue) use the raw ID string as fallback — the table always renders even if the Squidex fetch failed. Activity IDs are locale-specific Squidex content IDs; the same conceptual activity in different languages carries a different ID and title. See ADR-0002.

---

### activity_catalogue_match_stats(activity_usage, activity_catalogue)

**Purpose:** Computes diagnostic counts for how well the Matomo activity IDs match the loaded Squidex catalogue.

**Parameters:**
- `activity_usage` *(DataFrame)* — `activity_id` (str), `completion_count` (int) from `matomo.get_activity_usage_by_id`
- `activity_catalogue` *(dict)* — `{squidex_id: title}` from `squidex.get_activity_catalogue`

**Returns:** `dict` with keys:
- `usage_ids` (int) — unique Matomo activity IDs in the usage data
- `catalogue_ids` (int) — unique Squidex IDs loaded into the catalogue
- `matched_ids` (int) — IDs present in both sources
- `unmatched_ids` (int) — Matomo IDs not found in the catalogue

**Notes:** `app.py` uses these counts to show a warning when activity titles cannot be resolved, distinguishing an empty catalogue from a project/schema mismatch or partial catalogue.

---

### build_global_summary(org_summary, bundle_counts, star_ratings=None)

**Purpose:** Computes top-level scalar totals for the Global Overview tab.

**Parameters:**
- `org_summary` *(DataFrame)* — output of `build_org_summary`
- `bundle_counts` *(DataFrame)* — `organisation_name`, `total_groups` from `database.get_bundle_counts_per_org`
- `star_ratings` *(DataFrame, optional)* — `organisation_name`, `target`, `avg_rating`, `total_responses` from `database.get_star_ratings_by_org`

**Returns:** `dict` with keys:
- `total_organisations` (int) — excludes `"Unassigned / No organisation"`
- `total_users` (int) — sum across all orgs including unassigned
- `total_groups_created` (int) — sum from `bundle_counts`
- `total_sessions_delivered_30` (int)
- `total_sessions_delivered_90` (int)
- `overall_groups_avg_rating` (float, 2 decimal) — response-weighted mean across all organisations
- `overall_therapists_avg_rating` (float, 2 decimal) — same

**Notes:** When `star_ratings` is provided, rating averages are weighted by `total_responses`, so every submitted rating contributes equally regardless of organisation size. When omitted, the function preserves compatibility by falling back to an unweighted mean of the non-zero organisation-level ratings in `org_summary`.

---

### build_monthly_rating_summary(monthly_ratings)

**Purpose:** Computes response-weighted monthly ratings across all organisations.

**Parameters:**
- `monthly_ratings` *(DataFrame)* — `month`, `organisation_name`, `target`, `avg_rating`, `total_responses` from `database.get_monthly_star_ratings`

**Returns:** DataFrame with columns:
- `month` (str)
- `target` (str)
- `avg_rating` (float, 2 decimal)
