# Эксплуатация JURY Analytics

## Контуры и данные

| Контур | Файлы |
| --- | --- |
| Обнаружение переводов и чекпойнты | `indexer.py`, `provider.py`, `incremental.py`, `recovery.yml` |
| Независимое сравнение и исправления | `current_audit.py`, `recovery.py`, `history-audit.yml`, существующие repair-модули |
| Сборка Pages | `persistent_preview.py`, `public_beta.py`, `pages.yml` |
| Проверка в браузере | `integrity.mjs`, `app.mjs`, IndexedDB |

`main` содержит код, `data` содержит seed, append-only batches и исходные доказательства. Временный runner восстанавливает состояние из этих файлов. Ключи `TONCENTER_API_KEY` и `TONAPI_API_KEY` опциональны и поступают через Actions Secrets. UI работает со статическими файлами Pages.

`current-audit/v1/batch-*.json` — последовательные наблюдения, связанные предыдущим SHA-256. Fingerprint включает нормализованные переводы, последние доступные действия Toncenter из patch, классифицированные события после overlays и unresolved evidence. Старые наблюдения сохраняются. Для отчёта учитываются только наблюдения с fingerprint текущего состояния. Наблюдение `match` означает равенство двух мультимножеств по стороне, владельцу, количеству JURY, котируемому активу и его точной сумме. Отдельный `matched_with_swaps` исключает совпадения пустых наборов. Трассы с `unavailable` повторяются после часа; бюджет распределяется между новыми, историческими и повторными запросами. Согласие индексаторов не доказывает фактический settlement, полноту discovery или пригодность для PnL.

`holders/daily/YYYY-MM-DD.json` хранит первое успешное наблюдение UTC-дня. Последнее успешное чтение и статус попытки обновляются как прежде в `holders/latest.json` и `holders/status.json`. Новые наблюдения требуют согласия Toncenter и TonAPI по эмиссии, равенства сумме положительных балансов и проверки 9 десятичных знаков. Архивные форматы без поля `decimals` продолжают читаться. Дневные наблюдения привязаны к интервалу чтения, точность на конкретный блок не заявляется.

Манифест `release.json` связывает cutoff, SHA-256 снимка и SHA-256 evidence. Браузер сверяет оба digest, валидирует данные и lineage до замены кеша. Тот же манифест допускает обновление страницы без повторной загрузки снимка. При HTML/JS из более нового релиза и отсутствующем манифесте предусмотрен переход через старый `snapshot.json`. Старые или повреждённые данные и несовпадение манифеста со снимком оставляют ранее проверенную версию.

## Проверка и восстановление

