"""Integer-exact money: floats never reach a payment."""
import pytest

from alexa_pay_mcp.amounts import (
    parse_amount, format_amount, to_micro_usd, AmountError,
)


def test_parse_basic():
    assert parse_amount("1.00", 6) == 1_000_000
    assert parse_amount("0.01", 6) == 10_000
    assert parse_amount("1", 6) == 1_000_000
    assert parse_amount("  2.5 ", 6) == 2_500_000


def test_parse_refuses_floats():
    with pytest.raises(AmountError):
        parse_amount(1.10, 6)  # type: ignore
    with pytest.raises(AmountError):
        parse_amount(1.0, 6)  # type: ignore


def test_parse_refuses_negative_and_junk():
    with pytest.raises(AmountError):
        parse_amount("-1.00", 6)
    with pytest.raises(AmountError):
        parse_amount("", 6)
    with pytest.raises(AmountError):
        parse_amount("abc", 6)
    with pytest.raises(AmountError):
        parse_amount("1.2.3", 6)


def test_parse_refuses_overprecision():
    # rail allows 6dp; 7dp input is refused, not rounded
    with pytest.raises(AmountError):
        parse_amount("1.0000001", 6)


def test_format_roundtrip():
    assert format_amount(1_000_000, 6) == "1.000000"
    assert format_amount(parse_amount("3.14159", 6), 6) == "3.141590"
    with pytest.raises(AmountError):
        format_amount(1.5, 6)  # type: ignore


def test_to_micro_usd_integer_math():
    # 1 USDC (6dp) -> 1_000_000 micro-USD, no floats involved
    assert to_micro_usd(1_000_000, 6) == 1_000_000
    assert to_micro_usd(10_000, 6) == 10_000
