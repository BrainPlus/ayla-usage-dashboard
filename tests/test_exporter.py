import exporter


def test_methodology_describes_prepare_time_as_median() -> None:
    methodology = exporter.build_methodology_df(
        "eu",
        "2026-05-01,2026-05-31",
    )

    row = methodology[methodology["Field"] == "Median prepare time"]

    assert len(row) == 1
    assert row.iloc[0]["Description"] == (
        "Median duration in minutes for prepare-only visits"
    )
    assert "Avg prepare time" not in set(methodology["Field"])


def test_methodology_includes_organisation_filter_when_selected() -> None:
    methodology = exporter.build_methodology_df(
        "eu",
        "2026-05-01,2026-05-31",
        org_filter_name="Org A",
    )

    row = methodology[methodology["Field"] == "Organisation filter"]

    assert row.iloc[0]["Description"] == "Org A"
    assert methodology["Field"].iloc[:2].tolist() == ["Region", "Organisation filter"]


def test_methodology_omits_organisation_filter_for_all_organisations() -> None:
    methodology = exporter.build_methodology_df(
        "eu",
        "2026-05-01,2026-05-31",
    )

    assert "Organisation filter" not in set(methodology["Field"])


def test_methodology_uses_one_reporting_period_without_fixed_window_text() -> None:
    methodology = exporter.build_methodology_df("eu", "2026-01-01,2026-03-31")

    assert methodology[methodology["Field"] == "Reporting period"].iloc[0][
        "Description"
    ] == "2026-01-01,2026-03-31"
    assert not methodology.astype(str).apply(
        lambda column: column.str.contains("30-day|90-day", regex=True).any()
    ).any()
