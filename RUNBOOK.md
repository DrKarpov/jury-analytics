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
