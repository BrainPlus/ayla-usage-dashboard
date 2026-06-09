from contextlib import contextmanager

import pandas as pd
import pytest

import database


class _Engine:
    @contextmanager
    def connect(self):
        yield object()


@pytest.mark.parametrize(
    ("function_name", "org_id", "expected_filter", "expected_params"),
    [
        (function_name, 196, "u.organisation_id = :org_id", {"org_id": 196})
        for function_name in (
            "load_users_and_orgs",
            "get_org_user_counts",
            "get_bundle_counts_per_org",
            "get_star_ratings_by_org",
            "get_monthly_star_ratings",
        )
    ]
    + [
        (function_name, "unassigned", "u.organisation_id IS NULL", None)
        for function_name in (
            "load_users_and_orgs",
            "get_org_user_counts",
            "get_bundle_counts_per_org",
            "get_star_ratings_by_org",
            "get_monthly_star_ratings",
        )
    ]
    + [
        (function_name, None, None, None)
        for function_name in (
            "load_users_and_orgs",
            "get_org_user_counts",
            "get_bundle_counts_per_org",
            "get_star_ratings_by_org",
            "get_monthly_star_ratings",
        )
    ],
)
def test_database_queries_apply_organisation_filter(
    monkeypatch,
    function_name,
    org_id,
    expected_filter,
    expected_params,
) -> None:
    captured = {}

    def fake_read_sql(sql, conn, params=None):
        captured["sql"] = str(sql)
        captured["params"] = params
        if function_name == "load_users_and_orgs":
            return pd.DataFrame(
                columns=["user_id", "email", "organisation_name"]
            )
        return pd.DataFrame()

    monkeypatch.setattr(database, "get_engine", lambda region: _Engine())
    monkeypatch.setattr(database.pd, "read_sql", fake_read_sql)

    getattr(database, function_name)("eu", org_id=org_id)

    assert captured["params"] == expected_params
    if expected_filter is None:
        assert "u.organisation_id = :org_id" not in captured["sql"]
        assert "u.organisation_id IS NULL" not in captured["sql"]
    else:
        assert expected_filter in captured["sql"]


def test_get_organisations_orders_by_name(monkeypatch) -> None:
    captured = {}

    def fake_read_sql(sql, conn):
        captured["sql"] = str(sql)
        return pd.DataFrame(
            [{"organisation_id": 196, "organisation_name": "Org A"}]
        )

    monkeypatch.setattr(database, "get_engine", lambda region: _Engine())
    monkeypatch.setattr(database.pd, "read_sql", fake_read_sql)

    result = database.get_organisations("eu")

    assert "id   AS organisation_id" in captured["sql"]
    assert "name AS organisation_name" in captured["sql"]
    assert "ORDER BY name" in captured["sql"]
    assert result.iloc[0]["organisation_id"] == 196
