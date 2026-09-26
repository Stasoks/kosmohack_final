# Оперативный dashboard качества

Верхняя часть вкладки Streamlit **«Обзор»** для пользователей с правом
`VIEW_ANALYTICS` показывает read-only снимок качества производства. Это near-real-time
интерфейс с polling каждые 2 секунды, а не streaming, WebSocket или отдельный source of
truth.

Поток данных остаётся прежним:

```text
Streamlit -> GET /api/v1/analytics/live-quality -> FastAPI -> PostgreSQL projections
```

Dashboard не записывает данные, не читает зашифрованный raw payload и не меняет Trust,
Birth Window, NCR, rework или release semantics.

## API

```http
GET /api/v1/analytics/live-quality?window=1h
```

Endpoint требует `VIEW_ANALYTICS`. Допустимые окна: `15m`, `1h` (по умолчанию), `24h`
и `all`. Для ограниченных окон business-time граница применяется по
`Observation.occurred_at`; поздно доставленная проверка поэтому остаётся в своём
историческом bucket.

- **Проверено** — уникальные изделия хотя бы с одним observation в окне.
- **GOOD** — уникальные изделия с `TRUSTED` результатом `no_defect`. Это результат
  контроля в пределах его фактического inspection scope, а не автоматический выпуск и
  не доказательство отсутствия дефектов вне этого scope.
- **Сигналы дефекта** — уникальные изделия с `TRUSTED` результатом
  `defect_detected`. Сигнал не равен подтверждённому NCR.
- **Подтверждённые NCR** — только NCR с human verdict `confirmed`.
- **Ожидают решения** — NCR с текущим verdict `pending_review`.
- **На доработке** и **Выпущено** берутся из текущих canonical disposition/item states
  для изделий, попавших в выбранное окно.
- **FPY** использует ту же формулу, что `/api/v1/analytics/kpi`: доля оценимых
  проверенных изделий без подтверждённого NCR. Для live endpoint меняется только
  временной scope набора изделий.

Station aggregation показывает место обнаружения сигнала через
`Observation -> OperationRun -> station_id`. Это не root-cause attribution. Machine
warnings получаются отдельно из `MachineEvent`; предупреждение не является дефектом и
не доказывает его причину.

## Timeline и производительность

- `15m`: минутные buckets;
- `1h`: 5-минутные buckets;
- `24h`: часовые buckets;
- `all`: дневные buckets, максимум 90 последних представленных дней.

Counts и группировки выполняются SQL aggregates. Recent activity собирается только из
projection/business entities и ограничена 20 строками. Endpoint не имеет write side
effects и не использует cache/Redis; при существенно больших production volumes может
понадобиться materialized aggregate или короткоживущий cache после измерений.

Если polling-запрос временно недоступен, fragment показывает локальное сообщение
**«Оперативный мониторинг временно недоступен.»**. Остальные таблицы Overview продолжают
работать и не перезапускаются вместе с fragment.
