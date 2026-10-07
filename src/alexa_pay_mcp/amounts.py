"""Integer-exact money. No floats anywhere near a payment.

Every amount enters as a decimal STRING (e.g. "1.00") and becomes an integer
count of the rail's smallest unit (e.g. micro-USDC for 6-decimal rails).
Floats are refused at the door: float("1.10") is already a lie in binary.
"""
from __future__ import annotations


class AmountError(ValueError):
    """Raised when an amount cannot be represented exactly."""


def parse_amount(s: str, decimals: int) -> int:
    """Parse a decimal string into integer smallest-units.

    "1.00" @ 6 decimals -> 1_000_000. Refuses: non-strings (floats!),
    negatives, empty input, more fractional digits than the rail allows.
    """
    if isinstance(s, bool) or not isinstance(s, str):
        raise AmountError(f"amount must be a decimal string, got {type(s).__name__}")
    t = s.strip()
    if not t:
        raise AmountError("amount is empty")
    if t.startswith("-"):
        raise AmountError("amount must not be negative")
    if t.startswith("+"):
        t = t[1:]
    if not t.replace(".", "", 1).isdigit() or t.count(".") > 1:
        raise AmountError(f"amount is not a decimal number: {s!r}")
    whole, _, frac = t.partition(".")
    if len(frac) > decimals:
        raise AmountError(
            f"amount {s!r} has more precision than the rail allows ({decimals}dp)"
        )
    whole = whole or "0"
    frac = (frac + "0" * decimals)[:decimals]
    return int(whole) * (10 ** decimals) + int(frac)


def format_amount(units: int, decimals: int) -> str:
    """Format integer smallest-units back to a decimal string."""
    if not isinstance(units, int) or isinstance(units, bool):
        raise AmountError("units must be an integer")
    if units < 0:
        raise AmountError("units must not be negative")
    scale = 10 ** decimals
    return f"{units // scale}.{units % scale:0{decimals}d}"


# Micro-USD (6dp) is the ledger's internal unit: 1 USDC == 1 USD == 10**6.
MICRO_USD_DECIMALS = 6


def to_micro_usd(units: int, rail_decimals: int, usd_per_token: str = "1.00") -> int:
    """Convert a rail-native integer amount to integer micro-USD.

    usd_per_token is a decimal string (default 1.00 for stablecoins).
    Pure integer math: units * price // scale.
    """
    price_micro = parse_amount(usd_per_token, MICRO_USD_DECIMALS)
    return units * price_micro // (10 ** rail_decimals)
