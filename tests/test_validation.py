import math
import pytest
from services.validation import safe_float, parse_amount, parse_flag, clean_str, parse_iso_date, parse_int


@pytest.mark.parametrize('value,expected', [
    ('12.5', 12.5), (3, 3.0), ('nan', 0.0), ('inf', 0.0), ('-inf', 0.0),
    (-1, 0.0), (None, 0.0), ('x', 0.0), (True, 0.0), (1e12, 0.0),
])
def test_safe_float(value, expected):
    assert safe_float(value) == expected


def test_parse_amount_rounds_and_rejects_zero():
    assert parse_amount('10.006') == 10.01
    assert parse_amount(0) is None and parse_amount('nan') is None


@pytest.mark.parametrize('value,expected', [
    (1, 1), (0, 0), ('1', 1), ('true', 1), ('0', 0), (True, 1), ('abc', 0), (None, 0), (5, 0),
])
def test_parse_flag(value, expected):
    assert parse_flag(value) == expected


def test_clean_str_and_dates_and_ints():
    assert clean_str('  a ', 5) == 'a'
    assert clean_str(None, 5) == ''
    assert clean_str(5, 5) is None
    assert clean_str('abcdef', 5) is None
    assert parse_iso_date('2024-02-29').day == 29
    assert parse_iso_date('2023-02-29') is None
    assert parse_iso_date(20240101) is None
    assert parse_int('12') == 12 and parse_int(True) is None and parse_int('1.5') is None
