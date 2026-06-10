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


def test_methodology_describes_completed_session_definition() -> None:
    methodology = exporter.build_methodology_df("eu", "2026-05-01,2026-05-31")

    description = methodology[
        methodology["Field"] == "Completed sessions"
    ].iloc[0]["Description"]

    assert "Session Complete" in description
    assert "visitId + bundleId + sessionId" in description
    assert "prepare-mode events are excluded" in description


def test_methodology_describes_days_since_last_completed_session() -> None:
    methodology = exporter.build_methodology_df("eu", "2026-05-01,2026-05-31")

    description = methodology[
        methodology["Field"] == "Days since last completed session"
    ].iloc[0]["Description"]

    assert "deliver-mode Session Complete event" in description
    assert "last 365 days" in description
    assert "No recent session" in description


def test_methodology_describes_feedback_coverage_and_comment_rate() -> None:
    methodology = exporter.build_methodology_df("eu", "2026-05-01,2026-05-31")

    coverage = methodology[
        methodology["Field"] == "Feedback coverage"
    ].iloc[0]["Description"]
    comment_rate = methodology[
        methodology["Field"] == "Therapist comment rate"
    ].iloc[0]["Description"]

    assert "unique completed bundleId + sessionId pairs" in coverage
    assert "selected reporting period" in coverage
    assert "No sessions" in coverage
    assert "non-empty comment" in comment_rate


def test_methodology_describes_delivery_funnel_and_dropoff() -> None:
    methodology = exporter.build_methodology_df("eu", "2026-05-01,2026-05-31")

    funnel = methodology[methodology["Field"] == "Delivery funnel"].iloc[0]["Description"]
    dropoff = methodology[
        methodology["Field"] == "Delivery funnel drop-off"
    ].iloc[0]["Description"]

    assert "Deliver Selected, Active Delivery, and Completed Session" in funnel
    assert "visitId + bundleId + sessionId" in funnel
    assert "previous stage as the denominator" in dropoff


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
