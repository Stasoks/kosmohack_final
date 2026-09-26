# TRACE-Q — подробная документация решения

> TRACE-Q — MVP интеллектуального контроля качества и прослеживаемости изделий для закрытого промышленного контура. Система объединяет результаты контроля, производственные события, действия операторов и состояние оборудования в единую доказуемую историю изделия, помогает локализовать интервал возникновения несоответствия и доводит его до решения уполномоченного контролёра.

## 1. Задача проекта

Кейс посвящён контролю качества деталей в космической отрасли в условиях закрытого производства, ограниченности доступных данных и высокой критичности брака. TRACE-Q решает не узкую задачу «обучить CV-модель», а полный производственный процесс вокруг результатов контроля:

```text
источники производства
→ приём и проверка событий
→ защищённая исходная история
→ текущее состояние изделия
→ оценка доверия к наблюдениям
→ сигнал дефекта
→ локализация интервала возникновения
→ карточка несоответствия
→ решение контролёра
→ доработка / повторный контроль
→ выпуск или иное итоговое решение
→ внешняя система
→ аналитика и аудит
```

Входом TRACE-Q являются структурированные результаты уже выполненного контроля. Внешний VisionQC может прислать результат `no_defect`, `defect_detected` или `impossible_to_assess`, качество наблюдения, confidence, область контроля, идентификаторы изделия/операции/контрольной точки и ссылки на доказательные материалы.

Собственная промышленная CV-модель в MVP не заявляется. Проект комплекса «камеры + ИИ» описывается как архитектурная часть и набор проектных предположений, которые требуют проверки на реальном производстве.

## 2. Архитектура TRACE-Q

TRACE-Q реализован как событийно-ориентированный модульный монолит с отдельными deployable-компонентами:

```text
┌───────────────┐
│    Browser    │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│   Streamlit   │
│      UI       │
└───────┬───────┘
        │ HTTP/JWT
        ▼
┌────────────────────────────────────┐
│              FastAPI               │
│ auth / ingestion / projections     │
│ quality / routes / analytics       │
│ integrations / security / admin    │
└───────────────┬────────────────────┘
                │ SQLAlchemy
                ▼
┌────────────────────────────────────┐
│          PostgreSQL 16             │
│ encrypted raw history              │
│ rebuildable projections            │
│ NCR / decisions / analysis         │
│ audit / outbox / security state    │
└───────────────┬────────────────────┘
                │ FOR UPDATE SKIP LOCKED
                ▼
┌────────────────────┐      HTTP      ┌──────────────────┐
│   Outbox worker    │ ─────────────▶ │   ERP Emulator   │
└────────────────────┘                └──────────────────┘

Demo-only:
┌────────────────────┐
│ Factory Simulator  │ ── canonical events ──▶ FastAPI
└────────────────────┘
```

Streamlit никогда не подключается напрямую к PostgreSQL. Аутентификация, RBAC, event validation, replay, решения, audit и integrity enforcement находятся на backend/DB boundary.

### Почему модульный монолит

Для MVP микросервис на каждую бизнес-функцию создал бы лишнюю распределённую сложность. При этом границы сохранены:

- `domain` и `quality` содержат бизнес-правила;
- `ingestion` отвечает за приём внешних событий;
- `projections` отвечает за deterministic replay;
- `integrations` содержит бизнес-порты и adapters;
- `security` отвечает за auth, crypto, RBAC и audit;
- UI работает только через API;
- Outbox worker вынесен в отдельный процесс;
- Factory Simulator работает через публичные API, а не через БД.

## 3. Ключевые принципы

### 3.1. Исходная история отдельно от текущего состояния

Принятые производственные события сохраняются как исходные факты и не переписываются при пересчёте бизнес-состояния.

Проекции (`Item`, `OperationRun`, `Observation` и др.) являются rebuildable state и могут быть детерминированно восстановлены из исходной истории.

### 3.2. Observation ≠ NCR

TRACE-Q намеренно разделяет:

```text
Observation
≠
DefectOccurrence
≠
Nonconformance
≠
ControllerDecision
```

Сигнал дефекта от системы контроля не равен автоматически подтверждённому физическому дефекту и не является итоговым решением по изделию.

### 3.3. Корреляция не объявляется причиной

