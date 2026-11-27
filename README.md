# JURY Analytics — P4 (persistent history, unpublished preview)

**Current status:** The public repository and dedicated `data` branch exist. The seed history has been recovered from the completed primary collection; independent audit is ongoing and differences require investigation. The incremental workflow appends validated segments and saves audit batches every 15 minutes, independent of visitors. Full re-indexing is manual only. The separate persistent preview workflow builds from a pinned data checkout, checks its integrity with JavaScript and opens the actual snapshot in Chromium. It does not deploy GitHub Pages. Seed audit results are explicitly scoped to the seed, not the current candidate. Holder and lifecycle evidence is not carried forward to an unrelated snapshot; PnL remains blocked until sufficient verification. No runtime AI/MCP or external server required.

The sections below document earlier implementation stages; statements about missing repositories or unavailable live data describe those earlier stages, not the current state.

Независимая ончейн-аналитика JURY. Архитектурный референс — Pepegun Analytics, но отдельная модель данных и интерфейс. Целевая публикация: GitHub Pages (`docs/`). В этой версии нет ИИ, MCP, Wallet Agent, npm-зависимостей, браузерных API-ключей или обязательного постоянно работающего сервера. Источник блокчейна — публичный Toncenter v3 (опциональный API-ключ только для сборщика). Python 3.10+ и Node.js 22 для тестов.

## Запуск на тестовом сервере

```sh
python3 -m unittest discover -s tests -v
node tests/analytics.test.mjs
node tests/wallets.test.mjs
python3 scripts/staging.py --full
# При несовпадении аудит может завершиться кодом 2, диагностические файлы сохраняются.
python3 scripts/preview.py
python3 -m http.server 8000 --bind 127.0.0.1 --directory data/preview
```

Если требуется ключ, задайте переменную окружения `TONCENTER_API_KEY`. Сервер отдаёт только подготовленный каталог `data/preview/` (или `docs/` для пустого публичного каркаса). Не публикуйте SQLite, ключи или рабочие файлы. Для публичного тестового сервера используйте TLS и штатный reverse proxy. Сборщик повторно запускается той же командой; состояние хранится в `data/index.sqlite`. `--full` перепроверяет историю от начала. При ошибке предыдущий snapshot не заменяется. На текущем этапе публичный репозиторий не создан и Pages не развёрнут.

## P2: отдельный проверочный прогон

`python3 scripts/staging.py --full` записывает только `data/staging/`, не `docs/`:

- `candidate.json` — история классифицированных операций и отдельный массив `transfers` со всеми обнаруженными строками переводов (включая отменённые). Не является доказательством получения средств получателем.
- `swap-audit.json` — независимое сравнение свапов в обнаруженных трейcах с TonAPI: мультимножество направления, адреса владельца, актива и двух точных сумм. Проверяются и трейсы без первичных свапов. Не доказывает полноту глобальной истории, согласие не равнозначно проверке сырых сообщений блокчейна. Идентификаторы событий должны совпасть; несовпадение идентификатора, отсутствие сети или незавершённый event не засчитываются как совпадение. `--max-traces N` ограничивает проверку для диагностики, не для утверждения полноты.
- `holders.json` — текущие положительные балансы, только если два чтения Toncenter совпадают с TonAPI по кошельку, владельцу и балансу, а сумма равна заявленной эмиссии TonAPI. Это наблюдение за интервал времени, не точный блок или исторический баланс; адреса включают контракты, не только людей. При движении рынка проверка может закономерно не пройти. Не используются данные о переводах для восстановления баланса.
- `lifecycle.json` — распознанные действия mint по master и строки burn по master, включая признаки неуспешности. Не доказанная полная история эмиссии, не используется для расчёта балансов.
- `liquidity.json` — отдельно выделенные LP-депозиты, выводы и refunds по успешному действию и совпадающему переводу, неоднозначные операции выделены отдельно. Это диагностические данные, не окончательное разрешение всех маршрутов и не торговый оборот.

Два полных чтения фиксированного временного окна должны совпасть. Это не эквивалент фиксированному блоку. Аудит не изменяет опубликованный снимок. Workflow `Staging index` сохраняет диагностические JSON как артефакт даже при неуспехе. `TONAPI_API_KEY` и `TONCENTER_API_KEY` опциональны, только на сервере. Файлы проверочного прогона интегрируются в отдельный предварительный UI командой `scripts/preview.py`; автоматическая публикация по-прежнему запрещена. Реальные ответы обоих API ещё не доступны из среды разработки. Для повторной проверки полного прогона с изменившейся историей используйте новый диагностический SQLite-файл, не перезаписывая старую базу.

