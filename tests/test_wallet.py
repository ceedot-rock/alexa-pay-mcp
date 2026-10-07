"""Wallet: encrypted keys, hard caps, mainnet gate."""
import pytest

from alexa_pay_mcp.wallet import (
    AgentWallet, WrongPassword, SpendCapExceeded,
    MainnetConfirmationError, WalletError,
)


def _wallet(tmp_path, **kw):
    return AgentWallet(
        password="test-pw",
        store_path=tmp_path / "wallet.json",
        ledger_path=tmp_path / "ledger.json",
        **kw,
    )


def test_create_and_reopen(tmp_path):
    w = _wallet(tmp_path)
    assert w.address.startswith("0x") and len(w.address) == 42
    w2 = _wallet(tmp_path)
    assert w2.address == w.address


def test_wrong_password(tmp_path):
    _wallet(tmp_path)
    with pytest.raises(WrongPassword):
        AgentWallet(password="nope",
                     store_path=tmp_path / "wallet.json",
                     ledger_path=tmp_path / "ledger.json")


def test_per_call_cap(tmp_path):
    w = _wallet(tmp_path, per_call_cap_micro_usd=1_000_000)
    w.check_spend(1_000_000)  # exactly at cap: ok
    with pytest.raises(SpendCapExceeded):
        w.check_spend(1_000_001)


def test_lifetime_cap(tmp_path):
    w = _wallet(tmp_path, lifetime_cap_micro_usd=2_000_000)
    w.record_spend(1_500_000, {"txHash": "0x1"})
    assert w.lifetime_spent_micro_usd == 1_500_000
    with pytest.raises(SpendCapExceeded):
        w.check_spend(600_000)  # 1.5M + 0.6M > 2M
    # ledger survives reopen
    w2 = _wallet(tmp_path)
    assert w2.lifetime_spent_micro_usd == 1_500_000


def test_spend_amount_must_be_positive_int(tmp_path):
    w = _wallet(tmp_path)
    with pytest.raises(Exception):
        w.check_spend(0)
    with pytest.raises(Exception):
        w.check_spend(-5)
    with pytest.raises(Exception):
        w.check_spend(1.5)  # type: ignore


def test_mainnet_needs_confirmation(tmp_path):
    with pytest.raises(MainnetConfirmationError):
        _wallet(tmp_path, network="mainnet")
    with pytest.raises(MainnetConfirmationError):
        _wallet(tmp_path, network="mainnet", confirm_mainnet="yes please")
    w = _wallet(tmp_path, network="mainnet", confirm_mainnet="I UNDERSTAND")
    assert w.network == "mainnet"


def test_testnet_is_default(tmp_path):
    assert _wallet(tmp_path).network == "testnet"


def test_keystore_not_world_readable(tmp_path):
    import os, stat
    w = _wallet(tmp_path)
    mode = stat.S_IMODE(os.stat(w.store_path).st_mode)
    assert mode & 0o077 == 0