Событие оборудования рядом по времени с дефектом используется как контекст расследования, но система не делает автоматический вывод `machine warning → machine caused defect`.

Причина может иметь статус:

```text
not_established
candidate
confirmed_by_human
```

### 3.4. Решение человека остаётся финальным

Финальный verdict/disposition по NCR принимает уполномоченный контролёр.

### 3.5. Плохие данные не превращаются в GOOD

Пропущенное измерение становится limitation. Сомнительное измерение может сохраняться в истории, но не использоваться как trusted boundary.

### 3.6. Late events допустимы

События могут приходить позже своего `occurred_at`. TRACE-Q пересобирает состояние детерминированно и создаёт новую версию анализа, не переписывая старую.

## 4. Слои данных и доменная модель

| Уровень | Примеры | Правило |
|---|---|---|
| Исходные факты | `RawEvent`, `IngestAttempt` | accepted raw events append-only и зашифрованы |
| Восстанавливаемое состояние | `Item`, `OperationRun`, `Observation` | пересчитывается replay |
| Версионированный анализ | `AnalysisVersion`, `AnalysisEvidence` | добавляется новая версия |
| Человеческая/интеграционная история | `ControllerDecision`, `QualityResult`, `IntegrationMessage` | сохраняется как бизнес-факт |

Основные сущности:

- `Item` — изделие;
- `OperationRun` — фактическое выполнение операции;
- `Observation` — результат контроля;
- `DefectObservation` — сигнал конкретного defect type;
- `DefectOccurrence` — физический эпизод дефекта;
- `Nonconformance` — процесс рассмотрения несоответствия;
- `ControllerDecision` — решение контролёра;
- `AnalysisVersion` — версия Birth Window анализа;
- `AnalysisEvidence` — evidence/context/limitations;
- `OutboxMessage` — сообщение для внешней системы;
- `IntegrationMessage` — история доставки;
- `ProjectionState` — состояние пересборки изделия.

## 5. Canonical event contract

Источник истины контракта:

```text
contracts/events/canonical-event.schema.json
```

Из JSON Schema детерминированно генерируются Pydantic-модели, TypeScript-интерфейсы и contract registry.

Runtime contract `1.0` поддерживает:

```text
item.registered
operation.started
operation.finished
inspection.result
machine.state
operator.action
control_device.invalidated
```

Ключевые свойства:

- `item_id` и `operation_run_id` принадлежат canonical envelope;
- неизвестная версия отклоняется;
- malformed/invalid input отклоняется;
- семантически невозможные значения отклоняются;
- optional fields не получают выдуманные business defaults;
- `received_at` назначается TRACE-Q;
- production time хранится отдельно как `occurred_at`.

### Идемпотентность

Одинаковый `event_id` + одинаковое canonical content:

```text
duplicate
→ повтор не меняет бизнес-состояние
```

Одинаковый `event_id` + другое содержимое:

```text
409 EVENT_ID_CONFLICT
→ исходный факт не меняется
→ создаётся security alert
```

## 6. Ingestion и источники

Внешние источники не используют человеческие аккаунты.

Для source задаются:

- `source_id`;
- тип источника;
- allowed event types;
- line/station scopes;
- auth method;
- lifecycle status.

Поддерживаются demo shared-secret transport и `HMAC_V1` с timestamp + nonce + canonical body.

Nonce хранится как replay-факт, поэтому повтор транспортного запроса обнаруживается отдельно от бизнес-duplicate.

Примеры demo sources:

```text
MES-01
VISION-01
VISION-02
EQUIP-GW-01
MACHINE-01
OPTERM-01
OPERATOR-01
CAL-01
CALIBRATION-01
```

## 7. Проекции, replay и конкурентность

После приёма raw event TRACE-Q пересобирает состояние изделия.

Для одного изделия используется PostgreSQL advisory transaction lock. Разные изделия могут rebuild-иться параллельно.

Детерминированный порядок:

```text
occurred_at
source_id
source_sequence NULLS LAST
received_at
event_id
```

Это tie-break для воспроизводимости, а не доказательство причинности.

`ProjectionState` хранит:

```text
stale
rebuilding
up_to_date
failed
```

Если rebuild временно сломался после принятия raw event, исходный факт остаётся принятым, а проекция помечается как требующая восстановления.

## 8. Observation Trust

Observation получает один из статусов:

```text
TRUSTED
UNTRUSTED
UNASSESSABLE
CONFLICTED
INVALIDATED
```

Оценка учитывает:

- `observation_quality`;
- confidence и threshold, если это требует policy;
- validity средства контроля;
- media requirement;
- inspection scope;
- conflicts;
- evidence invalidation.

`impossible_to_assess` не является GOOD и получает `UNASSESSABLE`.

### Coverage

Coverage считается по `(defect_type, component_instance_id)`:

```text
FULL
PARTIAL
NONE
TARGET_ONLY
```

Только `FULL` может сформировать общий trusted GOOD boundary.

`TARGET_ONLY` используется для проверки конкретного NCR после rework и не превращается в общий исторический GOOD.

## 9. Missing checks и некорректные данные

Если следующая операция уже началась, а обязательный контроль предыдущего шага отсутствует, TRACE-Q фиксирует:

```text
MISSING_CHECK
LIMITATION
```

Система не создаёт фиктивное отрицательное наблюдение.

Общая семантика:

```text
данных нет
→ limitation

данные есть, но ненадёжны
→ сохраняются, но не считаются trusted

данные структурно/семантически невозможны
→ reject

данные валидны и проходят trust policy
→ участвуют в расчётах
```

## 10. Defect Birth Window

Одна из ключевых функций TRACE-Q — локализация интервала, в котором мог появиться дефект.

Для первого trusted defect `D` система ищет предыдущий trusted GOOD `G` с достаточным coverage для того же defect/component key.

Если GOOD найден:

```text
(G.occurred_at, D.occurred_at]
→ BOUNDED
```

Если GOOD отсутствует:

```text
(OPEN, D.occurred_at]
→ LEFT_OPEN
```

Birth Window не является автоматическим root-cause inference. Операции, machine warnings и operator actions внутри окна показываются как context evidence.

## 11. NCR и human-in-the-loop

`Nonconformance` хранит независимо несколько измерений состояния.

### Verdict

```text
pending_review
needs_extra_check
confirmed
rejected
```

### Disposition

```text
IN_PROCESS
REWORK_REQUIRED
RELEASED
SCRAPPED
USE_AS_IS
```

### Containment

```text
NONE
HOLD
REINSPECTION_REQUIRED
REVIEW_REQUIRED
```

### Cause status

```text
not_established
candidate
confirmed_by_human
```

Таким образом TRACE-Q не смешивает сигнал алгоритма, подтверждение дефекта, предполагаемую причину и производственное решение.

## 12. Rework и Controlled Release Gate

Доработка является новой производственной операцией, а не редактированием прошлого.

Rework `OperationRun` связывается с исходным NCR и предыдущим operation run.

Для безопасного выпуска после доработки требуется:

1. завершённая rework operation;
2. repeat trusted GOOD;
3. успешная controller verification;
4. разрешённое финальное решение контролёра.

Исходный дефект и NCR остаются в истории.

## 13. Evidence Invalidation

Если позднее выясняется, что средство контроля было неисправно или некорректно откалибровано, система не удаляет старые observations.

Вместо этого создаётся `ControlDeviceInvalidation`:

```text
invalidation
→ affected observations становятся INVALIDATED
→ affected items пересобираются
→ создаётся новая AnalysisVersion
→ Birth Window может измениться
```

Старая версия анализа сохраняется для audit/review.

## 14. Blast Radius

Blast Radius отвечает на вопрос: какие изделия потенциально затронуты обнаруженной проблемой?

Поддерживаемые факторы:

```text
equipment
tool
material_lot
control_device
component
time_interval
```

Ключевой принцип:

```text
Blast Radius
→ potential exposure
→ proposal
→ approval
```

Blast Radius сам не создаёт дефект и не переводит изделия в HOLD.

## 15. Coverage Gap Analyzer

Coverage Gap Analyzer помогает технологу проверить, насколько маршрут способен контролировать заявленные defect/component keys.

Статусы:

```text
FULL_AVAILABLE
PARTIAL_ONLY
NO_GENERAL_COVERAGE
TARGET_ONLY_ONLY
UNSCOPED_LEGACY
```

Функция read-only и не заменяет промышленную валидацию камер, оптики, NDT или метрологии.

## 16. Маршруты и версии

Маршрут моделируется как:

