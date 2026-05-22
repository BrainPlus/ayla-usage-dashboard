# Ayla Usage Dashboard

Streamlit web app for the Ayla CST Assistant product team. Pulls analytics from Matomo and user/organisation data from PostgreSQL, combines them, and displays in a browser UI with Excel export.

## Product Context
- Ayla is a Cognitive Stimulation Therapy (CST) web app for therapists
- Therapists create groups (called "bundles" internally), each with 14 fixed sessions
- Each session has activities (reality orientation, warm up, introduction, main activity)
- Sessions have two modes: Prepare (edit mode) and Deliver (live session with patients)
- At end of each delivered session: star rating feedback from the group AND from the therapist

## Two Environments (identical schema)
- UK: hosted on GCP
- EU: hosted on Open Telekom Cloud
- The app has a region selector (UK / EU) in the sidebar
- Secrets are stored in st.secrets with [uk] and [eu] sections

## Stack
- Python, Streamlit, pandas, psycopg2, requests, openpyxl, gspread
- Secrets via st.secrets (local: .streamlit/secrets.toml)

## Matomo
- URL: from st.secrets
- Site ID: 4 (production)
- Auth token: from st.secrets
- Custom dimensions in use:
  - dimension1: appVersion
  - dimension2: language
  - dimension3: offline
  - dimension4: bundleId
  - dimension5: sessionId
  - dimension6: activityId
  - dimension7: stepId
  - dimension10: editMode (true = prepare/edit, false = deliver)
  - dimension11: currentRoute
  - dimension13: organisationId

## CRITICAL Data Quality Rule
ALL Matomo queries for session/activity/step events MUST include this segment filter:
  customDimension10==false
This ensures we only count real delivered sessions, not therapists editing/preparing.
This filter does NOT apply to login/visit-level queries.

## Database Schema (relevant tables)
- users: id, email, organisation_id
- organisations: id, name
- bundles: id, user_id (do NOT use SELECT * FROM bundles - too slow, always use targeted queries)
  - bundles link to orgs via: bundles.user_id → users.id → users.organisation_id → organisations.id
- feedback_questions: id, target (groups or therapists), questions (jsonb, 1-5 stars)
- feedback_answers: id, feedback_question_id, user_id, answers (jsonb with bundleId + sessionId in metadata)

## App Structure
Three tabs:
1. Global Overview - totals across all orgs, sessions delivered, monthly star rating trend
2. By Organisation - logins, active users, avg session time, sessions delivered, star ratings
3. By User - logins, last login, avg session time, % activities completed

## File Structure
- app.py: Streamlit UI, tabs, sidebar
- matomo.py: all Matomo API calls
- database.py: all PostgreSQL queries
- merger.py: pandas joins and aggregations
- exporter.py: Excel export logic
- requirements.txt: all dependencies
