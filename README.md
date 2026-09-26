# TRACE-Q

TRACE-Q — MVP системы интеллектуального контроля качества и прослеживаемости изделий.

Система принимает структурированные производственные события и результаты контроля, формирует единую историю изделия, оценивает доверие к наблюдениям, регистрирует несоответствия, строит Defect Birth Window, поддерживает human-in-the-loop решение контролёра, rework/verification/release, аналитику и интеграцию с внешней ERP через transactional Outbox.

Подробное описание решения: [`DOCUMENTATION.md`](DOCUMENTATION.md).

## 1. Требования

Нужны:

- Docker Engine;
- Docker Compose v2;
- Git;
- примерно 1 ГБ свободной RAM;
- свободные порты:

```text
8501   Streamlit UI
8080   FastAPI
8070   Factory Simulator
8090   ERP Emulator
55432  PostgreSQL debug port
```

Локальный Python не нужен, если требуется только запустить demo stack.

## 2. Получить актуальный код

Если используется рабочая ветка проекта:

```bash
git switch chatgpt/hardening-fixes
git fetch origin
git pull --ff-only origin chatgpt/hardening-fixes
```

Перейдите в корень репозитория:

```bash
cd ~/python_prjcts/kosmohack_final
```

## 3. Первый запуск

```bash
cp -n .env.example .env

docker compose -f compose.yaml -f compose.demo.yaml up -d --build --wait

bash scripts/local_smoke.sh
```

`cp -n` не перезапишет уже существующий `.env`.

Успешный smoke должен закончиться:

```text
TRACE-Q local smoke: OK
```

## 4. URL

### Streamlit

```text
http://localhost:8501
```

### Swagger / FastAPI

```text
http://localhost:8080/docs
```

### Backend readiness

```text
http://localhost:8080/health/ready
```

### ERP Emulator

```text
http://localhost:8090/health
```

## 5. Тестовые пользователи

Все данные ниже предназначены только для `DEMO_MODE=true`.

| Пользователь | Роль | Пароль | Основное назначение |
|---|---|---|---|
| `controller` | Контролёр качества | `controller-demo` | NCR, controller decision, rework verification |
| `master` | Мастер участка | `master-demo` | изделия, история, analytics, overview |
| `technologist` | Технолог | `technologist-demo` | routes, Coverage Gap, Blast Radius, analytics |
| `manager` | Руководитель производства | `manager-demo` | realtime dashboard, analytics, audit |
| `admin` | Администратор | `admin-demo` | users, roles, integrations, integrity, crypto |
| `factory-simulator` | Служебный read-only пользователь | `simulator-reader-demo` | используется Factory Simulator, вручную обычно не нужен |

Не используйте demo credentials и demo crypto keys в production.

## 6. Быстрая проверка

```bash
docker compose -f compose.yaml -f compose.demo.yaml ps
bash scripts/local_smoke.sh
bash scripts/simulator_smoke.sh
```

Readiness:

```bash
curl -fsS http://127.0.0.1:8080/health/ready
```

## 7. Быстрый demo

### Приёмочные сценарии

Откройте страницу:

```text
Приёмочные сценарии
```

Полезные сценарии:

```text
S03  Birth Window + equipment warning как context
S08  decision → rework → repeat inspection → release
S09  tamper detection
S17  Evidence Invalidation
S18  Blast Radius
S19  ERP offline → retry → ACK
S22  RBAC / Controlled Release Gate
```

### Live Factory Simulator

Откройте:

```text
Симуляция производства
```

Запустите режим:

```text
Дефект и доработка
```

Когда симуляция дойдёт до ожидания решения:

1. во второй вкладке войдите как `controller`;
2. откройте `Контроль качества`;
3. подтвердите NCR;
4. выберите `REWORK_REQUIRED`;
5. вернитесь к симуляции;
6. дождитесь rework и повторного контроля;
7. выполните verification/release.

## 8. Realtime Dashboard

Войдите как:

```text
manager / manager-demo
```

Откройте `Обзор`.

Сверху должен быть оперативный мониторинг:

```text
Проверено
GOOD
Сигналы дефекта
Подтверждённые NCR
FPY
Ожидают решения
На доработке
Выпущено
```

Блок обновляется автоматически примерно каждые 2 секунды.

Ожидаемая логика:

```text
trusted GOOD
→ GOOD +1

trusted DEFECT
→ Сигналы дефекта +1
→ confirmed NCR пока не увеличивается

controller confirms NCR
→ Подтверждённые NCR +1

rework
→ На доработке +1

repeat GOOD + verification/release
→ На доработке уменьшается
→ Выпущено увеличивается
```

## 9. Логи

Все сервисы:

```bash
docker compose -f compose.yaml -f compose.demo.yaml logs -f
```

Backend:

```bash
docker compose -f compose.yaml -f compose.demo.yaml logs -f backend
```

Worker:

```bash
docker compose -f compose.yaml -f compose.demo.yaml logs -f worker
```

