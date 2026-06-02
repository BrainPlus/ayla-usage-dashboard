# merger.py — DataFrame Merge and Aggregation Functions

This module combines DataFrames from `database.py` and `matomo.py` into the final display-ready DataFrames used by the UI. It makes no database or Matomo API calls — all inputs are DataFrames.

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
- `avg_real_session_minutes` (float, 1 decimal) — mean duration for deliver visits over 20 minutes
- `avg_prepare_minutes` (float, 1 decimal) — mean duration for prepare-only visits
- `short_visit_count` (int) — count of deliver visits lasting 20 minutes or less
- `activities_completed` (int) — 0 if not in Matomo

**Notes:** All joins are left joins on `db_users`, ensuring every DB user has a row even if absent from Matomo. Visit duration rows are classified before joining: deliver visits over 20 minutes become real sessions, deliver visits at or below 20 minutes become short visits, and visits without deliver actions become prepare-only visits. Rows are sorted by `organisation_name` then `email`.

---

### build_org_summary(user_detail, sessions_delivered_30, sessions_delivered_90, star_ratings, org_user_counts)

**Purpose:** Builds the per-organisation summary table by aggregating user_detail and joining session, rating, and user-count data.

**Parameters:**
- `user_detail` *(DataFrame)* — output of `build_user_detail`
- `sessions_delivered_30` *(DataFrame)* — `bundle_id`, `session_id`, `user_id` from `matomo.get_sessions_delivered` for the 30-day window
- `sessions_delivered_90` *(DataFrame)* — same structure for the 90-day window
- `star_ratings` *(DataFrame)* — `organisation_name`, `target`, `avg_rating`, `total_responses` from `database.get_star_ratings_by_org`
- `org_user_counts` *(DataFrame)* — `organisation_name`, `user_count` from `database.get_org_user_counts`

**Returns:** DataFrame with columns:
- `organisation_name` (str)
- `total_users` (int) — from DB, not Matomo
- `active_users_30` (int) — users with 2+ logins in the 30-day window
- `logins_30_days` (int)
- `logins_90_days` (int)
- `avg_real_session_minutes` (float, 1 decimal) — mean of user-level real-session averages
- `avg_prepare_minutes` (float, 1 decimal) — mean of user-level prepare-only averages
- `short_visit_count` (int) — sum across users in the org
- `sessions_delivered_30_days` (int)
- `sessions_delivered_90_days` (int)
- `last_login_date` (str) — most recent login across all users in the org; `"No tracked usage"` if none
- `groups_avg_rating` (float, 2 decimal) — 0.0 if no data
- `therapists_avg_rating` (float, 2 decimal) — 0.0 if no data

**Notes:**
- **Last login aggregation:** rows with `"No tracked usage"` are excluded before taking `max()` so a real date always takes precedence. Orgs with no real logins get the sentinel back via `fillna`.
- **Sessions delivered:** the `sessions_delivered_*` DataFrames are joined to `user_detail` to resolve `organisation_name`, then deduplicated on `(organisation_name, bundle_id, session_id)` — so a session delivered by two different users within the same org is counted once, not twice.
- **Star ratings:** pivoted from long format (`target` as column values) to wide format (`groups_avg_rating` and `therapists_avg_rating` as columns). Both columns are guaranteed to exist even if one target type has no data.
- **Sort order:** alphabetical by `organisation_name`; `"Unassigned / No organisation"` is always last.

---

### build_global_summary(org_summary, bundle_counts)

**Purpose:** Computes top-level scalar totals for the Global Overview tab.

**Parameters:**
- `org_summary` *(DataFrame)* — output of `build_org_summary`
- `bundle_counts` *(DataFrame)* — `organisation_name`, `total_groups` from `database.get_bundle_counts_per_org`

**Returns:** `dict` with keys:
- `total_organisations` (int) — excludes `"Unassigned / No organisation"`
- `total_users` (int) — sum across all orgs including unassigned
- `total_groups_created` (int) — sum from `bundle_counts`
- `total_sessions_delivered_30` (int)
- `total_sessions_delivered_90` (int)
- `overall_groups_avg_rating` (float, 2 decimal) — mean across orgs that have a non-zero rating
- `overall_therapists_avg_rating` (float, 2 decimal) — same

**Notes:** `"Unassigned / No organisation"` is excluded from `total_organisations` (not a real org) but included in all other totals. Rating averages exclude orgs with a 0.0 rating to avoid depressing the mean with no-data entries — only orgs that have received at least one rating contribute.
