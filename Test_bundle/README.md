# TRACE-Q test data bundle

Этот набор подготовлен под текущую архитектуру TRACE-Q.

## Как устроен bundle

Каждый обычный сценарий находится в:

```text
scenarios/Sxx_.../
```

и содержит минимум:

```text
scenario.json   — что тестируем и зачем
events.jsonl    — входной поток событий
expected.json   — ожидаемое поведение системы
```

В некоторых сценариях дополнительно есть:

```text
actions.json          — действия контролёра/пользователя через application API
requests.json         — transport/security requests
erp_behavior.json     — поведение ERP Emulator
tamper_actions.json   — test-only действия для integrity demo
analysis_request.json — P1-запрос, например Blast Radius
```

`events.jsonl` выбран потому, что TRACE-Q принимает поток независимых structured events. Каждая строка — валидный JSON event.

---

## Важная семантика времени

**Порядок строк в `events.jsonl` = порядок доставки.**

`occurred_at` = время события на производстве.

`received_at` специально отсутствует: его должна назначить сама TRACE-Q при приёме.

Поэтому, например, в late-event scenario последняя строка файла может иметь `occurred_at`, который раньше уже обработанного DEFECT. Это намеренно.

---

## С чего начать команде

### Сначала P0

1. S01 — normal.
2. S03 — bounded defect + machine warning.
3. S04 — poor GOOD.
4. S05 — missing required inspection.
5. S06 — duplicate.
6. S07 — late event.
7. S10 — conflict.
8. S08 — rework success.
9. S16 — rework failure.
10. S19 — ERP outage.
11. S22 — RBAC/Controlled Release.
12. S09 — tamper.

### Затем P1

- S17 — Evidence Invalidation.
- S18 — Blast Radius.

### Отдельно

- `invalid_inputs/` — schema/semantic/version ошибки.
- S25 — KPI.
- `load/load_profile.json` — нагрузочное тестирование.

---

## Что проверяет каждый сценарий

| ID | Что тестируем |
|---|---|
| S01 | normal workflow, trusted GOOD, no false NCR |
| S02 | incoming defect, LEFT_OPEN |
| S03 | bounded Birth Window, warning = context, not cause |
| S04 | poor-quality GOOD не является trusted boundary |
| S05 | missing required inspection → MISSING_CHECK |
| S06 | duplicate idempotency |
| S07 | late event → new AnalysisVersion и более точное окно |
| S08 | controller + successful rework + release |
| S09 | tamper detection |
| S10 | conflicting Vision sources |
| S11 | no previous trusted inspection |
| S12 | multiple defect types in one observation |
| S13 | impossible_to_assess |
| S14 | same event_id + changed payload |
| S15 | out-of-order delivery |
| S16 | rework failure, same defect stays open |
| S17 | calibration/evidence invalidation |
| S18 | Blast Radius proposal |
| S19 | ERP outage + outbox retry |
| S20 | unknown source rejected |
| S21 | replay vs legitimate duplicate retry |
| S22 | RBAC + Controlled Release Gate |
| S23 | no KOMPAS/product structure fallback |
| S24 | immutable route revisions |
| S25 | KPI counting |

---

## Что НЕ надо сравнивать побайтно

`expected.json` описывает **бизнес-инварианты**. Например:

```json
{
  "root_cause_status": "not_established"
}
```

важнее, чем конкретный ID строки БД.

Команда может написать Scenario Runner, который переводит фактическое состояние приложения в небольшой normalized result и сравнивает именно его с `expected.json`.

---

## Test fixture auth

`config/test_source_secrets.json` содержит исключительно тестовые секреты.

S21 использует тестовую схему:

```text
HMAC-SHA256(
  secret,
  timestamp + "\n" + nonce + "\n" + canonical_json(body)
)
```

Это **fixture protocol**, а не требование к production authentication.

Production implementation может заменить его на mTLS / HTTP Message Signatures, сохранив смысл теста.

---

## Важные правила для команды

- Не менять fixture так, чтобы тест начал проходить: при изменении бизнес-правила сначала договориться, затем изменить expected и документировать причину.
- Все timestamps — UTC.
- Повторный delivery одного события не должен менять KPI.
- `machine warning` не должен автоматически становиться `confirmed cause`.
- `impossible_to_assess` не является GOOD.
- Rework не удаляет исходный confirmed NCR.
- Blast Radius не делает соседние изделия дефектными.
- Незарегистрированный source не должен создать RawEvent.
- Admin не должен автоматически уметь принимать QC decision.

---

## Рекомендуемая автоматизация

Один и тот же fixture должен использоваться:
- в pytest;
- в Scenario Runner;
- в demo.

Это исключит ситуацию, когда demo data и реальные тесты проверяют разные правила.
