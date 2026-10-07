# Security Policy

alexa-pay-mcp gives an agent a wallet. A bug that lets money move when the
law says it must not — wrong amount, no cap check, replayed proof, or a
receipt that verifies against the wrong terms — is a security issue, not a
normal bug.

## Reporting a vulnerability

Please do not open a public issue for security problems.

Use GitHub's private vulnerability reporting on this repository
(Security tab, "Report a vulnerability").

Include the affected tool or module, the mode (mock / live), steps or inputs
to reproduce, and what you expected versus what happened.

You can expect an acknowledgement within 3 business days. We will keep you
updated while we investigate and credit you in the changelog unless you
prefer to stay anonymous.

## In scope

- Amount handling: any float on the money path, or a decimal string that
  parses to the wrong integer units
- Cap bypass: spending above the per-call ($10) or lifetime ($25) cap
- Mainnet confirmation gate: anything that can reach mainnet without
  `AWL_MODE=live` AND the literal confirmation string
- Replay: a settlement proof accepted twice
- Receipt verification mismatches: tx hash, rail, amount, payee, or
  timestamp checks that can be fooled
- The `alexa-pay-mcp` server, its five tools, and the `/about` health route

## Out of scope

- Operator deployments we do not run
- Social engineering, spam, or denial-of-service against hosted demos
