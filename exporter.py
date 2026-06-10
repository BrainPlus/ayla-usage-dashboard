# Excel export logic: builds .xlsx files from merged DataFrames using openpyxl.

import io

import pandas as pd


def build_methodology_df(
    region: str,
    date_range: str,
    org_filter_name=None,
) -> pd.DataFrame:
    """Builds the Methodology sheet content as a two-column DataFrame."""
    rows = [
        ("Region", region),
        ("Reporting period", date_range),
        ("Source of usage data", "Matomo API"),
        ("Source of organisation mapping", "PostgreSQL database"),
        ("Logins", "Number of Matomo visits per user/organisation"),
        ("Active users", "Users with 2 or more logins in the selected period"),
        (
            "Avg real session time",
            "Average duration in minutes for deliver visits longer than 20 minutes",
        ),
        (
            "Min real session time",
            "Shortest individual deliver visit over 20 minutes (minutes) for any user in the organisation",
        ),
        (
            "Max real session time",
            "Longest individual deliver visit over 20 minutes (minutes) for any user in the organisation",
        ),
        (
            "Median prepare time",
            "Median duration in minutes for prepare-only visits",
        ),
        (
            "Short visits",
            "Count of deliver visits lasting 20 minutes or less",
        ),
        (
            "Completed sessions",
            "Deliver-mode Session Complete events, deduplicated by "
            "(Matomo visitId + bundleId + sessionId). Repeat deliveries in separate "
            "visits are counted separately; prepare-mode events are excluded.",
        ),
        (
            "Days since last completed session",
            "Calendar days since the organisation's most recent deliver-mode Session "
            "Complete event in the last 365 days. Organisations without one show "
            "No recent session.",
        ),
        (
            "Delivery funnel",
            "Deliver Selected, Active Delivery, and Completed Session counts are each "
            "deduplicated by (Matomo visitId + bundleId + sessionId). Active Delivery "
            "requires a Deliver Selected event and at least one high-confidence "
            "deliver-mode activity signal.",
        ),
        (
            "Delivery funnel drop-off",
            "Absolute difference and percentage decrease from each funnel stage to "
            "the next. Percentage uses the previous stage as the denominator.",
        ),
        (
            "Avg activities per session",
            "Total Activity Complete events divided by completed sessions in the selected period. "
            "Note: fires on forward navigation — rapid click-through may inflate this count.",
        ),
        ("Last login date", "Most recent recorded Matomo visit date"),
        (
            "Groups avg rating",
            "Average 1-5 star rating submitted by patient groups at end of session",
        ),
        (
            "Therapists avg rating",
            "Average 1-5 star rating submitted by therapists after session",
        ),
        (
            "Activities completed",
            "Count of Activity Complete events in Matomo (delivered sessions only)",
        ),
        (
            "Approx. Engagement Ratio",
            "Talking Point Expand Clicks divided by Step Forward Clicks per activity in deliver mode. "
            "Step Forward Click is a proxy denominator — Matomo does not record every talking point shown.",
        ),
        (
            "Audio / Session",
            "Audio interaction events (Button/Play/Pause clicks) per completed session in deliver mode, per organisation.",
        ),
        (
            "Video / Session",
            "Video interaction events (Button/Play/Pause clicks) per completed session in deliver mode, per organisation.",
        ),
        (
            "Additional Activity / Session",
            "How often facilitators accepted the prompt to run an additional main activity, "
            "per completed session in deliver mode.",
        ),
        (
            "Replacement rates",
            "Change Activity Click events (main / warmup / reality orientation) per completed session "
            "in deliver mode, per organisation.",
        ),
    ]
    if org_filter_name is not None:
        rows.insert(1, ("Organisation filter", org_filter_name))
    return pd.DataFrame(rows, columns=["Field", "Description"])


def build_excel_report(
    user_detail: pd.DataFrame,
    org_summary: pd.DataFrame,
    monthly_ratings: pd.DataFrame,
    region: str,
    date_range: str,
    activity_usage_table: pd.DataFrame | None = None,
    org_filter_name=None,
) -> bytes:
    """
    Builds an in-memory Excel workbook and returns its raw bytes for Streamlit download.

    Sheets (in order):
        1. Organisation Summary
        2. User Detail
        3. Monthly Ratings
        4. Activity Usage
        5. Methodology

    All columns are auto-sized up to a maximum width of 50 characters.

    Args:
        user_detail:           output of merger.build_user_detail
        org_summary:           output of merger.build_org_summary
        monthly_ratings:       output of database.get_monthly_star_ratings
        region:                "uk" or "eu"
        date_range:            "YYYY-MM-DD,YYYY-MM-DD" for the reporting period
        activity_usage_table:  output of merger.build_activity_usage_table (optional)

    Returns:
        bytes of the .xlsx file
    """
    if activity_usage_table is None:
        activity_usage_table = pd.DataFrame(columns=["Activity Name", "Completions"])

    methodology = build_methodology_df(region, date_range, org_filter_name=org_filter_name)

    sheets = [
        ("Organisation Summary", org_summary),
        ("User Detail", user_detail),
        ("Monthly Ratings", monthly_ratings),
        ("Activity Usage", activity_usage_table),
        ("Methodology", methodology),
    ]

    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, df in sheets:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            _autosize_columns(writer.sheets[sheet_name], df)

    return buffer.getvalue()


def _autosize_columns(worksheet, df: pd.DataFrame, max_width: int = 50) -> None:
    """Sets each column width to the max content length, capped at max_width."""
    for i, column in enumerate(df.columns, start=1):
        header_len = len(str(column))
        # Sample up to 1000 rows to avoid iterating huge DataFrames
        max_data_len = (
            df.iloc[:1000, i - 1]
            .astype(str)
            .str.len()
            .max()
        )
        max_data_len = int(max_data_len) if pd.notna(max_data_len) else 0
        col_width = min(max(header_len, max_data_len) + 2, max_width)
        col_letter = worksheet.cell(row=1, column=i).column_letter
        worksheet.column_dimensions[col_letter].width = col_width
