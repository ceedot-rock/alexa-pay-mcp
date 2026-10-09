"""The x402 pay flow: discover -> 402 -> sign -> settle -> receipt.

One 402 response carries an `accepts[]` array (multi-rail shape); the payer
picks a rail it can settle, signs a gasless EIP-712 payment authorization
binding the resource (domain-v2 Payment struct — the resource is INSIDE the
signed struct so one proof can't re-buy a cheaper resource), and retries
with the X-PAYMENT header carrying the base64url proof JSON.

Replay protection: the seller keys on (proof-id, network); a replayed proof
gets a 409, never a double-settle.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import socket
import time
import urllib.parse
import urllib.request
import urllib.error

from .amounts import parse_amount, to_micro_usd
from .rails import get_rail, EVM_RAILS
from .wallet import AgentWallet, SpendCapExceeded

X402_VERSION = 2  # multi-rail accepts[] shape


def validate_resource_url(url: str) -> None:
    """Fail closed on SSRF (2026-10-08 disclosure): only http/https, and the
    target must not resolve to a private, loopback, link-local, reserved,
    multicast, or unspecified address.

    Call on live-mode URLs only — the mock seller deliberately binds
    loopback, so mock/demo flows must NOT pass through this.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"refusing resource URL with scheme {parsed.scheme!r}: http/https only"
        )
    host = parsed.hostname
    if not host:
        raise ValueError("refusing resource URL with no host")
    try:
        addrinfo = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ValueError(f"resource host {host!r} does not resolve: {e}")
    for info in addrinfo:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(f"refusing resource at internal address {ip}")


def _http_get(url: str, headers: dict | None = None, timeout: int = 15) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return e.code, _try_json(body)
    return 200, _try_json(body)


def _try_json(body: str):
    try:
        return json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return body


def fetch_payment_requirements(resource_url: str) -> dict:
    """GET the resource. Expect 402 + PaymentRequirements with accepts[]."""
    status, body = _http_get(resource_url)
    if status != 402:
        raise ValueError(f"expected HTTP 402, got {status}: {str(body)[:200]}")
    if not isinstance(body, dict) or not body.get("accepts"):
        raise ValueError("402 response carries no accepts[] payment requirements")
    return body


def select_rail(requirements: dict, payer_rails: list[str]) -> dict:
    """Pick the first accepts[] entry the payer can settle. Never assume one rail."""
    accepted = {a.get("network") for a in requirements["accepts"]}
    for rail in payer_rails:
        if rail in accepted:
            entry = next(a for a in requirements["accepts"] if a.get("network") == rail)
            return {"rail": rail, "entry": entry}
    raise ValueError(
        f"no common rail: seller accepts {sorted(accepted)}, payer has {payer_rails}"
    )


def payment_typed_data(
    *,
    payer: str,
    pay_to: str,
    amount_units: int,
    token: str,
    rail: str,
    resource: str,
    nonce: str,
    deadline: int,
) -> dict:
    """EIP-712 domain-v2 Payment struct. The resource is bound inside."""
    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
            ],
            "Payment": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "amount", "type": "uint256"},
                {"name": "token", "type": "string"},
                {"name": "rail", "type": "string"},
                {"name": "resource", "type": "string"},
                {"name": "nonce", "type": "string"},
                {"name": "deadline", "type": "uint256"},
            ],
        },
        "primaryType": "Payment",
        "domain": {"name": "AwLPay-x402", "version": "2"},
        "message": {
            "from": payer,
            "to": pay_to,
            "amount": amount_units,
            "token": token,
            "rail": rail,
            "resource": resource,
            "nonce": nonce,
            "deadline": deadline,
        },
    }


