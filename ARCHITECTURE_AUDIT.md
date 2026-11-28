# Architecture audit — first migration gate

Source c885270438b5d351d04c3080df6551336ec573b2; data 0376a2a1aadcbd7ffb0a40def25ddfa9aec78f54. Inspected source paths below, current workflow logs and data tree. This is an implementation inventory and first migration slice, not a complete code/security audit or production sign-off.

| Component | Actual implementation | Gap / migration decision |
|---|---|---|
| Primary ingestion | provider.py, indexer.py, incremental.py, recovery.yml: timestamp windows, 3600s overlap, append batches, action patches | Retain as discovery hints. Beyond-overlap late arrival and independently omitted transfers not automatically discovered. Introduce independent finalized cursor, durable revision/retry queues. |
| Account history | genesis_checkpoint.py, wallet_history.py, wallet_reconcile.py, wallet_stateinit.py, wallet_deployment.py | Useful verified normalized observations at fixed anchor, not live. Pages retain selected token opcodes, not every raw body. Refactor shared comparison and immutable evidence ingestion first, then add moving cursor without modifying prior observations. Missing code and identity remain explicit. |
| Independent audit | current_audit.py, history-audit.yml, audit.py | Endpoint swap multiset comparison limited to primary-discovered traces. Independent discovery and raw settlement separate; do not treat empty matches as verified trades. |
| Classifier | indexer.classify uses provider actions and one matching transfer; repair_overlay, payout_repair, delivery_repair, arbitrage overlay used by persistent_preview.corrected_history | Legacy repair contexts can be seed-bound; liquidity_scan is diagnostic only. Convert verified patterns to versioned adapters operating on canonical message evidence, with shared ambiguity and consumption checks. Do not remove legacy overlays until shadow equivalence and known differences explained. |
| Trace provenance | revision_evidence.py, current_audit.py | Versioned audit fingerprints and release lineage useful; revision_evidence requires exactly one repair proof on changed trace. Generalize to explicit ordered multi-proof lineage and rule version rather than assuming one repair. |
| Accounting and UI | docs/analytics.mjs, cost-basis.mjs, wallets.mjs, public_beta.py, persistent_preview.py | Public beta consumes provider-derived events plus overlays, not verified account-chain movements. FIFO is conservatively gated and not a full ledger. Keep interface stable while building shadow ledger; no migration of PnL or classifications before gates. |
| Scheduling/storage | recovery.yml, genesis.yml, history-audit.yml, checkpoint.sh, pages.yml | Shared writer lock and immutable Git evidence good; queued runs may be replaced, multiple jobs re-fetch data, cron delays observed. Current data tree 3,256 blobs / 135,933,850 bytes uncompressed (genesis 88,415,329, arbitrage 19,488,956). These are checked-out blob sizes, not Git clone size or quota. Measure actual wall time, clone, API usage and storage growth before choosing replacement infrastructure. |

## Verified baseline

- Genesis run 46139724111 all steps successful. Anchor 1795796649: 43,377 scanned tx; 505 linked, 490 complete chains, 1,262 candidates; 19,614/21,835 matched outgoing internal messages, 2,221 unmatched outgoing and 1,292 unmatched incoming. 623/623 mint receipts now on scanned chains; 21,835/23,333 primary hashes observed, 1,498 unobserved. All matched sends agree with primary endpoint hash and amount. 30/124 nonroot activations persisted; 94 unprocessed. This is not a balance proof.
- Primary cutoff 1795865440, 23,512 rows, 13,723 traces; 11,101 classified and 12,411 unclassified. Current audit log 744 matches (276 with swaps), 153 mismatches, 12,826 pending, 0 unavailable at that run. Separate denominators; not 744 verified trades. Prior scheduled primary recovery at 23:20 and 04:46 UTC, not 15-minute cadence. Cause not proven.
- Existing CI and publication passed for ebfd52a. Architecture docs c885270 CI passed; Pages run queued when inspected.

## First vertical slice and sequence

1. Shadow canonical internal delivery adapter: consume the same two-provider normalized rows that pass wallet_history.compare and persisted page validation. Deduplicate immutable observations by transaction hash; reject conflicts. Use existing graph verification (exact message equality, endpoints, successful transactions and increasing LT), not a new competing matching algorithm. Output stable message-hash movement IDs, sender/recipient jetton accounts, transaction/LT references, exact integer amounts and net internal movements. No owner inference or economic labels. Deterministic replay independent of row ordering and duplicate arrival. Read-only actual historical replay checks counts against the saved reconciliation status; compare batched/reversed ingestion output. This tests the shared primitive, NOT real live ingestion parity or supply reconciliation.
2. Add evidence envelope with raw provider provenance and finalized block cursor; preserve legacy normalized observations as limited proof. Live discovery must extend master/wallet chains past anchor, include new wallets, retry late arrivals beyond overlap. Do not apply timestamp-only finality assumptions.
3. Add mint/burn/bounce/in-flight movement adapters and per-account ledger at common boundary; verify balances and supply. Integrate owner bindings only with adequate state proof. Keep unknowns explicit and check conservation without confusing internal net flows with balances.
4. Migrate economic adapters and trace revisions with a common event consumption API and real fixtures; replay and compare before publication. Test historical/live actual ingestion parity; close outstanding protocol classes and run autonomous acceptance.
5. Consolidate scheduling and measure actual throughput, data growth, provider failure behavior, and catch-up; choose infrastructure based on evidence, preserve cost constraint.

