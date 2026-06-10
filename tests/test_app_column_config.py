import ast
from pathlib import Path


def _column_config_constructor_names(column_name: str) -> list[str]:
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(app_path.read_text())
    constructors = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue

        for key, value in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant) or key.value != column_name:
                continue
            if not isinstance(value, ast.Call):
                continue
            if not isinstance(value.func, ast.Attribute):
                continue

            constructors.append(value.func.attr)

    return constructors


def test_last_login_date_columns_are_text() -> None:
    assert _column_config_constructor_names("last_login_date") == [
        "TextColumn",
        "TextColumn",
    ]


def test_user_id_column_is_text() -> None:
    assert _column_config_constructor_names("user_id") == ["TextColumn"]


def test_completed_sessions_are_configured_for_organisation_and_user_tables() -> None:
    assert _column_config_constructor_names("completed_sessions") == [
        "NumberColumn",
        "NumberColumn",
    ]
