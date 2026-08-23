from __future__ import annotations

from typing import Any, Iterable

SPREADSHEET_FORMULA_PREFIXES = ("=", "+", "-", "@")
SPREADSHEET_ERROR_VALUES = frozenset({
    "#NAME?", "#VALUE!", "#REF!", "#DIV/0!", "#N/A", "#NUM!", "#NULL!",
})


def protect_spreadsheet_text(value: Any) -> Any:
    """Return a spreadsheet-safe CSV value while preserving visible text.

    Numeric and non-string values are returned unchanged. Text beginning with a
    spreadsheet formula trigger is prefixed with an apostrophe, which Excel
    treats as a text marker and does not display in the cell.
    """
    if not isinstance(value, str):
        return value
    if value.startswith("'") and len(value) > 1 and value[1] in SPREADSHEET_FORMULA_PREFIXES:
        return value
    if value.startswith(SPREADSHEET_FORMULA_PREFIXES):
        return "'" + value
    return value


def recover_spreadsheet_text(value: Any) -> Any:
    """Remove only the protective apostrophe written by this module."""
    if not isinstance(value, str):
        return value
    if len(value) >= 2 and value[0] == "'" and value[1] in SPREADSHEET_FORMULA_PREFIXES:
        return value[1:]
    return value


def spreadsheet_error_value(value: Any) -> str | None:
    text = str(recover_spreadsheet_text(value)).strip().upper()
    return text if text in SPREADSHEET_ERROR_VALUES else None


def validate_script_text(value: Any, scene_id: str) -> str:
    text = str(recover_spreadsheet_text(value))
    error = spreadsheet_error_value(text)
    if error:
        raise ValueError(f"Scene {scene_id} contains spreadsheet-corrupted script text: {error}")
    return text


def protect_csv_row(row: dict[str, Any], *, text_columns: Iterable[str] | None = None) -> dict[str, Any]:
    columns = set(text_columns) if text_columns is not None else None
    return {
        key: protect_spreadsheet_text(value) if columns is None or key in columns else value
        for key, value in row.items()
    }


def sanitize_csv_file(path, *, text_columns=None, scene_columns=("scene_id", "Scene ID"), required_text_columns=()):
    import csv
    from pathlib import Path
    path = Path(path)
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if not fieldnames:
        return
    selected = set(text_columns or fieldnames)
    required = set(required_text_columns)
    output = []
    for index, row in enumerate(rows, 1):
        scene_id = next((str(row.get(c) or "").strip() for c in scene_columns if row.get(c)), f"S{index:03d}")
        for column in required:
            if column in row:
                validate_script_text(row.get(column, ""), scene_id)
        output.append(protect_csv_row(row, text_columns=selected))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader(); writer.writerows(output)
