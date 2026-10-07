# Video script — alexa-pay-mcp (target: under 3 minutes)

## 0:00 — Hook (15s)
"Alexa+ agents can read the web, call APIs, and book things. But they can't
*pay* for things. Every paywalled API, every premium report, every metered
tool is closed to them. We fixed that."

## 0:15 — The problem (20s)
Show a 402 Payment Required response in a terminal.
"HTTP 402 — payment required — has existed since the nineties, but nobody
built the client. Agents hit this wall and stop."

## 0:35 — The fix (30s)
"This is alexa-pay-mcp: a self-hosted MCP server that gives an Alexa+ agent
a wallet. Five tools: pay, quote, verify_receipt, list_rails, wallet_balance.
Powered by the AwLPay x402 rail — multi-rail accepts[], gasless EIP-712
auth, integer-exact amounts. No floats anywhere near the money."

## 1:05 — Live demo (60s)
Run `demo/demo_flow.py`. Narrate each beat as it prints:
1. Agent requests the report → **402** with accepts[]
2. Agent picks base-usdc, signs the EIP-712 authorization (resource-bound)
3. Retry with X-PAYMENT → **200** + settlement receipt
4. Receipt verified: amount, rail, payee, tx hash — 5/5 checks
"One USDC. No gas, no nonce management, no float rounding. And replay the
proof and the seller 409s it — no double-spend."

## 2:05 — Under the hood (30s)
"Amounts are integers from string parsing — '1.00' becomes 1,000,000
micro-USDC; a float is refused at the door. Caps are enforced in the wallet
before any signature exists: $10 per call, $25 lifetime, testnet default.
Mainnet needs the literal confirmation string."

## 2:35 — Close (20s)
"Self-hosted, Apache-2.0, Streamable HTTP, MCP spec 2025-11-25. The wallet
an agent was missing. Links in the description."

## B-roll / captions
- Terminal running the demo (primary)
- ASCII architecture from README
- 402 response JSON close-up
