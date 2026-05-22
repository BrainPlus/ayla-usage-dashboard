# Ayla Usage Dashboard

A Streamlit dashboard for the Ayla CST Assistant product team. Pulls analytics from Matomo and user/organisation data from PostgreSQL, combines them, and displays usage metrics in a browser UI with Excel export.

Covers both the **UK** (GCP) and **EU** (Open Telekom Cloud) deployments of Ayla via a region selector in the sidebar.

Live app: https://ayla-usage-dashboard.streamlit.app

---

## Features

### Global Overview
- Total organisations, users, and groups created
- Sessions delivered (30-day and 90-day windows)
- Overall average star ratings (group and therapist)
- Logins by organisation bar chart
- Monthly average star rating trend (group vs therapist)

### By Organisation
- Total users and active users (2+ logins in 30 days)
- Logins (30-day and 90-day)
- Average session duration
- Sessions delivered (30-day and 90-day)
- Average group and therapist star ratings
- Last login date

### By User
- Email and organisation
- Last login date
- Logins (30-day and 90-day)
- Average session duration
- Activities completed (delivered sessions only)
- Filter by organisation name

### Excel Export
Download a `.xlsx` report with Organisation Summary, User Detail, Monthly Ratings, and a Methodology sheet explaining each field.

---

## Project Structure

| File | Purpose |
|------|---------|
| `app.py` | Streamlit UI — sidebar, tabs, data fetching orchestration, download button |
| `matomo.py` | All Matomo API calls (logins, sessions delivered, activity completions, visit duration, last login) |
| `database.py` | All PostgreSQL queries (users, organisations, bundles, star ratings) |
| `merger.py` | Pandas joins and aggregations — combines Matomo and DB data into display-ready DataFrames |
| `exporter.py` | Excel export — builds an in-memory `.xlsx` with auto-sized columns |

---

## Local Development

### Prerequisites
- Python 3.12+
- pip

### Setup

```bash
# Clone the repo
git clone https://github.com/BrainPlus/ayla-usage-dashboard.git
cd ayla-usage-dashboard

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure secrets (see Secrets Configuration below)
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit .streamlit/secrets.toml with real credentials
```

### Run

```bash
streamlit run app.py
```

---

## Secrets Configuration

Create `.streamlit/secrets.toml` with the following structure:

```toml
# Matomo — shared, one instance for both regions
matomo_url = "https://your-matomo-instance/index.php"
matomo_token = "your_token_here"
matomo_site_id = "4"

# Database — UK (GCP)
[uk]
db_host = "your-uk-host"
db_port = "5432"
db_name = "postgres"
db_user = "your_user"
db_password = "your_password"

# Database — EU (Open Telekom Cloud)
[eu]
db_host = "your-eu-host"
db_port = "5021"
db_name = "postgres"
db_user = "your_user"
db_password = "your_password"
```

Matomo credentials are top-level (shared across regions). Database credentials are scoped under `[uk]` and `[eu]` sections. The app reads the correct DB section based on the region selected in the sidebar.

The `.streamlit/secrets.toml` file is gitignored and should never be committed.

---

## Deployment

The dashboard is hosted on **Streamlit Community Cloud** at:
https://ayla-usage-dashboard.streamlit.app

Secrets are managed in the app settings under **Settings → Secrets** in the Streamlit Cloud dashboard — paste the full `secrets.toml` content there.

To deploy updates, push to the `main` branch. Streamlit Cloud redeploys automatically.

---

## Important Notes

**Deliver mode filter** — All session, activity, and step event queries filter on `dimension10 == "false"` at the action level. This excludes Prepare (edit) mode and ensures only real delivered sessions are counted. This filter is applied in Python after fetching raw visit data from the Live API, not as a Matomo segment, because the segment approach was found to return 0 results.

**Bundles table** — Never query `SELECT * FROM bundles`. The table is large and the query is slow. Always use targeted queries selecting only the columns needed (`b.id`, `b.user_id`). The join path to organisations is `bundles.user_id → users.id → users.organisation_id → organisations.id`.

**Last login pull** — Fetching last login dates makes one API call per user to `Live.getLastVisitsDetails`. For large user bases this takes a few minutes. A progress bar is shown in the UI during this step.

**UK database network access** — The UK database on GCP requires `0.0.0.0/0` to be in the authorised networks list because Streamlit Community Cloud uses dynamic IP addresses. This is expected and intentional for this deployment.

---

## Access

**Dashboard access** is managed via the sharing settings in Streamlit Community Cloud. Contact the team admin to be added.

**Database access** uses a dedicated read-only user (`ayla_data_user` on UK, equivalent on EU). Credentials are stored in Streamlit Cloud secrets and in the team password manager.
