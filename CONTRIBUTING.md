# Contributing to alexa-pay-mcp

Thanks for helping give agents a wallet.

## Ground rules

These are the money laws. They are not negotiable in a PR.

- All money math is **integer-exact**. Amounts are parsed from decimal strings
  (`"1.00"` → 1,000,000 micro-USDC). Floats are refused at the door.
- Wallet caps ($10 per call, $25 lifetime) are enforced **before** signing,
  never after.
- **Mock is the default.** Nothing may reach mainnet without `AWL_MODE=live`
  AND the literal mainnet confirmation string.
- A 402 refusal (or a quote refusal) is a result, not something to work
  around.

## Quick checks

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
PYTHONPATH=src .venv/bin/python -m pytest   # 29 tests, all green
```

CI runs the test suite plus an HTTP smoke test on every pull request.

## Adding or changing a tool

1. Add the `@mcp.tool()` in `src/alexa_pay_mcp/server.py`.
2. Add or extend tests under `tests/` — a money-path change without a test
   does not ship.
3. Document the tool in the README table.
4. Open a pull request using the template.

## Licensing

alexa-pay-mcp is Apache-2.0. By contributing you agree your contribution may
be distributed under that license.
