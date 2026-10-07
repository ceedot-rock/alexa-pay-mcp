"""Rail registry: which chains/tokens the payer can settle on.

Mirrors the AwLPay rail table (server/x402.py): a rail is listed only when
its verify path exists. Statuses here are the payer-side view: which rails
this MCP server can actually sign and settle on in its current mode.
"""
from __future__ import annotations

# name -> {token, decimals (smallest unit), kind, status}
RAILS: dict[str, dict] = {
    "base-usdc": {
        "token": "USDC",
        "decimals": 6,
        "kind": "evm",
        "status": "live",
        "note": "USDC on Base. Gasless EIP-712 authorization.",
    },
    "solana-usdc": {
        "token": "USDC",
        "decimals": 6,
        "kind": "solana",
        "status": "live",
        "note": "USDC on Solana.",
    },
    "tron-usdt": {
        "token": "USDT",
        "decimals": 6,
        "kind": "tron",
        "status": "live",
        "note": "USDT on Tron.",
    },
    "bitcoin": {
        "token": "BTC",
        "decimals": 8,
        "kind": "bitcoin",
        "status": "live",
        "note": "Bitcoin on-chain.",
    },
    "lightning": {
        "token": "BTC",
        "decimals": 3,  # millisats in x402 amount fields
        "kind": "lightning",
        "status": "live",
        "note": "Lightning invoices, millisat amounts.",
    },
    "stellar-xlm": {
        "token": "XLM",
        "decimals": 7,
        "kind": "stellar",
        "status": "live",
        "note": "Stellar XLM.",
    },
    "bsc": {
        "token": "USDC",
        "decimals": 18,
        "kind": "evm",
        "status": "live",
        "note": "USDC on BSC.",
    },
}

EVM_RAILS = {name for name, r in RAILS.items() if r["kind"] == "evm"}


def list_rails() -> list[dict]:
    """Public rail table for the list_rails tool."""
    return [
        {"rail": name, **info}
        for name, info in RAILS.items()
    ]


def get_rail(name: str) -> dict:
    try:
        return RAILS[name]
    except KeyError:
        raise ValueError(f"unknown rail {name!r}; known: {sorted(RAILS)}") from None