1. По [Actions](https://github.com/DrKarpov/jury-analytics/actions) сверить `event=schedule`, branch и вывод этапов с содержимым `data` и текущим `snapshot.json`. Использовать фактическое время cutoff. `workflow_dispatch` подходит для восстановления, но учитывается отдельно от cron. GitHub может задержать расписание и заменить ожидающий job общей concurrency-группы.
2. При сетевой ошибке проверить класс HTTP/transport и квоты. При несовпадении исторической строки остановить публикацию и сохранить доказательства для ревью. Для повреждённого batch проверить SHA, имя, предыдущий digest и последний валидный head. Восстановление ведётся из сохранённого Git ref в отдельный checkout. Обычный fast-forward push блокирует запись поверх конкурирующего коммита.
3. Pages собирает артефакт из pinned checkout двух веток. Проверки Python, JS и реального browser smoke обязательны. Перед deploy job повторно проверяет source/data SHA, чтобы ручной повтор старого job не опубликовал устаревший артефакт. При superseded build запускать новую сборку из актуальных refs. При невалидном build/deploy остаётся прошлый успешный релиз.
4. Для проверки восстановления из истории воспроизвести бета-артефакт из зафиксированных коммитов. Рабочая база, логи и raw repair evidence остаются в checkout данных. Git backup следует делать отдельным `git bundle` или mirror обеих веток в независимое хранилище. Политика retention и тест из внешнего backup остаются открыты.

```sh
git worktree add --detach ../jury-data-check bde145dae1afc55a2275c46adf553806f0ac792c
JURY_HISTORY_FIXTURES=../jury-data-check python3 -m unittest discover -s tests -v
node --test tests/*.test.mjs
out=$(mktemp -d)
python3 scripts/public_beta.py --store ../jury-data-check --out "$out" \
  --source-sha "$(git rev-parse HEAD)" --data-sha "$(git -C ../jury-data-check rev-parse HEAD)"
node tests/check_public_beta.mjs "$out"
python3 tests/persistent_browser_test.py "$out"
```

Последняя проверка требует Playwright Chromium. Payout regression с отдельными raw fixtures запускается в соответствующем Actions workflow.

## Генезис и полная история JURY

Контрольная точка `416731d` имеет cutoff 27 ноября 2026, 16:24:09 UTC. Toncenter и TonAPI подтвердили развёртывание мастера JURY 18 ноября 2026 в 09:15:28 UTC, LT `117446032000001`, tx `b6d564b65ad5b8aeb80821f30752da3d03393e2991a5c9ae269419a04a728481`. Самая ранняя запись текущего индекса переводов датируется 19 ноября, 10:59:24 UTC. История мастера включает пять исходящих сообщений JURY раньше этого перевода.

Сверка связала 809 транзакций мастера от развёртывания до его последней транзакции на cutoff по `prev_trans_lt` и `prev_trans_hash`. Оба провайдера согласились по 623 исходящим `jetton_internal_transfer`: 1 млн JURY из одного сообщения после opcode `0x642b7d07` и ещё 1 млн JURY из 622 сообщений после opcode `0x0bf470f5`. Старый отчёт lifecycle включал первую группу. Суммы подсчитаны по исходящим сообщениям. Для доказанного зачисления проверяется отдельная успешная транзакция получателя с тем же message hash и суммой.

```sh
python3 scripts/master_history.py --store /path/to/pinned-data --out /path/to/master-history.json \
  --receipts-dir /path/to/receipts --receipt-limit 20
```

Проверенные зачисления сохраняются отдельными файлами с digest и переиспользуются при следующем запуске. Перед подтверждением полной истории требуется пройти транзакционные цепочки jetton-кошельков со старейших известных зачислений, замыкать множество кошельков по фактическим доставкам, учитывать контракты с нулевым остатком и сравнивать конечные балансы и эмиссию на общей границе. Сопоставление истории мастера само по себе не подтверждает охват последующих переводов и сделок.

[Транзакция развёртывания в Tonviewer](https://tonviewer.com/transaction/b6d564b65ad5b8aeb80821f30752da3d03393e2991a5c9ae269419a04a728481)

### Persistent genesis recovery

The separate `genesis.yml` workflow reconstructs the master at the fixed historical cutoff 1795796649, independently of the changing beta cutoff. `genesis/v1/master.json` is immutable. Each successful receipt stores both provider responses and is revalidated by replay; failures remain pending and are revisited after unattempted messages. The first run reconstructs evidence not previously committed by Codex. No seed or trade metrics are changed. The next stage is account-chain traversal starting from these verified receipts. Schedule execution remains unproven.

`wallet_history.py` pins each account tip at the same genesis cutoff and persists ascending predecessor-linked pages under `genesis/v1/wallet-history/accounts`. It compares transaction identity, message hash/endpoints, state hashes and decoded relevant token amounts from both providers; root accounts come from independently replayed master receipts. Outgoing internal-transfer messages from linked accounts create candidates; a matching non-aborted recipient transaction is required before expanding the graph. Unmatched edges and provider disagreements remain explicit. This is not yet a token balance ledger, verified wallet code/owner binding, burn reconciliation or global completeness proof. Both workflows share a writer lock; scheduled execution still needs evidence.

`wallet_reconcile.py` checks master receipts against scanned account chains and compares matched internal message deliveries with the original transfer index by both endpoint transaction hashes and exact amounts. It records unmatched messages and possible missing or conflicting index records, without treating hash/amount agreement as owner identity or changing public trade metrics. Wallet traversal now alternates recipient frontier and root discovery, to avoid starving the former as new master receipts arrive.

The genesis workflow runs one bounded backfill round on schedule and up to two on push/manual execution when the prior receipt checkpoint has zero pending receipts. A newly pinned account with exactly one predecessor-linked transaction can reuse the independently compared tip row; multi-transaction or resumed accounts continue normal two-provider page fetching. Each round commits completed receipts, wallet pages and reconciliation separately; interrupted later stages do not erase prior commits. Primary discovery is attempted before and after backfill; current trace audit is attempted afterwards. These independent optional stages can fail without invalidating historical checkpoints; inspect each step, not only the overall workflow conclusion. Recipient targets with the most unresolved inbound edges take priority within their traversal slot. Pages rebuilds after successful genesis execution, retaining the superseded-artifact guard. This does not certify the historical timestamp as a common masterchain block or replace the final ledger acceptance gate.


`genesis/v1/wallet-history/reconciliation-status.json` is the signed compact summary of the full reconciliation file (linked by its digest). It partitions primary rows at the anchor into hash/amount matched endpoints, other observed hashes and hashes not yet observed on linked chains; these are discovery diagnostics, not transfer classification. Gap reasons examine all scanned accounts, including unlinked and failed transactions, without extending the verified graph. Mint receipt census separates observed rows from unscanned and conflicting rows. A test-only source change also triggers Pages validation; freshness guard remains in force.


StateInit diagnostics: `wallet_stateinit.py` distinguishes the full Toncenter StateInit root hash (including explicit fixed_prefix_length=8) from the unprefixed code/data comparison hash used by TonAPI. It checks the full declared hash, the remaining 248 address bits and observed owner shard prefix, as well as historical code and JURY master data prefix; unknown encodings remain unresolved. `wallet-stateinit.yml` and `wallet-identity.yml` produce read-only diagnostic artifacts; their workflow success alone does not imply successful matches. Refer to logs and pinned refs in PROGRESS.md. No historic owner binding is automatically installed.

The StateInit workflow also runs `wallet_deployment.py` on linked non-mint accounts. It re-fetches a bounded sample of activation transactions by inbound message hash, replays normalized historical rows exactly, applies StateInit checks, and reports code observation gaps across saved chain rows. The diagnostic artifact contains raw successful observations and unresolved reasons; it is not yet a persistent incremental proof store. No data-branch write occurs. To continue, use the latest actual run and pinned refs, then add append-only replayable capture rather than rerun the same sample indefinitely.

Linked activation diagnostics retain raw failed and successful captures in the report and may retry the same historical LT through the account endpoints if message endpoint replay fails. Each attempt independently must replay the saved normalized row and pass StateInit checks, and missing historical code remains unresolved. The report is a bounded diagnostic, not a permanent evidence database.

Persistent linked deployment evidence is now written by the genesis workflow after historical traversal, under its existing writer lock. `genesis/v1/wallet-deployment/observations/*.json` are immutable signed records, tied to the original activation row and tip digest. Successful records replay exact raw proof; missing-code blockers replay rejection and are not verified identities. Other failures remain retryable. `status.json` distinguishes cumulative saved matches, blockers, and remaining activation candidates. Old read-only diagnostic artifacts are not automatically imported; first persistent pass recaptures evidence. The optional stage is bounded to 80 seconds of network budget and does not prevent subsequent primary discovery; check actual step conclusion and checkpoint, not only overall workflow status.

## Обязательный контроль эксплуатации

См. [ARCHITECTURE.md](ARCHITECTURE.md). До финальной приёмки требуется единый исторический/live pipeline, независимый discovery, отдельные watermarks для discovery/verification/publication, измерение реальных cron запусков и backlog age, тесты отказов/late arrivals/replay/restore, минимум 72 часа автономного наблюдения и проверка фактической пропускной способности и стоимости инфраструктуры. Не считать workflow success подтверждением покрытия. Текущие процедуры выше описывают бету, а не завершённую архитектуру.

`canonical_movements.py` and `continuation_shadow.py` are read-only shadow checks. The latter captures raw two-provider account tips/pages at a timestamp cap after the historical anchor, verifies the prior chain and replays them through the same normalized graph projection. It samples complete existing linked accounts, does not yet advance the production cursor, discover all new accounts, or certify a common finalized block boundary. Inspect actual report counts and failure reasons rather than workflow success alone.

`continuation/v1/accounts/<wallet>/page-*.json` holds immutable signed raw continuation envelopes. The `continuation_store.py` optional recovery step replays them against the completed historical prefix and previous record digest, prioritizes unfinished target and least recently checked accounts, retries recorded failures after 600 seconds, and writes a compact `continuation/v1/status.json`. It does not update public metrics. Inspect `accounts_reached_current_target` separately from cumulative accounts/rows; target is a primary timestamp, not common finalized block. A first successful pass does not demonstrate actual scheduled cadence, repeat catch-up or new-wallet discovery.

Continuation scheduling now interleaves refresh and first-time capture rather than starving previously saved accounts; unfinished pages first in the refresh lane. `continuation/v1/frontier.json` lists unmatched successful post-anchor internal messages observed in the sampled linked graph with peer discovery state, and its digest is included in status. Peers absent from historical graph are candidates only, not proven newly deployed wallets. Inspect `replayed_previous_envelopes`, `resumed_accounts_this_run`, `resumed_rows_this_run` and target coverage separately; a resumed unchanged tip is not a new transaction. This remains shadow, with independent block/master/new-account discovery still required.

`continuation/v1/counterparts/<side>-<message>.json` stores isolated raw two-provider opposite endpoint observations, validated against the original saved normalized endpoint. `counterpart-status.json` measures current frontier coverage separately from cumulative evidence and `counterpart-pending.json` records retryable failures. These are discovery evidence only, not full account chains or public metrics; the recovery job has an optional bounded 80-second provider stage and shared writer lock. Verify actual step and saved checkpoint.

`continuation/v1/peer-prefixes/<wallet>/page-*.json` is immutable raw predecessor evidence pinned to a previously validated counterpart transaction. `peer-status.json` reports complete prefixes, initial StateInit matches, explicit blockers and isolated projection results; `peer-pending.json` stores retryable capture failures. The stage does not install new production owner bindings or balances. A complete prefix ends at the evidence transaction, not necessarily current account tip. Future continuation and global discovery remain required.

`continuation/v1/master/base.json`, `pages/page-*.json`, and `receipts/*.json` are immutable raw evidence for master continuation. The legacy anchor row must match both raw providers before accepting subsequent shared-cursor pages. `status.json` records target reached, new rows, token opcode observations, confirmed recipient deliveries and unresolved cases; `pending.json` records retryable receipt failures. These are observations, not mint/burn/supply conclusions or public graph roots. The optional recovery stage is bounded to 55 seconds of network budget; overall timeout now 22 min, not a measured run duration. Verify schedule history and actual stage results separately.

`continuation/v1/peer-accounts/<wallet>/page-*.json` contains immutable raw shared-cursor extensions of identity-supported counterpart prefixes that end after anchor. `unified-status.json` binds the combined replay counts/digest, master root candidates, peer cursor coverage and conflicts; `unified-frontier.json` contains unmatched messages in that combined graph. Neither is consumed by public analytics; the existing counterpart acquisition still reads the legacy frontier until dependency-ordered integration is completed. Master receipt roots without rows remain explicit. Verify real stage, not just green workflow; total recovery timeout is 24 minutes, not observed runtime.

`live_pipeline.py` runs the existing five shadow stages in dependency order, validates current target/master and cross-stage evidence counts/digests, then checkpoints each stage separately. Fatal process or integrity failure stops dependent stages, retains already committed evidence and writes `live-pipeline-stage-report` artifact. Bounded pending failures/stop reasons are reported as degraded, not silently certified. On full execution `continuation/v1/pipeline-status.json` records operational outcomes, source/data refs and timing. Failed run artifacts supersede older successful operational status for monitoring. This is not completeness, balance or schedule acceptance. Recovery job timeout 18 minutes; actual run time must be measured independently.

`block_pilot.py` is a read-only, bounded feasibility workflow. It selects two adjacent masterchain intervals around saved post-anchor observations and independently enumerates provider pages, checks duplicate IDs, primary mc sequence, common transaction identity, terminal pages and saved-row overlap. `independent-block-pilot` artifact contains compressed raw responses and signed report; no data-branch cursor or publication is changed. Generic Jetton opcodes and wallet code are discovery hints, not JURY identity. Incomplete/mismatched enumeration is a measured result, not successful global coverage; inspect the report rather than workflow conclusion.

`continuation/v1/ledger-status.json` is a compact derived shadow journal report produced within unified replay and checked by live_pipeline. Its historical and combined summaries include journal/exception/wallet-net digests; full deterministic postings can be regenerated using delivery_journal.build on the same pinned compared inputs. Master distributions are observed source postings, not asserted issuance; unmatched deliveries, burns, failures and negative partial nets are not verified balances. No PnL or public metrics consume this report. Inspect actual DELIVERY JOURNAL log and digest binding after each run.

`continuation/v1/ledger-repair.json` contains diagnostic unresolved message routes and partial-negative-net accounts, bound by digest to ledger and unified status. No inferred balance repair. Regular continuation prioritizes eligible missing peers from freshly replayed legacy post-anchor frontier for at most half the slots, honoring backoff and ordinary refresh/discovery. Inspect `prior_frontier_edges_closed`, `new_frontier_edges`, and `selected_accounts_with_frontier_messages` separately (last includes ordinary slots too). Historical and unified-only unresolved routes remain diagnostic until acquisition integration is verified.

Historical traversal reads the last coherent signed ledger repair/ledger/unified report when present. Exact current unresolved inbound identity and incomplete peer eligibility gate its focus lane (one in three successful-page slots). Regular continuation prioritizes eligible negative-net missing senders not yet covered through receipt time within its existing half-budget focus lane. Inspect historical matched hints and live selected accounts. No public metric changes.
