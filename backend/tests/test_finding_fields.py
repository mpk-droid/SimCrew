from __future__ import annotations

import pytest

from app.models.finding import normalize_file_path, normalize_line_range


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ([10, 20], [10, 20]),
        ((10, 20), [10, 20]),
        ([10], [10, 10]),
        (["10", "20"], [10, 20]),
        (42, [42, 42]),
        (42.0, [42, 42]),
        ("42", [42, 42]),
        ("10-20", [10, 20]),
        ("lines 10 to 20", [10, 20]),
        ([10, 20, 30], [10, 20]),
        (None, None),
        ("", None),
        ("n/a", None),
        ([], None),
        (["a", "b"], None),
        ({"start": 1}, None),
        (True, None),
    ],
)
def test_normalize_line_range(value: object, expected: list[int] | None) -> None:
    assert normalize_line_range(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("src/app.py", "src/app.py"),
        ("  README.md ", "README.md"),
        ("", None),
        (None, None),
        (["a.py"], None),
        (123, "123"),
    ],
)
def test_normalize_file_path(value: object, expected: str | None) -> None:
    assert normalize_file_path(value) == expected


def test_file_path_is_capped_to_column_length() -> None:
    assert len(normalize_file_path("a" * 5000)) == 1024