## P3: аналитика кошельков и отдельный preview

- `docs/wallets.mjs` — независимые расчёты на BigInt: чистые покупки/продажи, потоки по наблюдаемым сообщениям, расходы/поступления GRAM, средневзвешенная цена в парах с GRAM, концентрация актуальных держателей, связи по однозначным прямым переводам. Проверка CRC16 адресов EQ/UQ, raw-адреса тоже поддерживаются.
- `docs/wallet-ui.mjs` — разделы держателей, рейтинга чистых покупок/продаж (по 10 лидеров каждого направления), аналитики введённого адреса, связей (20 крупнейших направленных пар), LP и эмиссии. Торговые метрики и потоки относятся к глобальному переключателю периода; держатели — отдельное наблюдение с датой. GRAM-поток не является PnL; средние цены не учитывают газ, комиссии и стоимость поступивших вне покупки токенов. Связь адресов не доказывает общего владельца. Положительные держатели включают пулы и контракты, пока их роли не верифицированы. Концентрация считается от текущей эмиссии, а не от free float.
- `scripts/preview.py` — проверка digest исходного кандидата, привязка всех файлов доказательств к одному кандидату и проверка суммы/уникальности держателей. Создаёт отдельную копию фронтенда и снимка в `data/preview/`, не в `docs/`. Это локальная проверка идентичности артефактов, не криптографическое доказательство цепи. Диагностический preview явно отмечен как неопубликованный и показывает статус сверки. Даже успешная сверка не снимает ограничений полноты.
- По умолчанию `scripts/indexer.py` пишет `data/candidate.json`; запись в `docs/` запрещена. Сбор через Actions сохраняет JSON и отдельный preview как артефакт; никакой автоматической публикации или внешнего запуска пока нет.
- CI дополнительно запускает `tests/wallets.test.mjs`, `tests/test_preview.py` (в составе unittest) и Chromium browser test на шести ширинах. Playwright используется только для разработки, не в runtime. Локально браузерный тест заблокирован политикой среды (ERR_BLOCKED_BY_ADMINISTRATOR), а живые запросы — DNS.

## Модули

- `scripts/provider.py` — HTTP, rate limit, проверка адресов и transfer-строк.
- `scripts/indexer.py` — глобальная выборка переводов по master, загрузка действий по trace, SQLite, точные целочисленные суммы, overlap 1 час, проверка неизменности уже записанных строк, SHA-256 и атомарное сохранение.
- `docs/analytics.mjs` — единый период, агрегаты с BigInt, форматирование, CSV.
- `docs/app.mjs` — RU/EN, адаптивный интерфейс, фильтр операций, SVG-график по UTC-дням, рейтинг торговых адресов по объёму JURY, обновление snapshot каждые 15 минут при открытой вкладке.
- `docs/snapshot.json` — начальный пустой снимок с состоянием `not_indexed`; тестовые сделки в него не входят.
- `.github/workflows/ci.yml` — тесты кода; `.github/workflows/staging-index.yml` — ручной сбор и аудит данных в отдельный артефакт без публикации. CI и сбор раздельны.

## Определения и ограничения P1

Покупка/продажа — успешное распознанное индексатором действие swap, где JURY является конечным входным или выходным активом и присутствует единственный соответствующий неотменённый transfer по сумме и адресу. Это не самостоятельный декодер DEX и не доказательство финального расчёта. Неизвестные маршруты не угадываются, нераспознанные трейсы показываются отдельно. Внутренние peer legs не считаются отдельными пользовательскими сделками. Несколько action, претендующих на один transfer, исключаются. Обычный перевод учитывается только при однозначном standalone действии. Цифры P1 могут недосчитывать операции. GRAM volume — сумма только нативных GRAM-сторон классифицированных свапов; обмены на другие jetton не включены. Адреса не равны людям. Чистый торговый поток не равен изменению баланса. CSV содержит классифицированные действия выбранного периода, а не нераспознанные трейсы. Все суммы хранятся в nano-unit, CSV сохраняет их полностью. Периоды UTC, привязаны к cutoff снимка, 7d/30d — скользящие окна. 

