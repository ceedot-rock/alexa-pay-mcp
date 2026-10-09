# Devpost submission draft — alexa-pay-mcp
Status: DRAFT. DO NOT SUBMIT — Devpost requires Corey's account sign-in.
Hackathon: Amazon Build, Ship, Shape — Alexa+ track
Deadline: October 23, 2026, 12:00 PM PT

## Title
alexa-pay-mcp — Give an Alexa+ agent a wallet

## Tagline
A self-hosted MCP server that lets an AI agent pay for 402-gated resources: five tools from "pay 1 USDC for the report" to a verified settlement receipt.

## Description

**The problem.** Alexa+ agents can read the web, call APIs, and book things — but they can't *pay* for things. Every paywalled API, every premium report, every metered tool returns `HTTP 402 Payment Required`, and agents hit that wall and stop. The 402 status code has existed since the nineties; nobody built the client.

**What we built.** alexa-pay-mcp is a self-hosted MCP server (MCP spec 2025-11-25, Streamable HTTP) that is the missing 402 client. Five tools:

- `pay` — the full 402 flow: GET → 402 → pick a rail from `accepts[]` → gasless EIP-712 sign → `X-PAYMENT` → verified receipt
- `quote` — anything-to-anything conversion quotes via AwLPay's ConverterRouter (or an honest refusal when the law says no)
- `verify_receipt` — five-check settlement verification (tx hash, rail, amount, payee, timestamp)
- `list_rails` — Base USDC, Solana USDC, Tron USDT, Bitcoin, Lightning, Stellar XLM, BSC
- `wallet_balance` — address, network, caps, lifetime spend ledger

**Money rules.** Amounts are integers parsed from decimal strings (`"1.00"` → 1,000,000 micro-USDC); floats are refused at the door. Spend caps ($10/call, $25/lifetime) live in the wallet and are enforced *before* any signature exists. Testnet is the default; mainnet requires the literal confirmation string. Replay a payment proof and the seller 409s it — no double-spend.

**How it's built.** Python + FastMCP, integer-exact money math, eth-account EIP-712 signing, AwLPay's x402 rail (multi-rail `accepts[]`, gasless auth). 29/29 tests green, including a full 402→sign→receipt→verify round trip against a mock seller with zero real money moved.

**What's next.** Live-seller integrations, per-agent sub-wallets, and spend-policy hooks so an Alexa+ skill can hand an agent a budget instead of a blank check.

## Built with
Python, FastMCP, MCP (Streamable HTTP), EIP-712, x402, AwLPay

## Links
- GitHub: https://github.com/ceedot-rock/alexa-pay-mcp
- Demo video: [VIDEO LINK PLACEHOLDER — upload demo/demo.mp4 to YouTube/Vimeo, paste public link here]

## Product feedback (for Amazon)
- What worked: FastMCP made the Streamable HTTP server straightforward; the MCP 2025-11-25 tool surface mapped cleanly onto a pay/quote/verify flow; EIP-712 typed-data signing keeps the auth gasless and resource-bound.
- What didn't: end-to-end testing against a real Alexa+ client requires Amazon-side access we don't have — all client interop was validated against the MCP inspector and stdio/HTTP transports locally.
- What we'd change about the Alexa+ MCP surface: a standard way for a server to advertise payment capability (402 handling, accepted rails) in its capability handshake, so agents discover "I can pay" the same way they discover tools.
