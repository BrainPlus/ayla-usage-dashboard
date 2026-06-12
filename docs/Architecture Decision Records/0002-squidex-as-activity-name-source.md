# Squidex as the activity name source for most/least used activity reporting

Activity IDs tracked in Matomo (`dimension6`) are Squidex CMS content IDs — opaque strings that are not human-readable in isolation. To display activity names alongside usage counts, the dashboard fetches a full id→title catalogue from Squidex at data-pull time using the GraphQL API with client-credentials auth.

Squidex is a single shared instance covering both UK and EU regions. Activities are locale-specific: the same conceptual activity in Danish and English carries different Squidex IDs and titles. The catalogue fetch returns all activities across all locales; names are shown as-is (in whatever locale that activity belongs to). No cross-locale grouping is attempted.

The tracked IDs are not limited to the generic `Activity` schema. They can come from slot-specific activity schemas in the session content model: `IntroActivity`, `RoActivity`, `WarmupActivity`, `MainActivity`, and `OutroActivity`. The dashboard therefore queries each of those schemas plus `Activity`, paging through each list with `top` and `skip` so large schemas such as `MainActivity` are not truncated by Squidex's per-request list cap.

## Considered options

- **Raw activityId strings only**: no new data source required, but the output is unreadable to anyone without CMS access. Rejected — the feature would have no practical value.
- **PostgreSQL lookup**: activity metadata is not stored in the Ayla PostgreSQL database; it lives in Squidex. Not feasible.
- **Backend proxy (same flow as the Flutter app)**: the app fetches Squidex tokens via an authenticated backend endpoint. The dashboard has no backend session to authenticate against. Rejected — wrong auth model for a server-to-server tool.
- **Client credentials (chosen)**: Squidex supports OAuth2 client credentials for server-to-server access. Credentials are stored in `st.secrets`. Paginated GraphQL calls fetch the complete activity catalogue across all activity schemas; results are cached for the session.
