# database.py — PostgreSQL Query Functions

All query functions accept a `region` parameter (`"uk"` or `"eu"`) and return a pandas DataFrame. Data queries also accept optional organisation scoping; star-rating queries additionally receive the selected reporting period.

**Never use `SELECT * FROM bundles`** — the table is large and the query is slow. Always select only the columns needed.

---

### get_engine(region)

**Purpose:** Builds and returns a SQLAlchemy engine for the given region using credentials from `st.secrets`.

**Parameters:**
- `region` *(str)* — `"uk"` or `"eu"`.

**Returns:** `sqlalchemy.engine.Engine` using the `postgresql+psycopg2` dialect. The engine is lightweight and does not open a connection until `.connect()` is called.

**Notes:** Connection URL is constructed as `postgresql+psycopg2://user:password@host:port/dbname`. All five credential keys (`db_host`, `db_port`, `db_name`, `db_user`, `db_password`) are read from `st.secrets[region]`.

---

### load_users_and_orgs(region)

**Purpose:** Loads all users with their organisation name via a LEFT JOIN, providing the canonical user list used as the base for all merges.

**Parameters:**
- `region` *(str)* — `"uk"` or `"eu"`.

**Returns:** DataFrame with columns:
- `user_id` (str) — cast from the integer DB ID
- `email` (str) — empty string if null
- `organisation_name` (str) — `"Unassigned / No organisation"` if the user has no org

**Notes:** This is the authoritative user list. All Matomo DataFrames are left-joined onto this, so users who never appear in Matomo still get a row (with zeros/sentinel values). Sorted by `user_id` ascending.

---

### get_org_user_counts(region)

**Purpose:** Counts the number of users registered under each organisation.

**Parameters:**
- `region` *(str)* — `"uk"` or `"eu"`.

**Returns:** DataFrame with columns:
- `organisation_name` (str) — `"Unassigned / No organisation"` for users with no org
- `user_count` (int)

**Notes:** Uses `COALESCE` in SQL to handle null `organisation_id` values, so users without an org are counted rather than dropped.

---

### get_bundle_counts_per_org(region)

**Purpose:** Counts the number of groups (bundles) created per organisation.

**Parameters:**
- `region` *(str)* — `"uk"` or `"eu"`.

**Returns:** DataFrame with columns:
- `organisation_name` (str) — `"Unassigned / No organisation"` for bundles whose creator has no org
- `total_groups` (int)

**Notes:** The `bundles` table has no direct `organisation_id` column. The join path is `bundles.user_id → users.id → users.organisation_id → organisations.id`. Only `b.id` and `b.user_id` are selected from `bundles` — never `SELECT *`.

---

### get_star_ratings_by_org(region, start_date, end_date, org_id=None)

**Purpose:** Calculates average star rating and total response count per organisation and feedback target type.

**Parameters:**
- `region` *(str)* — `"uk"` or `"eu"`.
- `start_date`, `end_date` *(date)* — inclusive reporting-period bounds
- `org_id` *(int, `"unassigned"`, or None)* — optional organisation scope

**Returns:** DataFrame with columns:
- `organisation_name` (str)
- `target` (str) — `"groups"` (patient group rating) or `"therapists"` (therapist self-rating)
- `avg_rating` (float) — average of 1–5 star answers
- `total_responses` (int)

**Notes:** Star ratings are stored as a jsonb array in `feedback_answers.answers->'answers'`. Each element has an `'answer'` key with a numeric value. The query uses `CROSS JOIN LATERAL jsonb_array_elements(...)` to unnest the array before aggregating. Results are sorted by `organisation_name`.

---

### get_monthly_star_ratings(region, start_date, end_date, org_id=None)

**Purpose:** Calculates average star ratings broken down by calendar month, organisation, and feedback target.

**Parameters:**
- `region` *(str)* — `"uk"` or `"eu"`.
- `start_date`, `end_date` *(date)* — inclusive reporting-period bounds
- `org_id` *(int, `"unassigned"`, or None)* — optional organisation scope

**Returns:** DataFrame with columns:
- `month` (str, `"YYYY-MM"`)
- `organisation_name` (str)
- `target` (str) — `"groups"` or `"therapists"`
- `avg_rating` (float)
- `total_responses` (int)

**Notes:** Uses the same join and unnesting logic as `get_star_ratings_by_org`, with an additional `TO_CHAR(fa.created_at, 'YYYY-MM')` grouping. `feedback_answers.created_at` is a confirmed `timestamptz` column. Used to power the monthly trend line chart in the Global Overview tab.
