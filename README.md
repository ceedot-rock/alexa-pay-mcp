# alexa-pay-mcp

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**Give an Alexa+ agent a wallet.** A self-hosted MCP server (spec 2025-11-25,
Streamable HTTP) that lets an AI agent pay for 402-gated resources — powered
by the [AwLPay](https://github.com/ceedot-rock/awlpay) x402 rail.

Built for the Amazon **Build, Ship, Shape** hackathon — Alexa+ track
(self-hosted MCP server / Agent Skill on the open MCP standard).

## What it does

Agents hit `HTTP 402 Payment Required` and stop. This server is the missing
client: five tools that take an agent from "pay 1 USDC for the report"
to a verified settlement receipt.

| Tool | What it does |
|---|---|
| `pay` | Full 402 flow: GET → 402 → pick rail from `accepts[]` → gasless EIP-712 sign → `X-PAYMENT` → verified receipt |
| `quote` | Anything-to-anything conversion quote via AwLPay's ConverterRouter (or refusal when the law says no) |
| `verify_receipt` | Check a settlement receipt: tx hash, rail, integer amount, payee, timestamp |
| `list_rails` | Rails the payer can settle: Base USDC, Solana USDC, Tron USDT, Bitcoin, Lightning, Stellar XLM, BSC |
| `wallet_balance` | Address, network, caps, lifetime spend ledger |

## How it works

```
Alexa+ agent ──MCP/Streamable HTTP──► alexa-pay-mcp ──x402──► seller (402)
        pay("1.00 USDC for the report")
              │
              ▼
   402 + accepts[] → select rail → EIP-712 sign (resource-bound)
              │         caps enforced BEFORE signing
              ▼
   X-PAYMENT ──► 200 + receipt ──► verified (5 checks) ──► ledger
```

Money rules: amounts are **integers** parsed from decimal strings (`"1.00"` →
1,000,000 micro-USDC); floats are refused at the door. Caps ($10/call,
$25/lifetime) live in the wallet, not the caller. Testnet default; mainnet
needs the literal confirmation string. Replay a proof and the seller 409s it.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full flow.

## Install & run

```bash
git clone https://github.com/ceedot-rock/alexa-pay-mcp && cd alexa-pay-mcp
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# stdio (Claude Desktop / MCP inspector)
PYTHONPATH=src .venv/bin/python -m alexa_pay_mcp.server

# Streamable HTTP (self-hosted, Alexa+ track)
MCP_TRANSPORT=streamable-http PYTHONPATH=src .venv/bin/python -m alexa_pay_mcp.server
```

Claude Desktop config:

```json
{ "mcpServers": { "alexa-pay": {
      "command": "/path/to/alexa-pay-mcp/.venv/bin/python",
      "args": ["-m", "alexa_pay_mcp.server"],
      "env": { "PYTHONPATH": "/path/to/alexa-pay-mcp/src" } } } }
```

Demo (zero real money — mock seller):

```bash
PYTHONPATH=src .venv/bin/python demo/demo_flow.py
```

Tests:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/ -q   # 29 passed
```

Live mode: `AWL_MODE=live` (default `AWLPAY_BASE_URL=https://awlpay.fly.dev`).
Wallet: `AWL_WALLET_PASSWORD`, `AWL_WALLET_DIR`; mainnet additionally needs
`AWL_NETWORK=mainnet` + `AWL_MAINNET_CONFIRM="I UNDERSTAND"`.

## Product feedback (for Amazon)

- What worked: FastMCP made the Streamable HTTP server straightforward; the
  MCP 2025-11-25 tool surface mapped cleanly onto a pay/quote/verify flow;
  EIP-712 typed-data signing keeps the auth gasless and resource-bound.
- What didn't: end-to-end testing against a real Alexa+ client requires
  Amazon-side access we don't have — all client interop was validated
  against the MCP inspector and stdio/HTTP transports locally.
- What we'd change about the Alexa+ MCP surface: a standard way for a
  server to advertise payment capability (402 handling, accepted rails) in
  its capability handshake, so agents discover "I can pay" the same way
  they discover tools.

## License

Apache-2.0 — see [LICENSE](LICENSE).