No public data model or legacy classifications changed by slice 1. Work on the backfill can resume safely independently of the read-only shadow workflow. Before next commit inspect shadow report, CI, and live data refs. Do not declare the architecture gate closed until actual live input feeds this shared path and full replay/catch-up tests pass.

### Verified slice 1 and next implementation

Run 46140769121 verified deterministic shadow projection of 43,377 normalized rows and 19,614 matched deliveries. Slice 2 begins with `continuation_shadow.py`: bounded real post-anchor account capture with raw evidence and exact predecessor replay through shared comparator/projection. Target is the saved primary timestamp, not a finalized global block cursor. New accounts/master discovery, durable cursor and actual complete live parity are still open. Do not promote shadow output to public analytics.

### Persistent continuation slice

Real continuation run 46141040835 proved 173 post-anchor normalized rows and 25 additional paired deliveries on a 12-wallet sample, with exact raw replay. The next implementation `continuation_store.py` persists immutable linked-account envelopes, resumes partial pages at the original pinned target and cold-replays the combined projection. Existing recovery workflow uses its shared writer lock. This is still shadow, bounded to completed historical accounts and a timestamp target; no independent master/new-wallet discovery or global finalized cursor. Validate actual saved status and repeated run before moving to broader discovery.

### Second persistent continuation pass

First permanent pass 46142136509 persisted 194 rows/26 additional matched deliveries on 12/698 eligible accounts, no failures. Queue previously favored all unseen accounts before refreshing saved cursors. New interleaved lanes and explicit resumed counters test real repeated capture; post-anchor unmatched message frontier records candidate peers independently of primary trace classifications. At 698 accounts and 12 per pass, even perfect 15-min cadence needs >=59 runs for one census, so this is an incremental migration/diagnostic primitive, not the final discovery architecture. Next prioritize master/new-peer and finalized block discovery rather than solely scaling polling. Verify actual second pass and retained immutable evidence before extending.

### Message-directed discovery

Second real continuation pass 46144762107 resumed six saved accounts with 27 new rows, 235 cumulative rows and 42 additional paired deliveries. Frontier 151 edges/51 peers including one absent from historical graph. New counterpart_discovery.py captures and persists exact opposite endpoint by message hash, compares both providers and replays immutable evidence. It does not splice isolated rows into account prefixes. Next consume proved peer discovery hints for prefix acquisition and master/block cursors; actual full independent discovery and sustained throughput remain open.

### Peer prefixes

Run 46145307917 proved 20/20 isolated counterpart observations across 13 peers; one absent from historical graph. Next bounded recovery stage reconstructs full raw predecessor prefixes to pinned counterpart LT/hash, replays activation StateInit, and shadow-projects only completed identity-supported prefixes without overwriting existing observations. This is not yet a moving cursor for new wallets, master discovery or production ledger. The shared writer job budget increases to 20 min; consolidate and measure before production.

### Independent master continuation

Actual schedule run 46150796690 confirms persistent post-anchor pipeline works once unattended; it does not establish 15-minute cadence or 72-hour acceptance. Three peer prefixes now have initial StateInit proof, including the previously unseen peer; two missing historical hashes remain. New master_continuation.py binds the existing master tip to raw exact transaction evidence and reuses the shared account continuation cursor and receipt verification, storing isolated master evidence and opcode observations. It does not establish supply, mint/burn semantics, finalized-block coverage or automatically integrate new roots. Verify actual output, then unify peer/master roots and ongoing cursor before scaling. Avoid indefinite addition of separate polling stages; measure/consolidate writer occupancy.

### Unified shadow and moving peer cursors

Master continuation 46154493740 reached target 1795876369 with unchanged master tip, no new observed master rows and durable raw base/cursor. unified_shadow.py now combines replayed account prefixes, regular continuation, identity-supported peer prefixes with shared moving cursors, and independently validated within-target master receipt roots. Reject conflicting overlaps, preserve existing movements, report a unified frontier; isolated counterpart and master receipt rows do not masquerade as complete prefixes. New master roots without rows and unified-frontier consumption remain open. This is a migration checkpoint, not a final ingestion architecture; consolidate stages and measure actual scheduler/throughput before production. No global block watermark or balance/PnL proof.

### Operational consolidation

Unified run 46156916697 proved 47,344 unique compared rows, 23,175 paired deliveries, five peer cursors at target with zero conflicts. Runner logs show ~143 seconds actual execution after ~689 seconds before first log, concurrent genesis held the same writer lock until just before start. Consolidated existing five shadow stages into one dependency-ordered `live_pipeline.py` with validated target/digests, explicit stage outcomes and timings, checkpoint after each successful stage, failure artifact and fail-closed downstream behavior. This is orchestration, not a new discovery proof. Continue with independent finalized-block discovery and ledger contract; measure actual scheduling, capacity and coverage before claiming production. Legacy frontier feedback and master-root prefix acquisition remain open.

### Block enumeration feasibility

Consolidated pipeline 46158894538 all five stages persisted in 124.955s; unified 47,378 unique rows/23,185 paired deliveries. New read-only block pilot compares two full bounded provider interval censuses on adjacent known post-anchor mc seqnos, with raw compressed artifacts and explicit candidate/coverage gaps. TonAPI documents scalability limitations of masterchain-wide transactions; this experiment is not a production architecture choice. Actual enumeration agreement, resource cost and block semantics must be checked before selecting finalized-block cursor or shard-based discovery. No global finality, master identity of generic hints or full ledger claim.
