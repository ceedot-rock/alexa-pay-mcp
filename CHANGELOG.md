# Changelog

## 0.1.1 — 2026-10-21 (security fixes)

- **Redirect safety:** fetches of payment resources now validate every
  redirect hop against the same SSRF policy as the initial URL, and the
  connection dials the address the guard validated instead of resolving
  the name a second time.
- **Spend-cap race closed:** the check → settle → record sequence of a
  payment now runs under a lock, so concurrent payments can no longer
  both pass the lifetime-cap check against stale ledger state.
- **Receipt verification enforced:** a settlement receipt that fails
  verification is no longer treated as a successful payment. The settled
  amount is recorded in the ledger flagged UNVERIFIED (it still counts
  against the lifetime cap — the money moved) and the payment call fails.
- **Ledger privacy:** `ledger.json` is now written with owner-only
  (0600) permissions like the keystore, and an existing looser file is
  tightened when the wallet opens it.
- **Proof IDs:** payment proof IDs are now keyed to the wallet, so they
  can no longer be recomputed from public values (address, URL, time).
- **Currency conversion:** spend-cap accounting no longer values every
  token at $1.00. Non-stablecoin rails require an operator-configured
  USD price (`AWL_USD_PRICE_<TOKEN>`) or the payment is refused.
- **Wallet password:** no longer accepted as an MCP tool parameter; it
  is read from the `AWL_WALLET_PASSWORD` environment variable only.
- **Bearer check:** the HTTP transport's bearer-token comparison now
  runs in constant time.

## 0.1.0

- Initial release: MCP server giving Alexa+ agents a wallet — x402 pay
  flow (discover → 402 → sign → settle → receipt) over the AwLPay rail,
  local encrypted wallet with hard spend caps, mock seller for demos.
