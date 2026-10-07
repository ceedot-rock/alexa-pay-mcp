"""Local agent wallet: encrypted keystore + hard spend caps.

- Keys live in an eth-account keystore JSON, password-encrypted. The server
  never sees a private key leave this module.
- Testnet is the default. Mainnet needs network="mainnet" AND the literal
  confirmation string "I UNDERSTAND" (mirrors the awlpay SDK).
- Spend caps are enforced HERE, not in the caller: per-call cap and a
  lifetime cap, both in integer micro-USD. Caps only move with explicit
  reconfiguration, never per-call.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from eth_account import Account

from .amounts import AmountError, MICRO_USD_DECIMALS

MAINNET_CONFIRMATION = "I UNDERSTAND"
DEFAULT_PER_CALL_CAP_MICRO_USD = 10_000_000      # $10
DEFAULT_LIFETIME_CAP_MICRO_USD = 25_000_000      # $25


class WalletError(Exception):
    """Base wallet error."""


class WrongPassword(WalletError):
    """Keystore password rejected."""


class SpendCapExceeded(WalletError):
    """A spend cap refused the payment."""


class MainnetConfirmationError(WalletError):
    """Mainnet requested without the confirmation string."""


def default_store_path() -> Path:
    return Path(os.getenv("AWL_WALLET_DIR", str(Path.home() / ".alexa-pay-mcp"))) / "wallet.json"


def default_ledger_path() -> Path:
    return Path(os.getenv("AWL_WALLET_DIR", str(Path.home() / ".alexa-pay-mcp"))) / "ledger.json"


class AgentWallet:
    def __init__(
        self,
        password: str,
        network: str = "testnet",
        confirm_mainnet: str | None = None,
        per_call_cap_micro_usd: int = DEFAULT_PER_CALL_CAP_MICRO_USD,
        lifetime_cap_micro_usd: int = DEFAULT_LIFETIME_CAP_MICRO_USD,
        store_path: Path | None = None,
        ledger_path: Path | None = None,
    ):
        if network not in ("testnet", "mainnet"):
            raise WalletError("network must be 'testnet' or 'mainnet'")
        if network == "mainnet" and confirm_mainnet != MAINNET_CONFIRMATION:
            raise MainnetConfirmationError(
                'Mainnet moves real money. Pass confirm_mainnet="I UNDERSTAND" '
                "(the literal string). Testnet is the default."
            )
        self.network = network
        self.per_call_cap = per_call_cap_micro_usd
        self.lifetime_cap = lifetime_cap_micro_usd
        self.store_path = Path(store_path) if store_path else default_store_path()
        self.ledger_path = Path(ledger_path) if ledger_path else default_ledger_path()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        if self.store_path.exists():
            try:
                keystore = json.loads(self.store_path.read_text())
                self._private_key = Account.decrypt(keystore, password).hex()
            except ValueError as e:
                raise WrongPassword("keystore password rejected") from e
        else:
            acct = Account.create()
            self._private_key = acct.key.hex()
            self.store_path.write_text(json.dumps(Account.encrypt(self._private_key, password)))
            try:
                self.store_path.chmod(0o600)
            except OSError:
                pass
        self.address = Account.from_key(self._private_key).address
        self._ledger = self._load_ledger()

    # -- ledger -----------------------------------------------------------
    def _load_ledger(self) -> dict:
        if self.ledger_path.exists():
            try:
                return json.loads(self.ledger_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"lifetime_spent_micro_usd": 0, "payments": []}

    def _save_ledger(self) -> None:
        self.ledger_path.write_text(json.dumps(self._ledger, indent=2))

    @property
    def lifetime_spent_micro_usd(self) -> int:
        return int(self._ledger.get("lifetime_spent_micro_usd", 0))

    # -- spending ---------------------------------------------------------
    def check_spend(self, amount_micro_usd: int) -> None:
        """Enforce caps. Raises SpendCapExceeded. Integer math only."""
        if not isinstance(amount_micro_usd, int) or isinstance(amount_micro_usd, bool):
            raise AmountError("spend amount must be an integer (micro-USD)")
        if amount_micro_usd <= 0:
            raise AmountError("spend amount must be positive")
        if amount_micro_usd > self.per_call_cap:
            raise SpendCapExceeded(
                f"amount {amount_micro_usd} micro-USD exceeds per-call cap "
                f"{self.per_call_cap} micro-USD"
            )
        if self.lifetime_spent_micro_usd + amount_micro_usd > self.lifetime_cap:
            raise SpendCapExceeded(
                f"lifetime cap {self.lifetime_cap} micro-USD would be exceeded "
                f"(spent {self.lifetime_spent_micro_usd}, adding {amount_micro_usd})"
            )

    def record_spend(self, amount_micro_usd: int, receipt: dict) -> None:
        self._ledger["lifetime_spent_micro_usd"] = (
            self.lifetime_spent_micro_usd + amount_micro_usd
        )
        self._ledger["payments"].append(
            {
                "amount_micro_usd": amount_micro_usd,
                "receipt": receipt,
                "at": int(time.time()),
            }
        )
        self._save_ledger()

    # -- signing ----------------------------------------------------------
    def sign_typed_data(self, typed_data: dict) -> bytes:
        """Sign EIP-712 typed data. Private key never leaves this object."""
        from eth_account.messages import encode_typed_data

        msg = encode_typed_data(full_message=typed_data)
        return Account.sign_message(msg, private_key=self._private_key).signature
