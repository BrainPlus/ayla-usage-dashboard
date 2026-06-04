import exporter


def test_methodology_describes_prepare_time_as_median() -> None:
    methodology = exporter.build_methodology_df(
        "eu",
        "2026-05-01,2026-05-31",
        "2026-03-01,2026-05-31",
    )

    row = methodology[methodology["Field"] == "Median prepare time"]

    assert len(row) == 1
    assert row.iloc[0]["Description"] == (
        "Median duration in minutes for prepare-only visits"
    )
    assert "Avg prepare time" not in set(methodology["Field"])
