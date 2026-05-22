# All Matomo API calls: visits, session events, activity completions, custom dimension queries.
# Reads st.secrets["matomo_url"], st.secrets["matomo_token"], st.secrets["matomo_site_id"] (top-level, shared across regions).
# ALWAYS include segment=customDimension10==false for session/activity/step event queries.
