# Project context — JURY Analytics

Current mode: public beta on GitHub Pages. See [release status](ROADMAP.md) for the measured baseline, pinned source/data SHAs and open gates. See [the runbook](RUNBOOK.md) for current pipeline and reproducible artifact checks.

## Historical staging notes

The following sections describe work before the production GitHub repository and Pages rollout.

### P3 staging preview

Target: independent JURY token analytics on GitHub Pages under DrKarpov after staging acceptance. Black/red/green, local Telegram-style SVG plane, RU/EN. Pepegun Analytics is an architectural reference only. No AI, MCP, Wallet Agent, paid-service runtime dependencies or mandatory always-on server. No external repo created or published. The existing Pepegun repository is not modified.

P2: raw transfer rows, two-read full history check, TonAPI swap comparison for primary-discovered traces, independently matching current holder observations + supply sum check, separate lifecycle and liquidity evidence, manual staging workflow. Not a proof of global history completeness, DEX protocol decoding, final settlement or historical balances.

P3: separate BigInt wallet analytics and UI for current holder distribution, top net buyers/sellers, address lookup (CRC-checked friendly/mainnet and raw addresses), observed raw transfer flows, GRAM trade cashflow and weighted GRAM prices, direct-transfer edges, LP and supply diagnostics. The current holder observation is independent of time range. Cashflow is not PnL; transfer flows are not balances; address links do not establish common ownership. No protocol role labels or fabricated history. Stage candidate and evidence files are bound by candidate digest, assembled to a separate preview directory and explicitly marked unpublished. Indexer CLI refuses to write under docs/; no automatic publishing. GitHub workflow creates preview artifact even after a nonzero audit result, when required files exist.

Verification: 32 Python unit tests and 37 JS assertions passed, Python compilation and JS syntax checks passed. All automated calculation tests use synthetic fixtures, not actual JURY history. Browser launched but navigation to loopback blocked by ERR_BLOCKED_BY_ADMINISTRATOR. Added CI browser test; actual CI not run. Live Toncenter DNS remains blocked. GitHub connector returns 404 for DrKarpov/jury-analytics and exposes no repository creation or workflow dispatch action. No external deployment or full real-history statistics.

Next mandatory gate: create/import separate GitHub repository (private staging recommended), run Staging index via Actions or a network-enabled host, inspect candidate and all differences against known real buy-bot trades, validate provider schemas, trace identity, actual settlement, global completeness and fixed-chain anchor, DEX coverage, supply/LP coverage and holder observations. Then implement historical balances, cost basis and PnL only for supported flows, wallet role verification, cache, chart interaction, export and publication gate. Do not publish as trustworthy before acceptance.

## P3.1 — 2026-11-27

Added canonical candidate and separate evidence digest validation (Python/JS parity tested), strict token and trace checks, validated IndexedDB fallback, history-prefix rollback/change rejection, and provisional FIFO gross GRAM estimate in address detail. Strict eligibility: matching full discovered-trace audit, raw transfer-to-trade one-to-one coverage for the address, no observed external token flows or non-GRAM trades, unambiguous order, nonnegative inventory, and matching current holder observation. This is deliberately not certified realized profit; no network fees, unrealized PnL, historical block-pinned balance, or carried cost basis across wallet transfers. New evidence digest required for preview; regenerate older staging artifacts. No public snapshot has been populated. GitHub repository lookup still returned 404; no available create-repository action. DNS lookups for both API hosts returned no addresses. Chromium local navigation failed with ERR_BLOCKED_BY_ADMINISTRATOR; actual browser CI remains unverified. No changes to Pepegun Analytics, no live deploy, no real history loaded. Mandatory next step remains separate repository/staging host, live index and real-swap reconciliation before release.

Verification: 33 Python unit tests and 72 JavaScript assertions pass; syntax and compilation pass. Browser test blocked as described.