```text
RouteDefinition
→ RouteRevision
→ RouteStep[]
```

Технолог может создавать draft revision, редактировать steps, активировать revision и экспортировать структуру.

После activation revision становится immutable.

При регистрации изделия активная revision фиксируется в `Item.route_revision_id`. Позднейшее изменение маршрута не переписывает уже начатое изделие.

## 17. Realtime Dashboard

В верхней части «Обзора» для пользователей с `VIEW_ANALYTICS` работает read-only мониторинг.

Endpoint:

```http
GET /api/v1/analytics/live-quality?window=1h
```

Окна:

```text
15m
1h
24h
all
```

Streamlit обновляет блок примерно каждые 2 секунды polling-ом.

Показываются:

- Проверено;
- GOOD;
- Сигналы дефекта;
- Подтверждённые NCR;
- FPY;
- Ожидают решения;
- На доработке;
- Выпущено;
- GOOD/DEFECT во времени;
- сигналы по месту обнаружения;
- equipment warnings;
- последние производственно значимые изменения.

Семантические ограничения:

```text
defect signal ≠ confirmed NCR
detection station ≠ root cause
machine warning ≠ defect
GOOD ≠ automatic release
```

Dashboard не создаёт новую таблицу и не является новым source of truth.

## 18. Аналитика

Analytics API считает, в частности:

- inspected items;
- assessable inspected items;
- items with confirmed nonconformities;
- unique defect occurrences;
- observed defect signals;
- confirmed physical defects;
- defects by type;
- detection grouping по line/station;
- established/unknown causes;
- operation duration avg/median/p95;
- rework count и rework rate;
- FPY;
- Birth Window width;
- post-operation detection delay.

Station grouping всегда является местом обнаружения/контекстом, а не автоматически установленной причиной.

## 19. Factory Simulator

Demo-профиль включает отдельный `factory-simulator`.

Он:

- не подключается напрямую к PostgreSQL;
- не импортирует backend ORM;
- получает маршрут через TRACE-Q API;
- отправляет canonical events через обычный ingestion endpoint;
- не принимает решения за контролёра.

Режимы:

### Штатное прохождение

```text
регистрация
→ операция
→ GOOD
→ следующий шаг
```

### Дефект и доработка

```text
DEFECT
→ ожидание контролёра
→ REWORK_REQUIRED
→ rework
→ repeat inspection
→ verification
→ release
```

### Предупреждение оборудования

В поток добавляется `machine.state`, но warning не объявляется причиной дефекта.

## 20. Приёмочные сценарии S01–S25

| Сценарий | Основная проверка |
|---|---|
| S01 | normal flow, trusted inspections, no NCR |
| S02 | incoming defect → LEFT_OPEN |
| S03 | GOOD → operation → DEFECT → BOUNDED Birth Window; warning остаётся context |
| S04 | poor-quality GOOD не становится trusted boundary |
| S05 | `MISSING_CHECK` |
| S06 | duplicate idempotency |
| S07 | late event → AnalysisVersion v2 |
| S08 | controller decision → rework → repeat GOOD → release |
| S09 | tamper detection |
| S10 | conflicting observations |
| S11 | defect без prior GOOD остаётся LEFT_OPEN |
| S12 | разные defect types и coverage |
| S13 | `UNASSESSABLE` |
| S14 | `EVENT_ID_CONFLICT` |
| S15 | out-of-order delivery |
| S16 | failed rework |
| S17 | Evidence Invalidation |
| S18 | Blast Radius proposal |
| S19 | ERP offline → retry → delivery |
| S20 | unknown source denied |
| S21 | nonce replay protection |
| S22 | RBAC / Controlled Release Gate |
| S23 | degraded item-level structure |
| S24 | route revision pinning |
| S25 | occurrence-based KPI |

Scenario Runner в UI использует те же acceptance bundles, что PostgreSQL CI.

## 21. Интеграции

TRACE-Q не помещает vendor-specific поля внутрь бизнес-ядра.

Основная integration boundary:

```text
ProductionSystemAdapter
```

Подготовлены interfaces/fixture transports для:

- MES;
- 1С;
- Галактика:ERP;
- КОМПАС-3D / product structure provider.

Для реального предприятия потребуются конкретные endpoint URL, schemas, authentication, TLS/mTLS, mappings и network policy.

