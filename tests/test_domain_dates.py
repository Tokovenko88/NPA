from datetime import date

import pytest

from npa_processor.domain.dates import format_npa_date, format_npa_date_iso, parse_npa_date


def test_parse_supported_formats():
    assert parse_npa_date("19.08.2026") == date(2026, 8, 19)
    assert parse_npa_date("2026-08-19") == date(2026, 8, 19)
    assert parse_npa_date("19/08/2026") == date(2026, 8, 19)


def test_missing_date_is_not_invented():
    assert parse_npa_date(None) is None
    assert format_npa_date("") == ""


def test_invalid_date_is_explicit_error():
    with pytest.raises(ValueError):
        parse_npa_date("19.99.2026", field_name="valid_from")


def test_output_formats_are_deterministic():
    value = date(2026, 8, 19)
    assert format_npa_date(value) == "19.08.2026"
    assert format_npa_date_iso(value) == "2026-08-19"
