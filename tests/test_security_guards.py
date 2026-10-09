"""Guards for the 2026-10-08 coordinated disclosure (CWE-306/798/918).

These tests pin the fail-closed behavior: no password configured -> no
wallet; no bearer token -> no HTTP transport; internal/odd URLs -> refused.
"""
import socket

import pytest

from alexa_pay_mcp import server
from alexa_pay_mcp.wallet import WalletError
from alexa_pay_mcp.x402 import validate_resource_url


def test_wallet_fails_closed_without_password(monkeypatch):
    monkeypatch.delenv("AWL_WALLET_PASSWORD", raising=False)
    with pytest.raises(WalletError, match="not configured"):
        server._wallet()


def test_wallet_accepts_configured_password(monkeypatch):
    monkeypatch.setenv("AWL_WALLET_PASSWORD", "tool-test-pw")
    wallet = server._wallet()
    assert wallet is not None


def test_streamable_http_refuses_without_token(monkeypatch):
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="MCP_BEARER_TOKEN"):
        server.main()


def test_validate_resource_url_rejects_non_http():
    with pytest.raises(ValueError, match="http/https only"):
        validate_resource_url("file:///etc/passwd")


def test_validate_resource_url_rejects_loopback_literal():
    with pytest.raises(ValueError, match="internal address"):
        validate_resource_url("http://127.0.0.1:9/report")


def test_validate_resource_url_rejects_private_ip(monkeypatch):
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="internal address"):
        validate_resource_url("https://payments.example.test/x")