ERP Emulator:

```bash
docker compose -f compose.yaml -f compose.demo.yaml logs -f erp-emulator
```

## 10. Остановить приложение

Без удаления данных:

```bash
docker compose -f compose.yaml -f compose.demo.yaml down
```

Запустить снова без rebuild:

```bash
docker compose -f compose.yaml -f compose.demo.yaml up -d --wait
```

## 11. Rebuild после изменений

```bash
docker compose -f compose.yaml -f compose.demo.yaml up -d --build --wait
```

## 12. Полный чистый reset

**Внимание:** команда удалит локальный PostgreSQL volume.

```bash
docker compose -f compose.yaml -f compose.demo.yaml down -v --remove-orphans

docker compose -f compose.yaml -f compose.demo.yaml up -d --build --wait

bash scripts/local_smoke.sh
```

Перед презентацией это полезно, если manual tests загрязнили demo DB.

## 13. Автоматические тесты

### Unit

```bash
./scripts/run_tests.sh unit
```

### Contracts

```bash
./scripts/run_tests.sh contracts
```

### Security

```bash
./scripts/run_tests.sh security
```

### PostgreSQL

```bash
./scripts/run_tests.sh postgres
```

### S01–S25

```bash
./scripts/run_tests.sh scenarios
```

### Всё

```bash
./scripts/run_tests.sh all
```

## 14. Realtime dashboard tests

```bash
pytest backend/tests/test_live_quality.py -q
RUN_POSTGRES_TESTS=1 pytest backend/tests/test_live_quality_postgres.py -q
```

## 15. Factory Simulator tests

```bash
pytest factory_simulator/tests -q
bash scripts/simulator_smoke.sh
```

## 16. TRACE-Q Doctor

До запуска:

```bash
python scripts/traceq_doctor.py --mode preflight
```

После запуска:

```bash
python scripts/traceq_doctor.py --mode live
```

Полностью:

```bash
python scripts/traceq_doctor.py --mode all
```

## 17. Final acceptance runner

```bash
python scripts/verify_final_improvements.py --default
```

Optional PQ:

```bash
uv sync --all-groups --extra pq
python scripts/verify_final_improvements.py --pq
```

Всё вместе:

```bash
python scripts/verify_final_improvements.py --all
```

## 18. Isolated PostgreSQL suite

```bash
docker compose -f compose.test.yaml down -v --remove-orphans

docker compose -f compose.test.yaml up -d --build postgres-test

docker compose -f compose.test.yaml run --rm migrate-test

docker compose -f compose.test.yaml run --rm seed-test

docker compose -f compose.test.yaml run --rm postgres-tests

docker compose -f compose.test.yaml down -v --remove-orphans
```

Не запускайте destructive test/scaling scripts против production database.

## 19. Если что-то не стартует

### Проверить контейнеры

```bash
docker compose -f compose.yaml -f compose.demo.yaml ps
```

### Backend alive, но not ready

```bash
curl -fsS http://127.0.0.1:8080/health/ready

docker compose -f compose.yaml -f compose.demo.yaml logs migrate seed backend
```

### Порт занят

```bash
ss -ltnp | grep -E ':8501|:8080|:8070|:8090|:55432'
```

### ERP / Outbox

```bash
docker compose -f compose.yaml -f compose.demo.yaml logs -f worker erp-emulator
```

## 20. Перед презентацией

```bash
git pull --ff-only

docker compose -f compose.yaml -f compose.demo.yaml down -v --remove-orphans

docker compose -f compose.yaml -f compose.demo.yaml up -d --build --wait

bash scripts/local_smoke.sh
bash scripts/simulator_smoke.sh

docker compose -f compose.yaml -f compose.demo.yaml ps

curl -fsS http://127.0.0.1:8080/health/ready
```

После этого открыть:

```text
http://localhost:8501
```

и вручную прогнать:

```text
S03
S08
Realtime Dashboard + Factory Simulator
```

## 21. Основные документы

```text
DOCUMENTATION.md
docs/architecture.md
docs/domain.md
docs/events.md
docs/quality-analysis.md
docs/routes.md
docs/integrations.md
docs/security.md
docs/scenarios.md
docs/demo.md
docs/LOCAL_RUNBOOK.md
docs/MODULE_TESTING.md
docs/LIVE_FACTORY_SIMULATOR.md
docs/SIMULATOR_TESTING.md
docs/REALTIME_DASHBOARD.md
docs/SCALING_PROOF.md
docs/limitations.md
docs/assumptions.md
```

## 22. Важные границы MVP

- TRACE-Q не содержит промышленно валидированной собственной CV-модели.
- Machine warning не является автоматически доказанной причиной дефекта.
- Defect signal не равен confirmed NCR.
- Финальное решение по качеству остаётся за уполномоченным человеком.
- Реальные 1С / Галактика / MES / КОМПАС требуют site-specific endpoints, credentials и mappings.
- Demo credentials и demo crypto secrets не предназначены для production.
