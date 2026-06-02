import pandas as pd
import pytest

import matomo


@pytest.mark.parametrize(
    ("function", "expected_columns"),
    [
        (
            matomo.get_visit_durations,
            ["user_id", "visit_duration_seconds", "has_deliver_action"],
        ),
        (
            matomo.get_sessions_delivered,
            ["bundle_id", "session_id", "user_id"],
        ),
        (
            matomo.get_activity_completions_per_user,
            ["user_id", "activities_completed"],
        ),
    ],
)
def test_raw_visit_transformers_return_empty_dataframe_for_non_list_payload(
    function,
    expected_columns: list[str],
) -> None:
    result = function("2026-01-01,2026-01-31", raw_visits={"result": "error"})

    assert isinstance(result, pd.DataFrame)
    assert result.empty
    assert list(result.columns) == expected_columns
