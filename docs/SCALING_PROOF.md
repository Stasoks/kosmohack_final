# Доказательство детерминированного масштабирования

Проверка отвечает на один вопрос: приводит ли одна и та же физическая история событий к одному бизнес-состоянию при разном числе конкурентных отправителей и outbox workers.

## Профили

- `configs/scaling/smoke.json`: 100 изделий, запуск `1 vs 2` отправителя. Этот профиль предназначен для CI.
- `configs/scaling/standard.json`: 1000 изделий, запуск `1 vs 4` отправителя. Это локальная полная проверка, а не обязательный benchmark каждого push.

Скрипт один раз создаёт `load.jsonl`, фиксирует SHA-256 и повторно использует именно этот файл во всех A/B запусках. Параметр `--concurrency` означает число клиентских отправителей, а не число backend workers.

```bash
python scripts/scaling_proof.py \
  --profile configs/scaling/smoke.json \
  --concurrency 1,2 \
  --outbox-workers 1,2 \
  --recovery

python scripts/scaling_proof.py \
  --profile configs/scaling/standard.json \
  --concurrency 1,4 \
  --outbox-workers 1,4 \
  --recovery
```

Нужны мигрированная изолированная PostgreSQL БД, выполненный seed, `DEMO_MODE=true`, `SOURCE_DEMO_TOKEN` и `DEMO_PRIVILEGED_DATABASE_URL`. Скрипт очищает только demo/business tables между A/B прогонами. Запускать его против производственной БД нельзя.

## Что входит в canonical snapshot

Snapshot включает `Item`, `OperationRun`, `Observation`, `DefectOccurrence`, `Nonconformance`, версии и доказательства анализа, решения, `ProjectionState`, outbox и integration messages. Случайные DB UUID заменяются бизнес-связями: event ID, item ID, operation run ID и identity физического дефекта. Времена событий, доверие, дефект/компонент, состояния NCR, Birth Window, rework и release сохраняются.

Исключены только технически volatile значения: wall-clock timestamps создания/пересчёта, heartbeat, request/session IDs и глобальные ingest sequence counters. Для `ProjectionState` сохраняются status, наличие ошибки и признак `latest == projected`; это позволяет сравнить результат при другом порядке конкурентных commit.

Отдельный KPI hash строится штатной функцией analytics API с удалением только `calculated_at`/`recalculated_at`.

## Критерии PASS

- SHA-256 physical dataset совпадает во всех запусках;
- число уникальных raw events совпадает;
- projection hash и KPI hash совпадают;
- projection failures и backlog равны нулю;
- дубликаты доставки не увеличивают KPI;
- повторная пересборка неизменной истории сохраняет projection hash;
- 1 и N outbox workers доставляют каждый `message_id` один раз;
- после остановки backlog сохраняется, затем полностью дренируется с теми же `message_id`;
- нет invalid ACK alerts.

Throughput и p95 измеряются и попадают в JSON/Markdown отчёты, но линейное ускорение не является критерием PASS. По умолчанию отчёты записываются в `tmp/scaling-proof/`.
