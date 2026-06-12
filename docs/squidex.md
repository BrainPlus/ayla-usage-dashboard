# squidex.py — Squidex CMS Client

Fetches the activity name catalogue from Squidex CMS for use in the activity usage table. No database or Matomo calls are made here.

See ADR-0002 for the decision to use Squidex as the activity name source.

---

### get_settings_from_secrets(secrets) → tuple | None

Returns a `(base_url, project, client_id, client_secret)` tuple if all four required keys exist in `st.secrets`, or `None` if any are missing. Used to gracefully skip the Squidex fetch when credentials are not configured.

**Required `st.secrets` keys (flat, not per-region):**
- `squidex_base_url` — e.g. `"https://squidex-production.brain-plus.com/"`
- `squidex_project` — e.g. `"cst-prepare"`; must be the Squidex app that contains the session activity schemas tracked by Matomo
- `squidex_client_id` — OAuth2 client ID (e.g. `"cst-prepare:default"`)
- `squidex_client_secret` — OAuth2 client secret

---

### get_access_token(base_url, client_id, client_secret) → str

POSTs to `{base_url}identity-server/connect/token` with `grant_type=client_credentials` and `scope=squidex-api`. Returns the bearer token string. Raises on HTTP error.

---

### get_activity_catalogue(base_url, project, token) → dict[str, str]

Queries the Squidex GraphQL endpoint (`{base_url}api/content/{project}/graphql`) for all activity content IDs and returns a `{squidex_id: title}` dict. Uses `X-Flatten: true` to unwrap language variant wrappers; `flatData.title` is a plain string in the response.

The catalogue spans all activity schemas that can be tracked in Matomo:

- `Activity`
- `IntroActivity`
- `OutroActivity`
- `WarmupActivity`
- `RoActivity`
- `MainActivity`

Each schema is fetched page by page with `top` and `skip`, because Squidex caps a single GraphQL list response. Schemas that do not exist in the configured project are skipped.

Returns `{}` on any error (network failure, auth error, malformed response) — callers degrade gracefully by showing raw IDs as fallback.

**Notes:**
- One shared Squidex instance covers both UK and EU regions.
- Activity IDs are locale-specific — the same conceptual activity in Danish and English has a different Squidex ID and title. The catalogue maps each locale-specific ID to its title as-is; no cross-locale grouping is performed.
- The catalogue is cached in `app.py` via `@st.cache_data(ttl=3600)`.
- `app.py` surfaces a warning when Matomo activity IDs cannot be resolved by the loaded Squidex catalogue.
