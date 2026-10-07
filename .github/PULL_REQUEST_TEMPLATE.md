## What changed

<!-- One or two sentences. -->

## Tools touched

<!-- e.g. pay, quote, verify_receipt — or "none" -->

## Checks

- [ ] `python -m pytest` passes (29 tests green)
- [ ] Amounts stay integer-exact — no floats anywhere on the money path
- [ ] Wallet caps enforced before signing, unchanged ($10/call, $25/lifetime)
- [ ] Mock stays the default; nothing here can reach mainnet without `AWL_MODE=live`
      and the literal mainnet confirmation string
- [ ] New tool or behavior documented in README
