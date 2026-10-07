"""alexa-pay-mcp: give an Alexa+ agent a wallet.

MCP server (spec 2025-11-25, Streamable HTTP transport) exposing AwLPay's
x402 payment rail as agent tools. Testnet/mock default; nothing here moves
real money unless AWL_MODE=live AND the wallet is mainnet-confirmed.

Tools:
  pay             settle a 402-gated resource (402 -> sign -> X-PAYMENT -> receipt)
  quote           anything-to-anything conversion quote (ConverterRouter)
  verify_receipt  check a settlement receipt against the agreement
  list_rails      rails this payer can settle on
  wallet_balance  local wallet address + spend ledger (no chain scan in mock mode)
"""
from __future__ import annotations

import os
import sys

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import __version__, facilitator
from .amounts import parse_amount, format_amount, to_micro_usd
from .rails import list_rails as _list_rails, get_rail
from .wallet import AgentWallet, WalletError
from .x402 import pay_resource, verify_receipt as _verify_receipt

mcp = FastMCP("alexa-pay", port=int(os.environ.get("PORT", "8000")))

MOCK_RAILS = ["base-usdc", "solana-usdc"]


def _wallet(password: str | None = None) -> AgentWallet:
    pw = password or os.getenv("AWL_WALLET_PASSWORD", "alexa-pay-demo")
    network = os.getenv("AWL_NETWORK", "testnet")
    confirm = os.getenv("AWL_MAINNET_CONFIRM")
    return AgentWallet(password=pw, network=network, confirm_mainnet=confirm)


@mcp.tool()
def pay(
    resource_url: str,
    amount: str,
    rail: str = "base-usdc",
    wallet_password: str | None = None,
) -> dict:
    """Pay for a 402-gated resource.

    amount is a decimal STRING in the rail's token units ("1.00" = 1 USDC).
    Integer-exact: floats are refused. Flow: GET -> 402 -> pick rail from
    accepts[] -> gasless EIP-712 sign (caps enforced first) -> X-PAYMENT ->
    settlement receipt, verified and recorded.
    """
    try:
        rail_info = get_rail(rail)
        amount_units = parse_amount(amount, rail_info["decimals"])  # validates
        wallet = _wallet(wallet_password)
        if facilitator.mode() == "live":
            # Live: real seller URL, real AwLPay rails.
            result = pay_resource(
                wallet=wallet, resource_url=resource_url,
                amount_str=amount, payer_rails=[rail],
            )
        else:
            # Mock/demo mode: the mock seller is the counterparty.
            from .mock_seller import MockSeller
            seller = MockSeller().start()
            try:
                result = pay_resource(
                    wallet=wallet,
                    resource_url=seller.url + "/report",
                    amount_str=amount, payer_rails=MOCK_RAILS,
                )
            finally:
                seller.stop()
        result["amount_display"] = format_amount(result["amount_units"], rail_info["decimals"])
        return {"ok": True, **result}
    except (WalletError, ValueError) as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def quote(
    from_rail: str,
    from_token: str,
    to_rail: str,
    to_token: str,
    amount_cents: int,
    tier: str = "free",
) -> dict:
    """Anything-to-anything conversion quote via the AwLPay ConverterRouter.

    amount_cents is an INTEGER (cents). Returns path + fees, or a refusal
    when the law says no (unknown token, no path, dust eaten by fees).
    """
    if facilitator.mode() != "live":
        return {
            "mode": "mock",
            "note": "quote hits the live facilitator; set AWL_MODE=live to use it",
            "echo": {
                "from": f"{from_rail}:{from_token}", "to": f"{to_rail}:{to_token}",
                "amount_cents": amount_cents, "tier": tier,
            },
        }
    return facilitator.quote(from_rail, from_token, to_rail, to_token, amount_cents, tier)


@mcp.tool()
def verify_receipt(receipt: dict, amount_units: int, rail: str, pay_to: str) -> dict:
    """Verify a settlement receipt against the agreed terms.

    Checks: tx hash present, rail matches, integer amount matches,
    payee matches, settlement timestamp present.
    """
    try:
        return _verify_receipt(receipt, {
            "amount_units": amount_units, "rail": rail, "pay_to": pay_to,
        })
    except (ValueError, TypeError) as e:
        return {"ok": False, "error": str(e)}


@mcp.tool()
def list_rails() -> dict:
    """Rails this payer can settle on, with token, decimals, and status."""
    return {"rails": _list_rails(), "mode": facilitator.mode()}


@mcp.tool()
def wallet_balance(wallet_password: str | None = None) -> dict:
    """Local wallet address, network, caps, and lifetime spend ledger.

    Mock mode reports the ledger only (no chain scan). Live mode would add
    per-rail on-chain balances.
    """
    try:
        wallet = _wallet(wallet_password)
        return {
            "address": wallet.address,
            "network": wallet.network,
            "mode": facilitator.mode(),
            "per_call_cap_micro_usd": wallet.per_call_cap,
            "lifetime_cap_micro_usd": wallet.lifetime_cap,
            "lifetime_spent_micro_usd": wallet.lifetime_spent_micro_usd,
        }
    except WalletError as e:
        return {"ok": False, "error": str(e)}


@mcp.custom_route("/about", methods=["GET"])
async def about(_request: Request) -> JSONResponse:
    """Service/about JSON for Streamable HTTP deployments.

    A health endpoint that proves the server is up without invoking a tool.
    """
    return JSONResponse({
        "ok": True,
        "service": "alexa-pay-mcp",
        "version": __version__,
        "mcp_spec": "2025-11-25",
        "mode": facilitator.mode(),
        "tools": ["pay", "quote", "verify_receipt", "list_rails",
                  "wallet_balance"],
        "rails": [r["rail"] for r in _list_rails()],
    })


def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    # stdio for local dev (Claude Desktop / inspector); streamable-http for
    # self-hosted Alexa+ track deployments (MCP spec 2025-11-25).
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
