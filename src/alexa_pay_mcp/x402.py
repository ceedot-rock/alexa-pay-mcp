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
import http.client
import ipaddress
import json
import socket
import time
import urllib.parse
import urllib.request
import urllib.error

from .amounts import parse_amount, rail_amount_to_micro_usd
from .rails import get_rail, EVM_RAILS
from .wallet import AgentWallet, SpendCapExceeded

X402_VERSION = 2  # multi-rail accepts[] shape


# IPs the SSRF guard has validated, keyed by hostname. The fetch layer
# dials the pinned IP instead of resolving the name again, so the address
# that was checked is the address that gets connected to — a DNS answer
# that flips between validation and connect (rebinding) lands nowhere
# (MEDIUM-03).
_PINNED_IPS: dict[str, str] = {}


def _pinned_ip_for(host: str) -> str | None:
    return _PINNED_IPS.get(host.lower())


def validate_resource_url(url: str) -> None:
    """Fail closed on SSRF (2026-10-08 disclosure): only http/https, and the
    target must not resolve to a private, loopback, link-local, reserved,
    multicast, or unspecified address.

    On success the first validated IP is pinned for the host (see
    _PINNED_IPS): the fetch layer connects to exactly that IP.

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
    ips: list[str] = []
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
        ips.append(str(ip))
    if ips:
        _PINNED_IPS[host.lower()] = ips[0]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Dial the guard-pinned IP for the host when one exists, so the
    address the SSRF guard validated is the address connected to. The
    Host header was already emitted from the real hostname before
    connect() runs, so it is unaffected by the swapped dial target."""

    def connect(self):  # mirrors stdlib, with a pinned dial target
        ip = _pinned_ip_for(self.host)
        if ip is None:
            return super().connect()
        real_host, self.host = self.host, ip
        try:
            return super().connect()
        finally:
            self.host = real_host


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS variant: TCP dials the pinned IP; TLS SNI and certificate
    verification still use the real hostname."""

    def connect(self):  # mirrors stdlib HTTPS connect, with a pinned dial
        ip = _pinned_ip_for(self.host)
        if ip is None:
            return super().connect()
        real_host, self.host = self.host, ip
        try:
            http.client.HTTPConnection.connect(self)
        finally:
            self.host = real_host
        server_hostname = self._tunnel_host or real_host
        self.sock = self._context.wrap_socket(
            self.sock, server_hostname=server_hostname
        )


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):  # noqa: D102 - stdlib handler shape
        return self.do_open(_PinnedHTTPConnection, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):  # noqa: D102 - stdlib handler shape
        return self.do_open(
            _PinnedHTTPSConnection, req,
            context=self._context, check_hostname=self._check_hostname,
        )


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validate every redirect hop against the SSRF guard (HIGH-01).

    The initial URL is the caller's choice — live mode validates it in
    server.pay; mock mode deliberately uses a loopback seller. A redirect
    target is the COUNTERPARTY's choice and is never trusted: each hop
    must pass the same validate_resource_url policy before it is fetched
    (which also pins the hop's IP, closing the rebinding window per hop).
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_resource_url(urllib.parse.urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(
    _PinnedHTTPHandler(), _PinnedHTTPSHandler(), _GuardedRedirectHandler(),
)


def _http_get(url: str, headers: dict | None = None, timeout: int = 15) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
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
    # Caps enforced in micro-USD before any signature exists. The
    # conversion is priced per the rail's token and fails closed when no
    # price is configured — never a silent $1.00 for a non-stablecoin
    # (LOW-03).
    wallet.check_spend(rail_amount_to_micro_usd(amount_units, rail_info))

    nonce = wallet.payment_nonce(resource_url)
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
        "amount_micro_usd": rail_amount_to_micro_usd(amount_units, rail_info),
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
    """Full flow: 402 -> select rail -> sign -> settle -> record -> receipt.

    The sign -> settle -> record span runs under the wallet's spend lock
    (HIGH-02): a concurrent payment cannot check the lifetime cap against
    state from before this payment recorded. A receipt that fails
    verification fails the payment (MEDIUM-02): the settled spend is
    recorded flagged UNVERIFIED — it still counts against the lifetime
    cap, because the money moved — and the call raises instead of
    returning a clean payment.
    """
    requirements = fetch_payment_requirements(resource_url)
    selection = select_rail(requirements, payer_rails)
    rail, entry = selection["rail"], selection["entry"]
    with wallet.spend_lock():
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
        wallet.record_spend(
            built["amount_micro_usd"], receipt, verification=verification
        )
        if not verification["ok"]:
            failed = [
                c["check"] for c in verification["checks"] if not c["pass"]
            ]
            raise ValueError(
                "settlement receipt failed verification "
                f"({', '.join(failed)}); the settled spend is recorded "
                "in the ledger flagged UNVERIFIED"
            )
    return {
        "receipt": receipt,
        "verification": verification,
        "rail": rail,
        "amount_units": built["amount_units"],
        "token": rail_info["token"],
        "lifetime_spent_micro_usd": wallet.lifetime_spent_micro_usd,
    }