def build_payment_proof(
    *,
    wallet: AgentWallet,
    rail: str,
    entry: dict,
    resource_url: str,
    amount_str: str,
) -> dict:
    """Sign the authorization. Enforces caps BEFORE signing (integer math)."""
    rail_info = get_rail(rail)
    if rail not in EVM_RAILS:
        raise ValueError(f"rail {rail!r} is not EVM-signable in this build")
    amount_units = parse_amount(amount_str, rail_info["decimals"])
    required_units = int(entry.get("maxAmountRequired", "0"))
    if amount_units < required_units:
        raise ValueError(
            f"amount {amount_units} below seller requirement {required_units}"
        )
    # Caps enforced in micro-USD before any signature exists.
    wallet.check_spend(to_micro_usd(amount_units, rail_info["decimals"]))

    nonce = hashlib.sha256(f"{wallet.address}{resource_url}{time.time_ns()}".encode()).hexdigest()
    typed = payment_typed_data(
        payer=wallet.address,
        pay_to=entry.get("payTo", ""),
        amount_units=amount_units,
        token=rail_info["token"],
        rail=rail,
        resource=resource_url,
        nonce=nonce,
        deadline=int(time.time()) + 300,
    )
    sig = wallet.sign_typed_data(typed)
    proof = {
        "x402Version": X402_VERSION,
        "scheme": "exact",
        "network": rail,
        "payload": {
            "signature": sig.hex(),
            "typedData": typed,
            "proofId": nonce,
        },
    }
    proof_json = json.dumps(proof, separators=(",", ":")).encode()
    return {
        "x_payment": base64.urlsafe_b64encode(proof_json).decode(),
        "proof": proof,
        "amount_units": amount_units,
        "amount_micro_usd": to_micro_usd(amount_units, rail_info["decimals"]),
    }


def settle(resource_url: str, x_payment: str) -> dict:
    """Retry the resource with the X-PAYMENT header. 200 -> receipt."""
    status, body = _http_get(resource_url, headers={"X-PAYMENT": x_payment})
    if status == 402:
        reason = body.get("error") if isinstance(body, dict) else str(body)[:200]
        raise ValueError(f"payment rejected by seller (402): {reason}")
    if status == 409:
        raise ValueError("replayed proof: seller already settled this proof-id (409)")
    if status != 200:
        raise ValueError(f"settle failed: HTTP {status}: {str(body)[:200]}")
    if not isinstance(body, dict) or "receipt" not in body:
        raise ValueError("200 response carries no settlement receipt")
    return body["receipt"]


def verify_receipt(receipt: dict, expected: dict) -> dict:
    """Check a settlement receipt against what was agreed.

    expected: {amount_units, rail, pay_to}. Returns {ok, checks[]}.
    """
    checks = []
    ok = True

    def check(name: str, cond: bool, detail: str = ""):
        nonlocal ok
        checks.append({"check": name, "pass": bool(cond), "detail": detail})
        if not cond:
            ok = False

    check("has_tx_hash", bool(receipt.get("txHash") or receipt.get("tx_hash")),
          "receipt must name the settlement transaction")
    check("rail_matches", receipt.get("rail") == expected.get("rail"),
          f"got {receipt.get('rail')!r}, expected {expected.get('rail')!r}")
    try:
        got_amt = int(receipt.get("amount", -1))
        check("amount_matches", got_amt == int(expected.get("amount_units", -2)),
              f"got {got_amt}, expected {expected.get('amount_units')}")
    except (TypeError, ValueError):
        check("amount_matches", False, "amount not an integer")
    check("payee_matches", receipt.get("payTo") == expected.get("pay_to"),
          f"got {receipt.get('payTo')!r}")
    check("settled_at_present", bool(receipt.get("settledAt")),
          "receipt must carry a settlement timestamp")
    return {"ok": ok, "checks": checks}


def pay_resource(
    *,
    wallet: AgentWallet,
    resource_url: str,
    amount_str: str,
    payer_rails: list[str],
) -> dict:
    """Full flow: 402 -> select rail -> sign -> settle -> record -> receipt."""
    requirements = fetch_payment_requirements(resource_url)
    selection = select_rail(requirements, payer_rails)
    rail, entry = selection["rail"], selection["entry"]
    built = build_payment_proof(
        wallet=wallet, rail=rail, entry=entry,
        resource_url=resource_url, amount_str=amount_str,
    )
    receipt = settle(resource_url, built["x_payment"])
    rail_info = get_rail(rail)
    verification = verify_receipt(receipt, {
        "amount_units": built["amount_units"],
        "rail": rail,
        "pay_to": entry.get("payTo"),
    })
    wallet.record_spend(built["amount_micro_usd"], receipt)
    return {
        "receipt": receipt,
        "verification": verification,
        "rail": rail,
        "amount_units": built["amount_units"],
        "token": rail_info["token"],
        "lifetime_spent_micro_usd": wallet.lifetime_spent_micro_usd,
    }