Сверка внутри одного провайдера не доказывает полноту: пагинация по offset и запаздывание индексатора требуют дополнительной проверки. Неожиданные изменения истории блокируют обновление; автоматический repair не реализован. Фиксация cutoff по времени не равна masterchain anchor. Из-за DNS в текущем окружении live запросы к Toncenter и TonAPI не прошли. Форматы действий основаны на документации, не проверены на реальных ответах JURY. До внешнего теста и независимой сверки публиковать как достоверную статистику нельзя. 

## Следующие этапы

P2: живой прогон с публичными API, измерение полноты, сверка TonAPI и Toncenter по traces, декодирование/проверка DEX (STON.fi, DeDust и фактически обнаруженные площадки), неоднозначные маршруты, LP, mint, burn, refunds, holders и контроль эмиссии. Подтверждение исторического anchor, сверка snapshots, восстановление после изменений источника. P3: базовые holder analytics, концентрация и wallet connections реализованы в staging preview. Остались проверка ролей адресов, исторические балансы, cost basis и PnL (с явно неизвестной стоимостью входящих переводов). P4: расширенный UI (графики с взаимодействием, PNG, IndexedDB), браузерные тесты Chromium/WebKit, проверка мобильного Safari, защищённая автоматическая публикация Pages, отдельный data refresh.

## Источники схем

- https://docs.ton.org/api/v3/action-types
- https://docs.ton.org/ecosystem/api/toncenter/v3/actions-and-traces/get-actions
- https://docs.ton.org/ecosystem/api/toncenter/v3/jettons/get-jetton-transfers
- https://pkg.go.dev/github.com/toncenter/ton-indexer/ton-index-go/index/models
- https://github.com/DrKarpov/pepegun-analytics/blob/main/README.md

Дополнительные источники P2:
- https://github.com/toncenter/ton-indexer/blob/master/ton-index-go/index/models/actions.go
- https://github.com/toncenter/ton-indexer/blob/master/ton-index-go/index/models/jetton.go
- https://github.com/tonkeeper/opentonapi/blob/master/api/openapi.yml
- https://docs.ton.org/api/v3/jettons/get-jetton-wallets

## P3.1 — integrity and provisional FIFO

- `docs/integrity.mjs` validates the JURY master, canonical candidate SHA-256 (same as Python), transfer/action identities, raw transfer mapping, trace count, and the separate evidence digest. Digests detect corruption; they are not signatures or blockchain proofs. Existing P3 staging artifacts must be reassembled using the P3.1 preview script to include the evidence digest.
- IndexedDB caches the last validated candidate per origin/path. Failed refresh, damaged data, historical row modification/deletion, late historical transfer or cutoff rollback do not silently replace a known candidate. The UI displays a fallback warning. Clearing browser site data resets the local anchor; investigate provider corrections before doing this. Existing classified actions are immutable in automatic refresh. No cache is required for use; if unavailable the current validated response is used. Staging remains explicitly unpublished.
- `docs/cost-basis.mjs` calculates an **experimental gross FIFO estimate**, only for a wallet whose observed history consists exclusively of matching GRAM endpoint trades, whose discovered traces pass the swap audit, which has no observed mint/burn/LP movements, whose cost inventory never becomes negative or has ambiguous intra-second ordering, and whose computed residual matches the holder observation. Costs are allocated with exact integer arithmetic and cumulative remainder conservation. Acquisition history is considered from inception; realized results are selected by sale date; remaining inventory/cost is as of period end. Unknown transfers, non-GRAM swaps, or incomplete audit make this estimate unavailable. It is not proof of complete wallet history or net profit; network fees excluded, holder observation is not block-pinned. Unrealized PnL and transferred cost basis are not implemented.
- CI runs new integrity/FIFO unit tests; browser scenarios include checksum-failure cache fallback. Actual live indexing and browser acceptance are still blocked in the current environment. No data or code is automatically published.

### Reproduce locally

```sh
python3 -m unittest discover -s tests -v
for f in tests/*.test.mjs; do node "$f" || exit; done
for f in docs/*.mjs; do node --check "$f" || exit; done
# Network-enabled staging host only:
python3 scripts/staging.py --full
python3 scripts/preview.py
python3 -m http.server 8000 --directory data/preview
```

The staging command may return nonzero for audit differences; inspect the evidence before previewing. The GitHub Actions workflow handles an unpublished candidate separately. Do not merge an unverified candidate into `docs/`.
