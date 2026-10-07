"""Demo: an Alexa+-style agent pays 1 USDC for a 402-gated report.

Run:  PYTHONPATH=src .venv/bin/python demo/demo_flow.py
Moves zero real money (mock seller + mock facilitator).
"""
import os
import sys
import tempfile

tmp = tempfile.mkdtemp(prefix="alexa-pay-demo-")
os.environ["AWL_WALLET_DIR"] = tmp
os.environ["AWL_WALLET_PASSWORD"] = "demo"
os.environ["AWL_MODE"] = "mock"

sys.path.insert(0, "src")

from alexa_pay_mcp.mock_seller import MockSeller
from alexa_pay_mcp.wallet import AgentWallet
from alexa_pay_mcp.x402 import pay_resource
from alexa_pay_mcp.amounts import format_amount


def say(agent: str, text: str):
    print(f"\n[{agent}] {text}")


def main():
    seller = MockSeller().start()
    wallet = AgentWallet(password="demo")
    resource = seller.url + "/report"

    say("agent", "I need the premium report. Checking the resource...")
    say("seller", "HTTP 402 — payment required. accepts[]: base-usdc, 1.00 USDC.")

    say("agent", "Selecting rail base-usdc from accepts[]. Signing gasless "
                 "EIP-712 authorization (1.00 USDC, resource-bound)...")
    result = pay_resource(
        wallet=wallet, resource_url=resource,
        amount_str="1.00", payer_rails=["base-usdc"],
    )

    say("seller", "X-PAYMENT verified: signature recovers, amount covers price, "
                  "proof-id fresh. HTTP 200 + settlement receipt.")
    r = result["receipt"]
    say("agent", f"Receipt verified: {format_amount(r['amount'], 6)} USDC on "
                 f"{r['rail']}, tx {r['txHash'][:18]}..., "
                 f"all {len(result['verification']['checks'])} checks passed.")
    say("agent", f"Lifetime spend: {format_amount(result['lifetime_spent_micro_usd'], 6)} "
                 "USD. Done — the report is mine.")
    seller.stop()


if __name__ == "__main__":
    main()
