"""End-to-end x402 flow against the mock seller: 402 -> sign -> 200.

Moves zero real money. Also covers: replayed proof -> 409, underpayment
refused, resource binding enforced, receipt verification.
"""
import base64
import json
import urllib.request
import urllib.error

import pytest

from alexa_pay_mcp.mock_seller import MockSeller, PRICE_MICRO_USDC, PAY_TO, RAIL
from alexa_pay_mcp.wallet import AgentWallet
from alexa_pay_mcp.x402 import (
    fetch_payment_requirements, select_rail, build_payment_proof,
    settle, verify_receipt, pay_resource,
)


@pytest.fixture()
def seller():
    s = MockSeller().start()
    yield s
    s.stop()


@pytest.fixture()
def wallet(tmp_path):
    return AgentWallet(password="pw",
                       store_path=tmp_path / "w.json",
                       ledger_path=tmp_path / "l.json")


def test_402_carries_accepts(seller):
    req = fetch_payment_requirements(seller.url + "/report")
    assert req["x402Version"] == 2
    assert req["accepts"][0]["network"] == RAIL
    assert req["accepts"][0]["maxAmountRequired"] == str(PRICE_MICRO_USDC)


def test_full_pay_flow(seller, wallet):
    result = pay_resource(
        wallet=wallet, resource_url=seller.url + "/report",
        amount_str="1.00", payer_rails=["base-usdc"],
    )
    receipt = result["receipt"]
    assert receipt["amount"] == PRICE_MICRO_USDC
    assert receipt["rail"] == RAIL
    assert receipt["payTo"] == PAY_TO
    assert result["verification"]["ok"] is True
    assert wallet.lifetime_spent_micro_usd == 1_000_000


def test_replay_gets_409(seller, wallet):
    req = fetch_payment_requirements(seller.url + "/report")
    sel = select_rail(req, ["base-usdc"])
    built = build_payment_proof(
        wallet=wallet, rail=sel["rail"], entry=sel["entry"],
        resource_url=seller.url + "/report", amount_str="1.00",
    )
    first = settle(seller.url + "/report", built["x_payment"])
    assert first["amount"] == PRICE_MICRO_USDC
    with pytest.raises(ValueError, match="409"):
        settle(seller.url + "/report", built["x_payment"])


def test_underpayment_refused(seller, wallet):
    with pytest.raises(ValueError, match="below seller requirement"):
        pay_resource(
            wallet=wallet, resource_url=seller.url + "/report",
            amount_str="0.50", payer_rails=["base-usdc"],
        )


def test_resource_binding_enforced(seller, wallet):
    """A proof signed for /report can't buy /other."""
    req = fetch_payment_requirements(seller.url + "/report")
    sel = select_rail(req, ["base-usdc"])
    built = build_payment_proof(
        wallet=wallet, rail=sel["rail"], entry=sel["entry"],
        resource_url="http://evil.example/loot", amount_str="1.00",
    )
    # verify_payment checks the resource binding
    assert seller.verify_payment(built["x_payment"], seller.url + "/report") is None


def test_receipt_verification_catches_tampering():
    good = {"txHash": "0xabc", "rail": "base-usdc", "amount": 1_000_000,
            "payTo": PAY_TO, "settledAt": 123}
    exp = {"amount_units": 1_000_000, "rail": "base-usdc", "pay_to": PAY_TO}
    assert verify_receipt(good, exp)["ok"] is True
    bad = dict(good, amount=999_999)
    assert verify_receipt(bad, exp)["ok"] is False
    wrong_rail = dict(good, rail="solana-usdc")
    assert verify_receipt(wrong_rail, exp)["ok"] is False


def test_no_common_rail(seller):
    req = fetch_payment_requirements(seller.url + "/report")
    with pytest.raises(ValueError, match="no common rail"):
        select_rail(req, ["lightning"])