Наличие fixture adapter не заявляется как готовая сертифицированная интеграция с неизвестной инсталляцией заказчика.

## 22. Transactional Outbox

Решение контролёра и сообщение во внешнюю систему не должны расходиться.

Поэтому используются:

```text
ControllerDecision
+ QualityResult
+ OutboxMessage
```

в одной бизнес-транзакции.

Отдельный worker обрабатывает состояния доставки и retry.

Особенности:

- стабильный `message_id`;
- повторная отправка не создаёт новое бизнес-сообщение;
- ACK сопоставляется с ожидаемым message;
- worker использует `FOR UPDATE SKIP LOCKED`;
- ERP outage не откатывает уже принятое controller decision.

## 23. Безопасность

### 23.1. Шифрование

RawEvent payload защищается AES-256-GCM.

### 23.2. Integrity chain

Для исходной истории используется HMAC-SHA256 chain.

### 23.3. Integrity Checkpoints

Классический профиль использует ECDSA P-256.

Опциональный профиль:

```text
HYBRID_PQ_V1
=
ECDSA P-256
+
ML-DSA-65
```

Обе подписи создаются над одним canonical checkpoint payload. Hybrid verification успешен только при успешной проверке обеих подписей. Silent downgrade к classic не используется.

### 23.4. Пароли и сессии

- password hashes: Argon2id;
- короткоживущий access token;
- server-side session;
- refresh-token rotation;
- revoke/logout;
- runtime permission check.

### 23.5. RBAC

Базовые роли:

```text
controller
master
technologist
manager
admin
simulator_reader
```

Role capabilities хранятся в PostgreSQL и могут изменяться через audited admin workflow.

Защищён сценарий потери последнего human `MANAGE_USERS`. `simulator_reader` является system-locked role.

### 23.6. Service source security

Source identity отделена от human identity. Источник ограничен allowed event types и scope.

### 23.7. Audit

Критические административные и quality actions сохраняются в audit trail.

## 24. Масштабирование

Реализован deterministic scaling proof:

```text
same physical input history
+
different concurrency
→
same business state
```

Профили:

- smoke: 100 изделий, 1 vs 2 senders;
- standard: 1000 изделий, 1 vs 4 senders.

Сравниваются:

- dataset SHA-256;
- raw unique count;
- projection hash;
- KPI hash;
- failures/backlog;
- replay stability;
- outbox delivery;
- recovery после остановки worker.

Throughput измеряется, но линейное ускорение не является критерием PASS.

Потенциальные bottlenecks:

- hot-item replay;
- source-level integrity serialization;
- PostgreSQL I/O;
- analytical scans.

## 25. Data Health и Doctor

UI показывает:

- ingestion status/errors;
- projection states;
- outbox states;
- integration health;
- worker heartbeats;
- problem items.

TRACE-Q Doctor:

```bash
python scripts/traceq_doctor.py --mode preflight
python scripts/traceq_doctor.py --mode live
python scripts/traceq_doctor.py --mode all
```

Doctor является read-only диагностикой окружения.

## 26. Контракты и антирассинхронизация

Canonical JSON Schema является единым источником истины.

CI проверяет:

```text
generated-code drift
contract fixtures
contract evolution
schema compatibility
```

Отдельный evolution proof демонстрирует изменение `1.0 → 1.1`, не включая 1.1 в runtime registry.

## 27. Пользовательские роли

### Контролёр качества

- изделия и timeline;
- review NCR;
- extra inspection;
- controller decision;
- rework verification;
- approval quality actions.

### Мастер участка

- изделия;
- состояние производства;
- analytics;
- realtime dashboard;
- investigation notes.

### Технолог

- история и analytics;
- route management;
- Coverage Gap Analyzer;
- Blast Radius;
- investigation notes.

### Руководитель производства

- Overview;
- realtime dashboard;
- analytics;
- NCR;
- audit.

### Администратор

- users/roles/capabilities;
- integrations/sources;
- audit/integrity;
- replay;
- trust policy;
- crypto profiles и key operations.

### Factory simulator reader

Служебная read-only роль demo simulator.

## 28. Реализация критериев кейса

Ниже нумерация сохранена по официальному документу. В техническом блоке оригинальная нумерация после пункта 3 переходит к пункту 5.

### 28.1. Отраслевые критерии — 70 баллов

