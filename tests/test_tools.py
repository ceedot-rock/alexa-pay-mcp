"""MCP tool-level tests: the five tools behave through their public surface.

The @mcp.tool() decorator returns the raw function, so we call
server.<name>(...) directly — the same code path the MCP transport invokes.
"""
import asyncio

import pytest

from alexa_pay_mcp import server
from alexa_pay_mcp.mock_seller import PAY_TO


@pytest.fixture(autouse=True)
def _wallet_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AWL_WALLET_DIR", str(tmp_path / "awl"))
    monkeypatch.setenv("AWL_MODE", "mock")
    monkeypatch.setenv("AWL_WALLET_PASSWORD", "tool-test-pw")


def test_tool_list():
    tools = asyncio.run(server.mcp.list_tools())
    assert sorted(t.name for t in tools) == [
        "list_rails", "pay", "quote", "verify_receipt", "wallet_balance",
    ]


def test_pay_tool_mock():
    res = server.pay(resource_url="ignored-in-mock", amount="1.00", rail="base-usdc")
    assert res["ok"] is True
    assert res["receipt"]["amount"] == 1_000_000
    assert res["verification"]["ok"] is True
    assert res["lifetime_spent_micro_usd"] == 1_000_000


def test_pay_tool_refuses_overprecision():
    res = server.pay(resource_url="x", amount="1.0000001", rail="base-usdc")
    assert res["ok"] is False


def test_pay_tool_unknown_rail():
    res = server.pay(resource_url="x", amount="1.00", rail="nope")
    assert res["ok"] is False


def test_list_rails_tool():
    res = server.list_rails()
    rails = {r["rail"] for r in res["rails"]}
    assert {"base-usdc", "solana-usdc", "tron-usdt", "bitcoin",
            "lightning", "stellar-xlm", "bsc"} <= rails


def test_wallet_balance_tool():
    res = server.wallet_balance()
    assert res["address"].startswith("0x")
    assert res["network"] == "testnet"
    assert res["lifetime_spent_micro_usd"] >= 0


def test_verify_receipt_tool():
    receipt = {"txHash": "0xabc", "rail": "base-usdc", "amount": 1_000_000,
               "payTo": PAY_TO, "settledAt": 123}
    res = server.verify_receipt(receipt=receipt,
                                amount_units=1_000_000, rail="base-usdc", pay_to=PAY_TO)
    assert res["ok"] is True


def test_quote_tool_mock_mode():
    res = server.quote(from_rail="base", from_token="USDC",
                       to_rail="solana", to_token="USDC", amount_cents=100)
    assert res["mode"] == "mock"
