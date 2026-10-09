# DRAFT — reply to Shiqiang Chen's 2026-10-08 disclosure (NOT SENT — needs Corey's review)

To: hermesone <hermesone@agent.qq.com>
Subject: Re: Security disclosure: alexa-pay-mcp unauthenticated wallet/pay surface

Shiqiang —

Thank you. Both findings check out against the tree:

1. Confirmed — `_wallet()` fell back to the hard-coded demo password when
   `AWL_WALLET_PASSWORD` was unset. The fallback is removed; the wallet now
   refuses to initialize without a configured password (fail closed).
2. Confirmed — the Streamable-HTTP transport ran with no auth. It now
   refuses to start without an explicit `MCP_BEARER_TOKEN` (every request
   needs the matching `Authorization: Bearer` header) and binds 127.0.0.1
   by default.
3. Live-mode `resource_url` is now scheme-checked (http/https only) and
   refused when it resolves to an internal address.

Verified locally: 35/35 tests pass, and a live smoke test shows
unauthenticated and wrong-token POSTs now get 401 while a valid token
returns 200. The fix ships with the next push. I'm also enabling Private
Vulnerability Reporting on the repo so the next report has the right
channel.

Happy to credit you in the advisory — tell me the name/handle you want
listed.

— Corey Tasz, Slid Phi Labs