| Критерий | Max | Реализация в TRACE-Q | Что показывать |
|---|---:|---|---|
| 1. Понимание производственных процессов и специфики отрасли | 10 | Routes/revisions, incoming inspection, operations, equipment/operator context, rework, human authority, ограничения VisionQC/NDT/metrology, degraded item-level mode | Timeline + route + VisionQC assumptions |
| 2. Сквозной процесс контроля качества и работы с браком | 15 | Observation → trust → DefectOccurrence → NCR → ControllerDecision → rework → repeat inspection → verification → release | S03 + S08 |
| 3. Модуль сбора и обработки данных | 15 | Canonical events, validation, source auth, idempotency, late events, missing checks, replay, conflicts, out-of-order | S05/S06/S07/S10/S14/S15 |
| 4. Презентация и защита | 5 | Human-first UI, Scenario Runner, live simulator, realtime dashboard, explainable Birth Window | Live demo |
| 5. Дополнительные отраслевые улучшения | 5 | Evidence Invalidation, Blast Radius, Coverage Gap Analyzer, realtime quality dashboard | S17/S18 + Overview |
| 6. Расширяемость, масштабируемость и поддерживаемость | 5 | Modular boundaries, adapters, config routes, item locks, SKIP LOCKED outbox, scaling proof | `docs/SCALING_PROOF.md` |
| 7. Спецификации и кодогенерация | 5 | JSON Schema → generated Python/TypeScript/registry | contract generation check |
| 8. Автоматизация предотвращения рассинхронизации | 5 | CI drift/evolution/fixture checks | CI |
| 9. Долгосрочная криптографическая защита | 5 | Threat model, external keyrings, crypto profiles, ECDSA P-256 + optional real ML-DSA-65 | `pq-proof` |

### 28.2. Технические критерии — 60 баллов

| Критерий | Max | Реализация в TRACE-Q | Что показывать |
|---|---:|---|---|
| 1. Работоспособность и воспроизводимость кода | 8 | Docker Compose, migrations, seed, healthchecks, Doctor, local smoke, clean reset | clean start + smoke |
| 2. Архитектура и системные интеграции | 12 | Adapter boundary, ERP Emulator, Outbox, retry/ACK, fixtures for 1C/Galaktika/MES, KOMPAS provider | S19 / integration health |
| 3. Информационная безопасность и аудит | 5 | RBAC, source auth/scope, AES-GCM, HMAC chain, append-only history/audit, checkpoint signatures | deny + tamper/integrity |
| 5. Полнота и качество документации | 5 | README, architecture, domain, events, security, integrations, scenarios, limitations, runbooks | `docs/` + этот файл |
| 6. Сквозной процесс контроля качества и работы с браком | 15 | Full quality lifecycle with human decision/rework/release | S03/S08/S16/S17 |
| 7. Модуль сбора и обработки данных | 15 | Structured VisionQC input, gaps, duplicates, delays, conflicts, replay | S04–S07/S10/S14/S15 |

## 29. Рекомендуемый demo flow

### Demo 1 — signal ≠ NCR

```text
Simulator отправляет DEFECT
→ «Сигналы дефекта» увеличивается
→ confirmed NCR ещё нет
→ контролёр подтверждает
→ «Подтверждённые NCR» увеличивается
```

### Demo 2 — Birth Window

```text
trusted GOOD
→ operation
→ machine warning
→ trusted DEFECT
```

Показать, что warning — context, а не root cause.

### Demo 3 — Rework

```text
confirmed NCR
→ REWORK_REQUIRED
→ rework operation
→ repeat GOOD
→ controller verification
→ RELEASED
```

### Demo 4 — Evidence Invalidation

Показать v1 анализа и новую версию после invalidation.

### Demo 5 — ERP outage

Показать сохранённое controller decision, Outbox retry с тем же `message_id` и последующий ACK.

### Demo 6 — Security

Показать RBAC deny и integrity/tamper proof.

## 30. Что TRACE-Q сознательно не заявляет

### Нет собственной промышленно валидированной CV-модели

TRACE-Q принимает structured observations от внешнего VisionQC.

### Нет заявления о готовой интеграции с конкретным заводом

Есть interfaces/adapters/emulator/fixtures. Реальные endpoints и credentials должны быть предоставлены на интеграции.

### Нет автоматического root cause

