"""Integer-exact money. No floats anywhere near a payment.

Every amount enters as a decimal STRING (e.g. "1.00") and becomes an integer
count of the rail's smallest unit (e.g. micro-USDC for 6-decimal rails).
Floats are refused at the door: float("1.10") is already a lie in binary.
"""
from __future__ import annotations

import os


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

    Low-level converter: the payment path must NOT call this with the
    default price for a non-stablecoin — use rail_amount_to_micro_usd,
    which resolves the price per token and fails closed (LOW-03).
    """
    price_micro = parse_amount(usd_per_token, MICRO_USD_DECIMALS)
    return units * price_micro // (10 ** rail_decimals)


# Tokens with a configured USD price for spend-cap accounting. Only the
# $1-pegged stablecoins carry a built-in price. Any other token must be
# priced explicitly by the operator (env AWL_USD_PRICE_<TOKEN>) or the
# conversion refuses: valuing 1 BTC as $1.00 would under-count real spend
# against the caps by orders of magnitude (LOW-03).
TOKEN_USD_PRICES: dict[str, str] = {"USDC": "1.00", "USDT": "1.00"}


def token_usd_price(token: str) -> str:
    """Configured USD price (decimal string) for a token, or fail closed."""
    env_price = os.getenv(f"AWL_USD_PRICE_{token.upper()}")
    if env_price:
        parse_amount(env_price, MICRO_USD_DECIMALS)  # validate the format
        return env_price
    try:
        return TOKEN_USD_PRICES[token.upper()]
    except KeyError:
        raise AmountError(
            f"no USD price configured for token {token!r}: refusing to "
            "value it at $1.00 for spend-cap accounting. Set "
            f"AWL_USD_PRICE_{token.upper()} to enable payments on this rail."
        ) from None


def rail_amount_to_micro_usd(units: int, rail_info: dict) -> int:
    """Convert a rail-native amount to micro-USD for spend-cap accounting,
    priced per the rail's token (see token_usd_price)."""
    return to_micro_usd(
        units,
        int(rail_info["decimals"]),
        token_usd_price(str(rail_info["token"])),
    )
