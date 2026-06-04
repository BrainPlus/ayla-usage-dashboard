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

ACTIVITY_SCHEMA_NAMES = (
    "Activity",
    "IntroActivity",
    "OutroActivity",
    "WarmupActivity",
    "RoActivity",
    "MainActivity",
)
GRAPHQL_PAGE_SIZE = 200


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
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def get_activity_catalogue(base_url: str, project: str, token: str) -> dict[str, str]:
    """Query Squidex GraphQL for all activity IDs and titles.

    Returns {id: title} dict. Returns {} on any request error.
    Schemas that do not exist in a Squidex project are skipped.
    """
    url = f"{base_url}api/content/{project}/graphql"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Flatten": "true",
    }
    catalogue: dict[str, str] = {}
    try:
        for schema_name in ACTIVITY_SCHEMA_NAMES:
            query_field = f"query{schema_name}Contents"
            skip = 0
            while True:
                query = f"""
                {{
                    {query_field}(top: {GRAPHQL_PAGE_SIZE}, skip: {skip}) {{
                        id
                        flatData {{ title }}
                    }}
                }}
                """
                response = requests.post(url, json={"query": query}, headers=headers, timeout=60)
                response.raise_for_status()
                payload = response.json()
                if payload.get("errors"):
                    break
                items = payload.get("data", {}).get(query_field, [])
                for item in items:
                    title = (item.get("flatData") or {}).get("title")
                    if item.get("id") and title:
                        catalogue[str(item["id"])] = str(title)
                if len(items) < GRAPHQL_PAGE_SIZE:
                    break
                skip += GRAPHQL_PAGE_SIZE
        return catalogue
    except Exception:
        return {}
