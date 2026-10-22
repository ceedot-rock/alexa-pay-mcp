"""Regression tests for the 2026-10-21 backlog PoC pass (leads #12-#15).

Each test adapts a working PoC from
~/workspace/bounty-recon/backlog-poc/ (12-alexa-high01-ssrf-redirect,
13-alexa-high02-spend-toctou, 14-alexa-med01-ledger-perms,
15-alexa-med-low-bundle): the exploit succeeds on the pre-fix code and is
refused on the fixed code. HIGH-01/HIGH-02 both-direction evidence is in
ALEXA_FIXES.md (same tests run against the pristine tree fail there).
"""
import asyncio
import hashlib
import inspect
import json
import os
import socket
import stat
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import pytest

from alexa_pay_mcp import server
from alexa_pay_mcp.amounts import AmountError
from alexa_pay_mcp.mock_seller import MockSeller
from alexa_pay_mcp.rails import get_rail, list_rails
from alexa_pay_mcp.wallet import AgentWallet, SpendCapExceeded
from alexa_pay_mcp.x402 import _http_get, build_payment_proof, pay_resource, validate_resource_url

MARKER = "INTERNAL-ONLY-MARKER-7f3a"
PRICE = 1_000_000  # MockSeller price: 1 USDC in micro-USD


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    # Keep the fetch tests hermetic: no ambient proxy may reroute them.
    # (urllib consults no_proxy at request time, so setting it here is
    # effective even though the opener was built at import.)
    bypass = "127.0.0.1,localhost,rebind.test"
    for var in ("no_proxy", "NO_PROXY"):
        existing = os.environ.get(var, "")
        monkeypatch.setenv(var, f"{existing},{bypass}" if existing else bypass)


def _serve(handler_cls):
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ---------------------------------------------------------------- HIGH-01
class _InternalHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"secret": MARKER}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_redirect_hop_to_loopback_is_refused():
    """HIGH-01: a redirect target is the counterparty's choice and must
    pass the same SSRF guard as an initial URL. Pre-fix, urllib followed
    the 302 and returned the internal marker."""
    internal = _serve(_InternalHandler)
    internal_url = f"http://127.0.0.1:{internal.server_port}/latest/meta-data"

    class Redirector(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", internal_url)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    redirector = _serve(Redirector)
    try:
        with pytest.raises(ValueError, match="internal address"):
            _http_get(f"http://127.0.0.1:{redirector.server_port}/jump")
    finally:
        internal.shutdown()
        redirector.shutdown()


def test_direct_fetch_of_caller_chosen_url_unchanged():
    """HIGH-01 semantics pin: the INITIAL URL is the caller's choice (the
    mock seller deliberately binds loopback); only hops are re-validated."""
    internal = _serve(_InternalHandler)
    try:
        status, body = _http_get(
            f"http://127.0.0.1:{internal.server_port}/latest/meta-data"
        )
        assert status == 200
        assert body == {"secret": MARKER}
    finally:
        internal.shutdown()


# ---------------------------------------------------------------- MEDIUM-03
def test_dns_rebinding_second_resolution_is_never_used(monkeypatch):
    """MEDIUM-03: DNS answers public at validation time, loopback at
    connect time. Post-fix the host is resolved exactly once (at
    validation) and the fetch dials only the validated IP."""
    resolutions: list[str] = []
    dialed: list = []
    real_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(host, port=None, *args, **kwargs):
        if host == "rebind.test":
            resolutions.append(host)
            ip = "93.184.216.34" if len(resolutions) == 1 else "127.0.0.1"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 0))]
        return real_getaddrinfo(host, port, *args, **kwargs)

    def fake_connect(sock, address):
        dialed.append(address)
        raise OSError("test sentinel: dial intercepted")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", fake_connect)

    validate_resource_url("http://rebind.test/report")
    with pytest.raises(urllib.error.URLError):
        _http_get("http://rebind.test/report", timeout=5)
    assert resolutions == ["rebind.test"]  # resolved once: at validation
    assert dialed == [("93.184.216.34", 80)]  # only the validated IP dialed


