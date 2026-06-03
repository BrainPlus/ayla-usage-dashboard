# Squidex CMS client — OAuth2 client credentials + GraphQL activity catalogue.
#
# Optional st.secrets keys (flat, not per-region):
#   squidex_base_url      — e.g. "https://cloud.squidex.io/"
#   squidex_project       — e.g. "ayla-app"
#   squidex_client_id     — OAuth2 client ID
#   squidex_client_secret — OAuth2 client secret

import requests


SECRET_KEYS = (
    "squidex_base_url",
    "squidex_project",
    "squidex_client_id",
    "squidex_client_secret",
)


def get_settings_from_secrets(secrets) -> tuple[str, str, str, str] | None:
    """Return Squidex settings when all optional secrets are configured."""
    values = []
    for key in SECRET_KEYS:
        value = secrets.get(key)
        if not value:
            return None
        values.append(value)
    return tuple(values)


def get_access_token(base_url: str, client_id: str, client_secret: str) -> str:
    """POST to {base_url}identity-server/connect/token with client credentials grant.

    Returns the bearer token string. Raises on HTTP error.
    """
    url = f"{base_url}identity-server/connect/token"
    response = requests.post(
        url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "squidex-api",
        },
    )
    response.raise_for_status()
    return response.json()["access_token"]


def get_activity_catalogue(base_url: str, project: str, token: str) -> dict[str, str]:
    """Query Squidex GraphQL for all activity IDs and titles.

    Returns {id: title} dict. Returns {} on any error (graceful degradation).
    """
    url = f"{base_url}api/content/{project}/graphql"
    query = "{ queryActivityContents { id flatData { title } } }"
    try:
        response = requests.post(
            url,
            json={"query": query},
            headers={
                "Authorization": f"Bearer {token}",
                "X-Flatten": "true",
            },
        )
        response.raise_for_status()
        items = response.json()["data"]["queryActivityContents"]
        return {item["id"]: item["flatData"]["title"] for item in items}
    except Exception:
        return {}
