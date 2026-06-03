import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# Stub streamlit before importing app modules
streamlit_stub = ModuleType("streamlit")
streamlit_stub.secrets = {
    "squidex_base_url": "https://cloud.squidex.io/",
    "squidex_project": "ayla-app",
    "squidex_client_id": "test-client",
    "squidex_client_secret": "test-secret",
}
streamlit_stub.cache_data = lambda **kwargs: (lambda f: f)
sys.modules.setdefault("streamlit", streamlit_stub)

import squidex


def _mock_post_response(json_data: dict, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    if status_code >= 400:
        response.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    else:
        response.raise_for_status.return_value = None
    return response


def test_get_access_token_returns_token() -> None:
    mock_response = _mock_post_response({"access_token": "abc123", "token_type": "Bearer"})

    with patch("squidex.requests.post", return_value=mock_response) as mock_post:
        token = squidex.get_access_token(
            "https://cloud.squidex.io/", "my-client", "my-secret"
        )

    assert token == "abc123"
    mock_post.assert_called_once_with(
        "https://cloud.squidex.io/identity-server/connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "my-client",
            "client_secret": "my-secret",
            "scope": "squidex-api",
        },
    )


def test_get_access_token_raises_on_http_error() -> None:
    mock_response = _mock_post_response({}, status_code=401)

    with patch("squidex.requests.post", return_value=mock_response):
        with pytest.raises(Exception):
            squidex.get_access_token(
                "https://cloud.squidex.io/", "bad-client", "bad-secret"
            )


def test_get_activity_catalogue_returns_dict() -> None:
    graphql_response = {
        "data": {
            "queryActivityContents": [
                {"id": "id-1", "flatData": {"title": "Reality Orientation"}},
                {"id": "id-2", "flatData": {"title": "Warm Up"}},
            ]
        }
    }
    mock_response = _mock_post_response(graphql_response)

    with patch("squidex.requests.post", return_value=mock_response):
        result = squidex.get_activity_catalogue(
            "https://cloud.squidex.io/", "ayla-app", "token-xyz"
        )

    assert result == {"id-1": "Reality Orientation", "id-2": "Warm Up"}


def test_get_activity_catalogue_returns_empty_on_request_failure() -> None:
    with patch("squidex.requests.post", side_effect=Exception("connection error")):
        result = squidex.get_activity_catalogue(
            "https://cloud.squidex.io/", "ayla-app", "token-xyz"
        )

    assert result == {}


def test_get_activity_catalogue_handles_partial_catalogue() -> None:
    # One item is missing the title key in flatData
    graphql_response = {
        "data": {
            "queryActivityContents": [
                {"id": "id-1", "flatData": {"title": "Reality Orientation"}},
                {"id": "id-2", "flatData": {}},  # missing title
            ]
        }
    }
    mock_response = _mock_post_response(graphql_response)

    with patch("squidex.requests.post", return_value=mock_response):
        result = squidex.get_activity_catalogue(
            "https://cloud.squidex.io/", "ayla-app", "token-xyz"
        )

    # KeyError on missing title is caught, returns {}
    assert result == {}