# ---------------------------------------------------------------- HIGH-02
def test_concurrent_payments_cannot_exceed_lifetime_cap(tmp_path, monkeypatch):
    """HIGH-02: two concurrent payments against a lifetime cap of exactly
    one payment. Pre-fix both passed check_spend against stale state and
    both settled (2x the cap). Post-fix the loser is refused cleanly."""
    orig_verify = MockSeller.verify_payment

    def slow_verify(self, x_payment, resource):
        time.sleep(1)  # widen the check -> settle -> record window
        return orig_verify(self, x_payment, resource)

    monkeypatch.setattr(MockSeller, "verify_payment", slow_verify)
    seller = MockSeller().start()
    store, ledger = tmp_path / "wallet.json", tmp_path / "ledger.json"
    barrier = threading.Barrier(2)
    outcomes: dict[int, tuple[str, object]] = {}

    def worker(i: int):
        # Fresh wallet per call — exactly what server._wallet() builds.
        w = AgentWallet(
            password="poc-password", network="testnet",
            per_call_cap_micro_usd=PRICE, lifetime_cap_micro_usd=PRICE,
            store_path=store, ledger_path=ledger,
        )
        barrier.wait()
        try:
            outcomes[i] = ("ok", pay_resource(
                wallet=w, resource_url=seller.url + "/report",
                amount_str="1.00", payer_rails=["base-usdc"],
            ))
        except Exception as e:  # noqa: BLE001 - outcome recorded, asserted below
            outcomes[i] = ("err", e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    seller.stop()

    oks = [v for kind, v in outcomes.values() if kind == "ok"]
    errs = [v for kind, v in outcomes.values() if kind == "err"]
    assert len(seller.receipts) == 1  # exactly one settle, ever
    assert len(oks) == 1 and len(errs) == 1
    assert isinstance(errs[0], SpendCapExceeded)
    on_disk = json.loads(ledger.read_text())
    assert on_disk["lifetime_spent_micro_usd"] == PRICE
    assert len(on_disk["payments"]) == 1


# ---------------------------------------------------------------- MEDIUM-01
def _mode(p) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


def test_ledger_written_owner_only(tmp_path):
    """MEDIUM-01: ledger.json (full payment history) must be 0600 like
    the keystore. Pre-fix it landed 0644 under the default umask."""
    w = AgentWallet(password="poc", network="testnet",
                    store_path=tmp_path / "wallet.json",
                    ledger_path=tmp_path / "ledger.json")
    w.record_spend(1_000_000, {"txHash": "0x0", "rail": "base-usdc",
                               "amount": 1_000_000, "payTo": "0x0", "settledAt": 1})
    assert _mode(tmp_path / "wallet.json") & 0o077 == 0
    assert _mode(tmp_path / "ledger.json") == 0o600


def test_existing_loose_ledger_tightened_on_open(tmp_path):
    """MEDIUM-01: a pre-existing world-readable ledger is tightened to
    0600 when the wallet opens it."""
    ledger = tmp_path / "ledger.json"
    w = AgentWallet(password="poc", network="testnet",
                    store_path=tmp_path / "wallet.json", ledger_path=ledger)
    w.record_spend(1, {"txHash": "0x0"})
    os.chmod(ledger, 0o644)  # simulate the pre-fix state on disk
    assert _mode(ledger) == 0o644
    AgentWallet(password="poc", network="testnet",
                store_path=tmp_path / "wallet.json", ledger_path=ledger)
    assert _mode(ledger) == 0o600


# ---------------------------------------------------------------- MEDIUM-02
def test_failed_receipt_verification_fails_the_payment(tmp_path):
    """MEDIUM-02: a receipt that fails verification (wrong amount AND
    wrong payee) must not be recorded as a good payment or returned as
    one. The settled spend is still cap-accounted — the money moved —
    but the ledger entry is flagged UNVERIFIED and the call raises."""

    class LyingSeller(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, status, body):
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if not self.headers.get("X-PAYMENT"):
                self._send(402, {
                    "x402Version": 2, "error": "payment required",
                    "resource": "x", "accepts": [{
                        "scheme": "exact", "network": "base-usdc",
                        "maxAmountRequired": "1000000", "asset": "USDC",
                        "decimals": 6,
                        "payTo": "0x000000000000000000000000000000000000dEaD",
                        "maxTimeoutSeconds": 300}],
                })
            else:
                self._send(200, {"receipt": {
                    "txHash": "0xdead", "rail": "base-usdc", "amount": 1,
                    "payTo": "0x00000000000000000000000000000000000badd",
                    "settledAt": 1}, "content": "x"})

    srv = _serve(LyingSeller)
    url = f"http://127.0.0.1:{srv.server_port}/report"
    ledger = tmp_path / "ledger.json"
    w = AgentWallet(password="poc", network="testnet",
                    store_path=tmp_path / "wallet.json", ledger_path=ledger)
    try:
        with pytest.raises(ValueError, match="failed verification"):
            pay_resource(wallet=w, resource_url=url, amount_str="1.00",
                         payer_rails=["base-usdc"])
    finally:
        srv.shutdown()
    assert w.lifetime_spent_micro_usd == 1_000_000  # settled: still counted
    entry = json.loads(ledger.read_text())["payments"][-1]
    assert entry["verified"] is False
    assert "amount_matches" in entry["verification_failed_checks"]
    assert "payee_matches" in entry["verification_failed_checks"]


# ---------------------------------------------------------------- MEDIUM-04
def test_wallet_password_is_not_a_tool_parameter():
    """MEDIUM-04: the wallet password must come from server-side env
    only; as a tool parameter it transits the MCP tool-call surface."""
    assert "wallet_password" not in inspect.signature(server.pay).parameters
    assert "wallet_password" not in inspect.signature(server.wallet_balance).parameters
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    for name in ("pay", "wallet_balance"):
        props = tools[name].inputSchema.get("properties", {})
        assert "wallet_password" not in props


# ---------------------------------------------------------------- LOW-01
def test_bearer_authorized_helper():
    """LOW-01: the bearer check accepts exactly the right token."""
    assert server._bearer_authorized("Bearer s3cret", "s3cret")
    assert not server._bearer_authorized("Bearer s3cretX", "s3cret")
    assert not server._bearer_authorized("bearer s3cret", "s3cret")
    assert not server._bearer_authorized("", "s3cret")


def test_bearer_check_uses_constant_time_compare():
    """LOW-01: the comparison is hmac.compare_digest, not a plain !=."""
    src = inspect.getsource(server)
    assert "compare_digest" in src
    assert '!= f"Bearer {token}"' not in src


# ---------------------------------------------------------------- LOW-02
def test_proof_id_not_recomputable_from_public_inputs(tmp_path):
    """LOW-02: with the clock frozen, the pre-fix proofId was exactly
    sha256(address || url || time_ns) — recomputable by anyone who knows
    the payer address and URL and observes the request time. The keyed
    nonce must not equal that value."""
    w = AgentWallet(password="poc", network="testnet",
                    store_path=tmp_path / "wallet.json",
                    ledger_path=tmp_path / "ledger.json")
    entry = {"maxAmountRequired": "1000000",
             "payTo": "0x000000000000000000000000000000000000dEaD"}
    url = "http://seller.example/report"
    frozen_ns = 1792614803268346379
    with mock.patch.object(time, "time_ns", return_value=frozen_ns):
        built = build_payment_proof(
            wallet=w, rail="base-usdc", entry=entry,
            resource_url=url, amount_str="1.00",
        )
    proof_id = built["proof"]["payload"]["proofId"]
    old_formula = hashlib.sha256(f"{w.address}{url}{frozen_ns}".encode()).hexdigest()
    assert proof_id != old_formula
    assert len(proof_id) == 64


def test_proof_ids_are_unique_per_payment(tmp_path):
    w = AgentWallet(password="poc", network="testnet",
                    store_path=tmp_path / "wallet.json",
                    ledger_path=tmp_path / "ledger.json")
    entry = {"maxAmountRequired": "1000000",
             "payTo": "0x000000000000000000000000000000000000dEaD"}
    url = "http://seller.example/report"
    a = build_payment_proof(wallet=w, rail="base-usdc", entry=entry,
                            resource_url=url, amount_str="1.00")
    b = build_payment_proof(wallet=w, rail="base-usdc", entry=entry,
                            resource_url=url, amount_str="1.00")
    assert a["proof"]["payload"]["proofId"] != b["proof"]["payload"]["proofId"]


# ---------------------------------------------------------------- LOW-03
def test_cap_conversion_fails_closed_for_unpriced_tokens(monkeypatch):
    """LOW-03: cap conversion must not value every token at $1.00.
    Stablecoins price at par; BTC/XLM rails refuse without an operator-
    configured price. Pre-fix every live rail converted 1 token to
    1,000,000 micro-USD."""
    from alexa_pay_mcp.amounts import rail_amount_to_micro_usd

    for token in ("USDC", "USDT", "BTC", "XLM"):
        monkeypatch.delenv(f"AWL_USD_PRICE_{token}", raising=False)
    for info in list_rails():
        units = 10 ** int(info["decimals"])  # exactly 1 token
        if info["token"] in ("USDC", "USDT"):
            assert rail_amount_to_micro_usd(units, info) == 1_000_000
        else:
            with pytest.raises(AmountError, match="no USD price configured"):
                rail_amount_to_micro_usd(units, info)


def test_cap_conversion_uses_configured_price(monkeypatch):
    """LOW-03: an operator-configured price is honored for cap math."""
    from alexa_pay_mcp.amounts import rail_amount_to_micro_usd

    monkeypatch.setenv("AWL_USD_PRICE_BTC", "50000.00")
    assert rail_amount_to_micro_usd(10 ** 8, get_rail("bitcoin")) == 50_000 * 1_000_000
    monkeypatch.setenv("AWL_USD_PRICE_XLM", "0.25")
    assert rail_amount_to_micro_usd(10 ** 7, get_rail("stellar-xlm")) == 250_000
