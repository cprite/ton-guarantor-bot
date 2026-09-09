from decimal import Decimal

import pytest

from guarantor.errors import AmountError
from guarantor.money import format_ton, format_units, from_units, parse_amount, to_units


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1", 1_000_000_000),
        ("0.5", 500_000_000),
        ("1,5", 1_500_000_000),
        (" 2.5 ", 2_500_000_000),
        ("0.000000001", 1),
    ],
)
def test_parse_amount_accepts_human_input(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "-1", "0", "1e400", "nan", "0.0000000001"])
def test_parse_amount_rejects_nonsense(text):
    with pytest.raises(AmountError):
        parse_amount(text)


def test_parse_amount_respects_jetton_decimals():
    assert parse_amount("1.5", decimals=6) == 1_500_000
    with pytest.raises(AmountError):
        parse_amount("0.0000001", decimals=6)


def test_units_round_trip():
    assert from_units(to_units(Decimal("3.25"))) == Decimal("3.25")


def test_formatting_trims_trailing_zeros():
    assert format_ton(1_500_000_000) == "1.5 TON"
    assert format_ton(1_000_000_000) == "1 TON"
    assert format_units(1_500_000, 6, "USDT") == "1.5 USDT"
