# Фактический прогресс — 28.11.2026

Контрольная точка **до изменения алгоритма ускорения**. Данные: [09726b5d](https://github.com/DrKarpov/jury-analytics/tree/09726b5d379c528287c9da251e58b06ede947e82). Код опубликованной версии на момент проверки: [4a8fffd4](https://github.com/DrKarpov/jury-analytics/commit/4a8fffd488eda2de5027b9638f6f65fea632da61); [публикация](https://github.com/DrKarpov/jury-analytics/actions/runs/46135234765) и [тесты](https://github.com/DrKarpov/jury-analytics/actions/runs/46135234761) — success. Сайт [JURY Analytics](https://drkarpov.github.io/jury-analytics/). План: [ROADMAP.md](ROADMAP.md).

| Метрика | Измерено | Область |
|---|---:|---|
| Переводы Toncenter | 23 478 | cutoff 1795856210, не полнота блокчейна |
| Трассы | 13 703 | тот же индекс |
| Классифицированные операции | 11 088 | последний построенный snapshot на этом cutoff; включая transfers |
| Первичные доставки | 549 / 623 | anchor 1795796649 |
| Подтверждённая доставка эмиссии | 1 979 281,995975 / 2 000 000 JURY | тот же anchor |
| Связанные jetton-кошельки с завершённой цепочкой | 124 / 354 | 808 обнаруженных кандидатов, 454 пока не связаны |
| Сопоставленные внутренние доставки | 2 388 / 6 788 | 4 400 незакрытых (3 032 не просканированы, 1 368 цепь неполна) |
| Проверено account tx | 12 790 | 0 зарегистрированных gaps, не доказательство полноты |
| Арбитражные кандидаты | 893 / 1 445 | 39 не прошли, 513 ожидают; только двухплечевой паттерн |
| Текущий аудит | 423 match, 76 mismatch, 13 204 pending | 13 703 актуальных fingerprints; 144 совпадения со swap |
| Аудит исходного seed | 550 match, 100 mismatch / 650 попыток | из 13 542 исходных трасс, отдельный от current audit |

Доказательства: [индекс](https://github.com/DrKarpov/jury-analytics/blob/09726b5d379c528287c9da251e58b06ede947e82/update-status.json), [эмиссия](https://github.com/DrKarpov/jury-analytics/blob/09726b5d379c528287c9da251e58b06ede947e82/genesis/v1/status.json), [цепочки](https://github.com/DrKarpov/jury-analytics/blob/09726b5d379c528287c9da251e58b06ede947e82/genesis/v1/wallet-history/status.json), [арбитраж](https://github.com/DrKarpov/jury-analytics/blob/09726b5d379c528287c9da251e58b06ede947e82/arbitrage/v1/status.json), [current audit и reconciliation](https://github.com/DrKarpov/jury-analytics/actions/runs/46127841983), [сборка с 11 088 операций](https://github.com/DrKarpov/jury-analytics/actions/runs/46131114162). Cutoff актуального индекса: 28.11.2026 08:56:50 UTC; фактическая UTC дата определяется числом cutoff.

Независимый полный пересчёт 27.11 [run 46041974783](https://github.com/DrKarpov/jury-analytics/actions/runs/46041974783): 23 341 строк на cutoff 1795800269; два обхода Toncenter совпали. Это не счёт всех блокчейн-доставок, не текущая граница.

## Основной незакрытый этап — 1

Осталось 74 исходных доставки, 4 400 известных незакрытых внутренних сообщений, 454 ещё не связанных кандидата; числа могут увеличиваться при обходе новых цепочек. Не подтверждены owner/master binding, баланс на общей границе и отсутствие иных операций. Следующее действие: ускорить независимые provider calls и продолжить обход, затем проверить связность, code/master binding и полноту ledger. Сохранять все исходные факты.

Отдельный блокер аудита: отрицательные записи delivery repair содержали version=1, валидатор его не принимал. Исправлено в 4a8fffd488eda2de5027b9638f6f65fea632da61; тесты и публикация прошли, повтор workflow аудита на реальных данных ещё не подтверждён.

Арбитраж: 893 подтверждения — реальное продвижение против одного в прошлом, но не все маршруты и не все точные котировки. UI работает как бета, PnL не сертифицирован. Следующему агенту обязательно обновить цифры из фактических data refs и Actions, не использовать этот снимок как вечную истину.

## Follow-up checkpoint — primary mint delivery complete

[Data 27ac9565](https://github.com/DrKarpov/jury-analytics/tree/27ac9565330eff39ce9dd4e85776bfff793b030a): all 623/623 master messages verified (74 new), 2,000,000 JURY delivered, 381 recipient jetton wallets, no pending or failed receipt. [Proof](https://github.com/DrKarpov/jury-analytics/blob/27ac9565330eff39ce9dd4e85776bfff793b030a/genesis/v1/status.json). The wallet graph still needs closure; do not treat this as full history. [Parallel provider implementation](https://github.com/DrKarpov/jury-analytics/commit/47e8763eb3955001e46f386aa29ec538e4b7fb06) passed code tests and publication. Historical backfill run 46135597396 was still in progress when this checkpoint was written.

Next: produce an all-observed movement inventory that separates missing account-chain edges from indexed rows whose economic label is unknown. Topology flags (fan-out/fan-in/chained/cyclic) are review evidence, not proof of split swaps or LP. Historical normalized wallet pages retain only selected token opcodes; complete non-token/bounce payload capture remains open. Inventory is diagnostic; do not alter immutable transfer facts or promote unverified roles.

## Follow-up — wallet traversal and liquidity research

[Data c4b4de01](https://github.com/DrKarpov/jury-analytics/tree/c4b4de01e1d179f5c4984a254e1383dac19dfc0f) records 16,541 scanned account transactions (+3,751), 405 linked jetton accounts (+51), 157 completed linked chains (+33), 8,527 observed internal sends and 3,788 matched deliveries (+1,400). The discovered frontier expanded to 893 candidates; 4,739 internal sends still unmatched. Primary index reached 23,501 transfers and 13,718 traces at cutoff 1795862089. Mint receipt count remains 623/623. Inventory workflow queued; its real results not yet available. See [DeDust v2 real examples and ABI](research/DEDUST_V2_LIQUIDITY.md) for 3 previously unresolved LP-related cases. No new economic classifications installed from these samples; need raw replay and mass validation.

## Next historical completeness check — bidirectional discovery

Found a structural limitation of the original traversal: only outbound internal transfers expanded the graph. Successful inbound transfers from as-yet-unlinked accounts are now candidates too; a sender is linked only after both independently compared transactions have matching message hash, amount, endpoints, success and increasing LT. Master receipts remain separately verified. Upstream gaps are reported separately from outgoing gaps; both must close. Existing historical checkpoints remain unchanged. Regression tests cover missing, inconsistent, failed and out-of-order senders and exclude the master. Mass execution and resulting counts are not yet confirmed at this checkpoint.

## Liquidity settlement evidence — implementation checkpoint

At data 715cfbc309218aade0857c8fa36330294d1cef99 the inventory counted 23,507 indexed transfer rows (11,099 classified, 12,408 not classified) and 9,226 traces requiring review. The initial LP evidence contains 66 matched and 148 unresolved action records. New bounded workflow profiles provider actions across the indexed universe and attempts DeDust CPMM v2 same-trace Join/Exit settlements, with historical pool code and causal token delivery checks. Records live in liquidity-proof/v1, separate from trade data. No confirmed production count yet; raw traces lacking provider hints, multi-trace deposits, position ownership/fee/principal split, other protocols and integration remain open. Existing genesis work continues; don't claim global completeness.

## Session handoff — verified live checkpoint and next recovery pass

Data [a34f0485](https://github.com/DrKarpov/jury-analytics/tree/a34f0485c4166f6416ca26a8935291dfe26cca29), source 715abbbfe8c0b57cc71c4df1a004ec6353ae8d13. At anchor 1795796649: 623/623 mint receipts, 24,181 scanned account transactions, 419 linked accounts / 1,042 candidates, 219 completed linked chains, 7,567/12,371 internal sends matched, 4,804 unmatched sends and 3,843 unmatched inbound messages (separate, potentially overlapping scopes), 0 recorded account failures, traversal stopped at time budget. [Wallet status](https://github.com/DrKarpov/jury-analytics/blob/a34f0485c4166f6416ca26a8935291dfe26cca29/genesis/v1/wallet-history/status.json). Index cutoff 1795862828: 23,508 rows, 11,099 classified, 12,409 unclassified; 9,227 review traces out of 13,722. [Inventory](https://github.com/DrKarpov/jury-analytics/blob/a34f0485c4166f6416ca26a8935291dfe26cca29/inventory/v1/status.json). [Liquidity run](https://github.com/DrKarpov/jury-analytics/actions/runs/46137139638) success at workflow level, 240 profiles, 214 candidate traces, 68 attempts, 0 confirmations; 67 unsupported same-trace settlements and budget exhaustion. No trade integration. [CI](https://github.com/DrKarpov/jury-analytics/actions/runs/46137139556) and [Pages](https://github.com/DrKarpov/jury-analytics/actions/runs/46137173926) succeeded for that source. Stage 1 remains open.

Next implementation: reuse the freshly double-checked pinned tip for a single-transaction account only if predecessor LT is zero and all tip identity and chain checks pass. Other accounts and persisted partial chains still fetch both providers. Push/manual genesis runs can take two independently checkpointed wallet passes when mint receipts are already complete; cron stays at one. Regression tests added; speedup, new coverage and CI remain unverified until Actions finishes. No data facts, classifications or gates changed. Next check actual Actions and pinned wallet status; then investigate remaining edges, wallet master/owner binding, bounce and burn evidence. Full history and PnL are not certified.

## Offline StateInit diagnostic — implementation checkpoint

While genesis run [46137620539](https://github.com/DrKarpov/jury-analytics/actions/runs/46137620539) continues, Python/JS and genesis regression steps on 5c345a3 passed. Saved mint receipts contain dual-provider StateInit BOCs. Added a read-only diagnostic for ordinary level-zero BOCs: independently recompute representation hashes, compare provider roots, require the derived recipient address and observed historical code hash, then inspect the candidate zero-balance/owner/master data prefix. Unknown formats, mismatches and conflicting candidates remain unresolved. This is not verified owner binding or a balance ledger. The dedicated workflow reads the pinned checkout and produces a report artifact without a data-branch writer or API calls. Parser tests and real diagnostic results must be checked before any promotion. Full traversal remains stage 1 priority.
