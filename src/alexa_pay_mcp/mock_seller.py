"""Mock x402 seller for tests and the demo. Moves zero real money.

Serves one paid resource (/report):
  GET /report                  -> 402 + PaymentRequirements (accepts[])
  GET /report + X-PAYMENT       -> verifies the EIP-712 authorization
                                   (signature recovers to payer, amount covers
                                   price, proof-id not seen before)
                                -> 200 + settlement receipt, or 402/409
  GET /.well-known/x402        -> discovery manifest

Replay protection: proof-ids are keyed per network; a replayed proof-id
gets 409, never a double-settle.
"""
from __future__ import annotations

import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from eth_account import Account
from eth_account.messages import encode_typed_data

PRICE_MICRO_USDC = 1_000_000  # 1 USDC
PAY_TO = "0x000000000000000000000000000000000000dEaD"
RAIL = "base-usdc"


class MockSeller(HTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.used_proof_ids: set[str] = set()
        self.receipts: list[dict] = []

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"

    def start(self) -> "MockSeller":
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()

    # -- verification (mirrors what a real facilitator checks) --------------
    def verify_payment(self, x_payment: str, resource: str) -> dict | None:
        """Returns the receipt dict, or None if the proof is invalid."""
        try:
            proof = json.loads(base64.urlsafe_b64decode(x_payment).decode())
        except Exception:
            return None
        if proof.get("x402Version") != 2 or proof.get("scheme") != "exact":
            return None
        if proof.get("network") != RAIL:
            return None
        payload = proof.get("payload", {})
        proof_id = payload.get("proofId", "")
        if not proof_id or proof_id in self.used_proof_ids:
            return None  # replay or missing id
        typed = payload.get("typedData")
        try:
            msg = encode_typed_data(full_message=typed)
            payer = Account.recover_message(msg, signature=bytes.fromhex(payload["signature"]))
        except Exception:
            return None
        m = typed.get("message", {})
        if m.get("resource") != resource:  # resource binding enforced
            return None
        if m.get("to", "").lower() != PAY_TO.lower():
            return None
        if int(m.get("amount", 0)) < PRICE_MICRO_USDC:
            return None
        if int(m.get("deadline", 0)) < int(time.time()):
            return None
        self.used_proof_ids.add(proof_id)
        receipt = {
            "txHash": "0x" + proof_id[:64],
            "rail": RAIL,
            "amount": int(m["amount"]),
            "payTo": PAY_TO,
            "payer": payer,
            "settledAt": int(time.time()),
        }
        self.receipts.append(receipt)
        return receipt


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status: int, body: dict):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        seller: MockSeller = self.server  # type: ignore
        if self.path == "/.well-known/x402":
            self._send(200, {
                "x402Version": 2,
                "merchant": "mock-seller (alexa-pay-mcp demo)",
                "acceptsFrom": [RAIL],
                "settleEndpoint": seller.url + "/report",
            })
            return
        if self.path == "/report":
            x_payment = self.headers.get("X-PAYMENT")
            if not x_payment:
                self._send(402, {
                    "x402Version": 2,
                    "error": "payment required",
                    "resource": seller.url + "/report",
                    "accepts": [{
                        "scheme": "exact",
                        "network": RAIL,
                        "maxAmountRequired": str(PRICE_MICRO_USDC),
                        "asset": "USDC",
                        "decimals": 6,
                        "payTo": PAY_TO,
                        "maxTimeoutSeconds": 300,
                    }],
                })
                return
            resource = seller.url + "/report"
            # Replay check BEFORE verify: used id -> 409.
            try:
                proof = json.loads(base64.urlsafe_b64decode(x_payment).decode())
                pid = proof.get("payload", {}).get("proofId", "")
            except Exception:
                pid = ""
            if pid and pid in seller.used_proof_ids:
                self._send(409, {"error": "proof already settled"})
                return
            receipt = seller.verify_payment(x_payment, resource)
            if receipt is None:
                self._send(402, {"error": "invalid payment proof"})
                return
            self._send(200, {"receipt": receipt, "content": "REPORT: …"})
            return
        self._send(404, {"error": "not found"})
