from contextlib import contextmanager
from datetime import date

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
            "get_monthly_bundle_creations",
            "get_bundle_filter_breakdown",
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
            "get_monthly_bundle_creations",
            "get_bundle_filter_breakdown",
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
            "get_monthly_bundle_creations",
            "get_bundle_filter_breakdown",
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

    if function_name in (
        "get_monthly_bundle_creations",
        "get_bundle_filter_breakdown",
        "get_star_ratings_by_org",
        "get_monthly_star_ratings",
    ):
        getattr(database, function_name)(
            "eu", date(2026, 1, 1), date(2026, 6, 8), org_id=org_id
        )
    else:
        getattr(database, function_name)("eu", org_id=org_id)

    if function_name in (
        "get_monthly_bundle_creations",
        "get_bundle_filter_breakdown",
        "get_star_ratings_by_org",
        "get_monthly_star_ratings",
    ):
        assert captured["params"] == {
            "start": date(2026, 1, 1),
            "end_exclusive": date(2026, 6, 9),
            **(expected_params or {}),
        }
        timestamp_alias = (
            "b.created_at"
            if function_name in (
                "get_monthly_bundle_creations",
                "get_bundle_filter_breakdown",
            )
            else "fa.created_at"
        )
        assert f"{timestamp_alias} >= :start" in captured["sql"]
        assert f"{timestamp_alias} < :end_exclusive" in captured["sql"]
    else:
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


def test_get_organisations_normalises_null_country_and_sector(monkeypatch) -> None:
    def fake_read_sql(sql, conn):
        return pd.DataFrame(
            [{
                "organisation_id": 196,
                "organisation_name": "Org A",
                "country": None,
                "sector": None,
            }]
        )

    monkeypatch.setattr(database, "get_engine", lambda region: _Engine())
    monkeypatch.setattr(database.pd, "read_sql", fake_read_sql)

    result = database.get_organisations("eu")

    assert result.iloc[0]["country"] == "Unknown"
    assert result.iloc[0]["sector"] == "Unknown"


@pytest.mark.parametrize(
    ("country", "sector", "expected_sql", "expected_params"),
    [
        ("Denmark", None, ["COALESCE(o.country::text, 'Unknown') = :country"], {"country": "Denmark"}),
        (None, "Care home", ["COALESCE(o.sector::text, 'Unknown') = :sector"], {"sector": "Care home"}),
        (
            "Unknown",
            "Care home",
            [
                "COALESCE(o.country::text, 'Unknown') = :country",
                "COALESCE(o.sector::text, 'Unknown') = :sector",
            ],
            {"country": "Unknown", "sector": "Care home"},
        ),
    ],
)
def test_organisation_filter_supports_country_and_sector_independently(
    country,
    sector,
    expected_sql,
    expected_params,
) -> None:
    sql, params = database._organisation_filter(None, country, sector)

    assert all(fragment in sql for fragment in expected_sql)
    assert params == expected_params


def test_get_bundle_counts_groups_and_orders_by_displayed_organisation_name(
    monkeypatch,
) -> None:
    captured = {}

    def fake_read_sql(sql, conn, params=None):
        captured["sql"] = str(sql)
        return pd.DataFrame()

    monkeypatch.setattr(database, "get_engine", lambda region: _Engine())
    monkeypatch.setattr(database.pd, "read_sql", fake_read_sql)

    database.get_bundle_counts_per_org("eu")

    assert "GROUP BY organisation_name" in captured["sql"]
    assert "ORDER BY organisation_name" in captured["sql"]


def test_monthly_bundle_creations_use_canonical_database_timestamp(monkeypatch) -> None:
    captured = {}

    def fake_read_sql(sql, conn, params=None):
        captured["sql"] = str(sql)
        return pd.DataFrame()

    monkeypatch.setattr(database, "get_engine", lambda region: _Engine())
    monkeypatch.setattr(database.pd, "read_sql", fake_read_sql)

    database.get_monthly_bundle_creations(
        "eu", date(2026, 1, 1), date(2026, 6, 8)
    )

    assert "DATE_TRUNC('month', b.created_at)" in captured["sql"]
    assert "COUNT(b.id) AS bundles_created" in captured["sql"]
    assert "SELECT * FROM bundles" not in captured["sql"]


def test_bundle_filter_breakdown_counts_all_preferences_and_missing_values(
    monkeypatch,
) -> None:
    captured = {}

    def fake_read_sql(sql, conn, params=None):
        captured["sql"] = str(sql)
        return pd.DataFrame()

    monkeypatch.setattr(database, "get_engine", lambda region: _Engine())
    monkeypatch.setattr(database.pd, "read_sql", fake_read_sql)

    database.get_bundle_filter_breakdown(
        "eu", date(2026, 1, 1), date(2026, 6, 8)
    )

    assert "SELECT b.bundle_filters" in captured["sql"]
    assert "bundle_filters->>'severity'" in captured["sql"]
    assert "bundle_filters->>'age'" in captured["sql"]
    assert "bundle_filters->>'physical_requirement'" in captured["sql"]
    assert captured["sql"].count("'Not set'") == 3
    assert "COUNT(*) AS bundle_count" in captured["sql"]
    assert "SELECT * FROM bundles" not in captured["sql"]


def test_monthly_ratings_join_answers_to_readable_question_labels(monkeypatch) -> None:
    captured = {}

    def fake_read_sql(sql, conn, params=None):
        captured["sql"] = str(sql)
        return pd.DataFrame()

    monkeypatch.setattr(database, "get_engine", lambda region: _Engine())
    monkeypatch.setattr(database.pd, "read_sql", fake_read_sql)

    database.get_monthly_star_ratings(
        "eu", date(2026, 1, 1), date(2026, 6, 8)
    )

    assert "question->>'question_en'" in captured["sql"]
    assert "AS question_label" in captured["sql"]
    assert "question->>'id' = ans->>'questionId'" in captured["sql"]
    assert "question_label" in captured["sql"]
