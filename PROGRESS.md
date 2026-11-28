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
