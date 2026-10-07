# Architecture — alexa-pay-mcp

```
 ┌──────────────┐   MCP (Streamable HTTP, spec 2025-11-25)   ┌───────────────┐
 │  Alexa+ agent │ ◄────────────────────────────────────────► │ alexa-pay-mcp │
 └──────────────┘        pay / quote / verify_receipt /      │  FastMCP      │
                         list_rails / wallet_balance         └───────┬───────┘
                                                                   │
                              ┌────────────────────────────────────┼───────────────────┐
                              │                                    │                   │
                       ┌──────▼──────┐                     ┌───────▼──────┐   ┌────────▼────────┐
                       │   wallet.py │                     │    x402.py   │   │ facilitator.py  │
                       │ keystore +  │                     │ 402 → sign → │   │ AwLPay backend  │
                       │ hard caps   │                     │ X-PAYMENT →  │   │ quote / execute │
                       │ (testnet    │                     │ receipt      │   │ /.well-known/   │
                       │  default)   │                     └──────┬───────┘   │   x402          │
                       └─────────────┘                            │           └─────────────────┘
                              │                          ┌───────▼────────┐
                              │                          │  mock_seller   │
                              │                          │  (tests/demo,  │
                              │                          │   $0 real)      │
                              │                          └────────────────┘
                       ┌──────▼──────┐
                       │ amounts.py  │
                       │ int-only    │
                       │ money math  │
                       └─────────────┘
```

## The pay flow (tool: `pay`)

1. `GET resource` → **402** + `PaymentRequirements` (`accepts[]`, multi-rail).
2. `select_rail`: first `accepts[]` entry the wallet can settle. Never assume one rail.
3. `build_payment_proof`: parse `"1.00"` → integer micro-units (floats refused);
   `wallet.check_spend()` enforces per-call + lifetime caps **before** signing;
   sign EIP-712 `Payment` struct with the **resource bound inside** (domain v2).
4. `GET resource` + `X-PAYMENT: <base64url proof>` → **200** + settlement receipt
   (or 402 invalid proof / 409 replayed proof-id).
5. `verify_receipt`: tx hash present, rail/amount/payee match, timestamp present.
6. `wallet.record_spend`: ledger updated to the micro-USD, integer math.

## Money rules

- Amounts enter as decimal strings, become integers. `parse_amount("1.10", 6)`
  is exact; `parse_amount(1.10, 6)` raises — floats are refused at the door.
- Ledger unit is integer micro-USD (6dp). No float touches a balance.
- Caps: $10/call, $25 lifetime defaults; enforced in `wallet.py`, not the caller.
- Testnet default. Mainnet needs `network="mainnet"` + `confirm_mainnet="I UNDERSTAND"`.

## Modes

- `AWL_MODE=mock` (default): in-process mock seller; demo + tests move $0.
- `AWL_MODE=live`: talks to `AWLPAY_BASE_URL` (default https://awlpay.fly.dev);
  `quote` hits `/api/pay/quote`, `pay` settles against real 402 sellers.