TRACE-Q локализует временное окно и собирает evidence/context. Причину подтверждает специалист.

### Machine warning не равен дефекту

Warning является контекстом.

### Камеры не прошли промышленную валидацию

Параметры оптики, latency и minimum detectable defect остаются project assumptions до натурных испытаний.

### PQ runtime не равен production-сертификации

ML-DSA-65 hybrid runtime реализован и тестируется, но это не HSM/key-ceremony/certification предприятия.

## 31. Ограничения MVP

- demo products/routes/equipment/timings синтетические;
- PostgreSQL является поддерживаемым persistence path;
- component structure может отсутствовать, тогда система работает на item-level с меньшей точностью;
- real MES/ERP/KOMPAS transport site-specific;
- HTTPS/mTLS относится к deployment boundary;
- runtime event contract сейчас `1.0`;
- visual inspection не заменяет обязательную метрологию/NDT;
- source clock drift пока не оценивается автоматически;
- realtime dashboard использует polling, а не WebSocket;
- на больших объёмах analytics может потребовать cache/materialized aggregates.

## 32. Тестирование

### Unit / contracts / security

```bash
./scripts/run_tests.sh unit
./scripts/run_tests.sh contracts
./scripts/run_tests.sh security
```

### PostgreSQL / scenarios

```bash
./scripts/run_tests.sh postgres
./scripts/run_tests.sh scenarios
```

### Всё

```bash
./scripts/run_tests.sh all
```

### Docker smoke

```bash
bash scripts/local_smoke.sh
bash scripts/simulator_smoke.sh
```

### Realtime dashboard

```bash
pytest backend/tests/test_live_quality.py -q
RUN_POSTGRES_TESTS=1 pytest backend/tests/test_live_quality_postgres.py -q
```

### Final acceptance

```bash
python scripts/verify_final_improvements.py --default
```

Optional PQ:

```bash
uv sync --all-groups --extra pq
python scripts/verify_final_improvements.py --pq
```

## 33. CI

GitHub Actions включает jobs:

```text
unit-and-contracts
postgres-integration
scaling-smoke-proof
pq-proof
docker-demo-smoke
```

Они покрывают разные классы отказов и не заменяются одним формальным unit-test job.

## 34. Структура репозитория

```text
backend/
  app/
    api/              FastAPI endpoints
    domain/           event validation / business rules
    ingestion/        source ingestion
    integrations/     adapter ports / external systems
    persistence/      SQLAlchemy / PostgreSQL
    projections/      deterministic rebuild
    quality/          trust / Birth Window / release
    read_models/      read-only aggregate views
    security/         auth / RBAC / crypto / audit

contracts/events/      canonical schema + evolution proof
shared_contracts/      generated artifacts
streamlit_app/         UI + backend API client
factory_simulator/     live demo simulator
erp_emulator/          ERP emulator
worker/                outbox worker
scenarios/S01...S25/   acceptance bundles
scripts/               smoke / doctor / scaling / generation / acceptance
docs/                  project documentation
```

## 35. Главные документы

```text
README.md
docs/architecture.md
docs/domain.md
docs/events.md
docs/quality-analysis.md
docs/routes.md
docs/integrations.md
docs/security.md
docs/scenarios.md
docs/demo.md
docs/vision-control-design.md
docs/limitations.md
docs/recovery.md
docs/LOCAL_RUNBOOK.md
docs/MODULE_TESTING.md
docs/LIVE_FACTORY_SIMULATOR.md
docs/SIMULATOR_TESTING.md
docs/REALTIME_DASHBOARD.md
docs/SCALING_PROOF.md
docs/AUDIT_REPORT.md
docs/assumptions.md
```

## 36. Короткая формулировка решения

> **TRACE-Q превращает разрозненные результаты контроля и производственные события в защищённую, воспроизводимую историю изделия, локализует интервал возможного возникновения дефекта, сохраняет доказательства и ограничения анализа и проводит несоответствие через human-in-the-loop процесс до доработки, повторного контроля, выпуска и передачи результата во внешнюю систему.**

Главное отличие TRACE-Q — доказуемость:

```text
что произошло
когда произошло
каким данным можно доверять
где мог возникнуть дефект
какие факторы были рядом
какое решение принял человек
что произошло после решения
можно ли воспроизвести этот вывод снова
```
