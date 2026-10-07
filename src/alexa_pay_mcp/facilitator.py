"""AwLPay facilitator client.

In live mode the MCP server talks to the real AwLPay backend:
  GET  /.well-known/x402      discovery manifest
  POST /api/pay/quote         anything-to-anything conversion quote
  POST /api/pay/execute        402-gated execution (X-PAYMENT header)

In mock mode (default) everything runs against the in-process mock seller,
so the demo and tests move zero real money.
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error


def base_url() -> str:
    return os.getenv("AWLPAY_BASE_URL", "https://awlpay.fly.dev")


def mode() -> str:
    return os.getenv("AWL_MODE", "mock").lower()  # mock | live


def _post(path: str, body: dict, headers: dict | None = None, timeout: int = 30) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        base_url() + path, data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"status": resp.status, "body": json.loads(resp.read().decode())}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return {"status": e.code, "body": json.loads(raw)}
        except ValueError:
            return {"status": e.code, "body": {"error": raw[:300]}}


def discovery() -> dict:
    """GET /.well-known/x402 — who AwLPay is and where settle lives."""
    url = base_url() + "/.well-known/x402"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode())


_TIER_IDS = {"free": 0, "pro": 1, "l33t": 2}


def quote(
    from_chain: str,
    from_token: str,
    to_chain: str,
    to_token: str,
    amount_cents: int,
    tier: str = "free",
    to_address: str | None = None,
) -> dict:
    """Anything-to-anything conversion quote via the ConverterRouter.

    Returns the path + all-tier fees, or {refused: true, reason} when the
    law says no (unknown token, no path, dust eaten by fees).
    """
    if not isinstance(amount_cents, int) or isinstance(amount_cents, bool):
        return {"refused": True, "reason": "amount_cents must be an integer"}
    if amount_cents <= 0:
        return {"refused": True, "reason": "amount_cents must be positive"}
    body = {
        "from_chain": from_chain,
        "from_token": from_token,
        "to_chain": to_chain,
        "to_token": to_token,
        "amount_cents": amount_cents,
        "tier": _TIER_IDS.get(tier, 0),
    }
    if to_address:
        body["to_address"] = to_address
    res = _post("/api/pay/quote", body)
    if res["status"] != 200:
        return {"refused": True, "reason": res["body"]}
    return res["body"]
