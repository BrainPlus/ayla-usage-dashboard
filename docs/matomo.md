# matomo.py — Matomo API Functions

All functions in this module make HTTP GET requests to the Matomo API using credentials read from `st.secrets` at module load time. No database calls are made here.

---

### _fetch_all_live_visits(base_params, page_size=5000) *(private)*

**Purpose:** Paginates through `Live.getLastVisitsDetails` using `filter_offset`, returning all visits in the date range regardless of total count.

**Parameters:**
- `base_params` *(dict)* — Matomo API parameters (without `filter_limit` or `filter_offset`; those are added per page).
- `page_size` *(int, default 5000)* — visits to request per page.

**Returns:** `list` of visit dicts (all pages concatenated). Raises `RuntimeError` if any page returns a non-list, preventing API errors or partial results from being reported as empty data.

**Notes:** Replaces the previous single-call approach with `filter_limit=10000`, which silently discarded visits beyond that threshold for large deployments. All four `Live.getLastVisitsDetails`-based functions (`get_visit_durations`, `get_sessions_delivered`, `get_activity_completions_per_user`, `get_activity_usage_by_id`) call this helper.

---

### matomo_get(params, expect_csv=False)

**Purpose:** Low-level helper that merges base params (`module`, `idSite`, `token_auth`) with the caller's params and makes a GET request to the Matomo API.

**Parameters:**
- `params` *(dict)* — Matomo API parameters to merge with base params (e.g. `method`, `period`, `date`, `segment`).
- `expect_csv` *(bool, default False)* — when `True`, sets `format=CSV` and returns the raw response text; otherwise defaults to JSON and returns parsed Python objects.

**Returns:** Parsed JSON (list or dict) when `expect_csv=False`; raw CSV string when `expect_csv=True`. Raises `requests.HTTPError` on non-2xx responses.

**Notes:** Timeout is fixed at 60 seconds. All public functions in this module call `matomo_get` rather than `requests` directly.

---

### get_logins_by_date_range(date_range)

**Purpose:** Fetches the number of Matomo visits per user within a date range.

**Parameters:**
- `date_range` *(str)* — date range in `"YYYY-MM-DD,YYYY-MM-DD"` format.

**Returns:** DataFrame with columns:
- `user_id` (str) — Matomo user identifier
- `visits` (int) — number of visits in the date range

**Notes:** Uses `UserId.getUsers` with CSV format and `filter_limit=10000`. Matomo returns `label` for the user ID and `nb_visits` for the count; these are renamed on read. No dimension10 filter — this is a visit-level aggregate and includes all visits regardless of mode.

---

### get_last_login_per_user(user_ids, progress_callback=None)

**Purpose:** Fetches the most recent login date for each user by making one API call per user.

**Parameters:**
- `user_ids` *(list[str])* — list of user ID strings to look up.
- `progress_callback` *(callable, optional)* — called as `callback(current: int, total: int)` after each user is fetched; used to drive a Streamlit progress bar.

**Returns:** DataFrame with columns:
- `user_id` (str)
- `last_login_date` (str, `"YYYY-MM-DD"`) — empty string if no visit found in the last 365 days

**Notes:** Makes one `Live.getLastVisitsDetails` call per user with `countVisitorsToFetch=1` and `doNotFetchActions=1` for minimal payload. Uses a fixed `date=last365` window regardless of the UI date range. For large user bases (100+ users) this is the slowest step in the data pull — a progress bar is shown in the UI. This function is intentionally not cached because caching would bypass the progress callback.

---

### get_avg_visit_duration_by_user(date_range)

**Purpose:** Fetches average visit duration in seconds for each user via a single bulk API call.

**Parameters:**
- `date_range` *(str)* — date range in `"YYYY-MM-DD,YYYY-MM-DD"` format.

**Returns:** DataFrame with columns:
- `user_id` (str)
- `avg_session_seconds` (float) — mean of `visitDuration` across all visits for the user; 0.0 if no visits found

**Notes:** Uses a single `Live.getLastVisitsDetails` call and computes the mean per user in pandas — much faster than the previous approach of one `VisitsSummary.get` call per user. Visits with no `userId` (anonymous/logged-out visits) are skipped. No dimension10 filter — visit duration is visit-level data unrelated to deliver vs. prepare mode.

---

### get_sessions_delivered(date_range)

**Purpose:** Fetches unique delivered session instances as `(bundle_id, session_id, user_id)` rows.

**Parameters:**
- `date_range` *(str)* — date range in `"YYYY-MM-DD,YYYY-MM-DD"` format.

**Returns:** DataFrame with columns:
- `bundle_id` (str) — DB integer bundle ID from dimension14 (`customBundleId`)
- `session_id` (str) — UUID from dimension5
- `user_id` (str)

**Notes:** Uses `Live.getLastVisitsDetails` without a segment filter. The deliver-mode filter is applied in Python: only actions where `dimension10 == "false"` are included (dimension10 is the `editMode` flag; `"false"` means deliver/live mode, `"true"` means prepare/edit mode). The Matomo segment approach (`customDimension10==false`) was found to return 0 results because the Live API returns dimension values as bare `dimensionN` keys, not `customDimensionN`. Within each visit, `(bundle_id, session_id)` pairs are deduplicated to avoid double-counting multiple events from the same session.

---

### get_activity_completions_per_user(date_range)

**Purpose:** Counts "Activity Complete" events per user in delivered sessions only.

**Parameters:**
- `date_range` *(str)* — date range in `"YYYY-MM-DD,YYYY-MM-DD"` format.

**Returns:** DataFrame with columns:
- `user_id` (str)
- `activities_completed` (int)

**Notes:** Uses `Live.getLastVisitsDetails` without a segment filter. Three conditions must all be true for an action to be counted: `dimension10 == "false"` (deliver mode), `eventCategory == "Activity"`, and `eventAction == "Activity Complete"`. The dimension10 check is evaluated first to short-circuit quickly.

---

### _extract_dimension(obj, dim_number) *(private)*

**Purpose:** Extracts a custom dimension value from a Matomo visit or action dict, handling all response shapes the API may return.

**Parameters:**
- `obj` *(dict)* — a visit or action dict from the Matomo Live API response.
- `dim_number` *(str)* — dimension number as a string (e.g. `"10"`, `"14"`).

**Returns:** The dimension value as a string, or `""` if not found.

**Notes:** Handles four shapes in priority order:
1. Bare key `dimensionN` — used in `actionDetails` in the Live API (confirmed shape for this instance)
2. Flat key `customDimensionN` — used at visit level in some Matomo versions
3. Nested dict `customDimensions: {"N": {"value": "..."}}`
4. Array `customDimensions: [{"index": N, "value": "..."}]`
