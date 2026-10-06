**Проект Склад с pub/sub**

# Структура

```
├── src/
│   └── warehouse/                # пакет в wheel
│       ├── inventory_api/        # сервис 1
│       ├── analytics_worker/     # сервис 2
│       └── core/                 # общее для сервисов
├── tests/                        # тесты (в wheel не входят)
├── secrets/                      # папка с секретами
├── docker-compose.yml            # инфра (postgresql, redis, redis для тестов)
├── Makefile                      # setup, test, wheel, down
├── pyproject.toml                # сборка
├── alembic.ini                   # для миграций в разработке
├── .env.example                  # шаблон для .env
├── .gitignore                    # gitignore
└── README.md                     # readme
```

# Инструкция по запуску

Требования: docker compose, python ≥ 3.10, `venv`, `make`, `curl`.

Порты на хосте по умолчанию (можно изменить в настройках окружения .env):
- `8080` (API)
- `5440` (PostgreSQL)
- `6380` и `6381` (redis и test redis)

```bash
git clone git@github.com:vasya-r/bfg_test.git bfg_test && cd bfg_test
```

Создать настройки окружения (скопировать .env.example и секреты и изменить, если нужно):
```bash
make setup
```

Добавятся: `.env`, `secrets/postgres_password` и `secrets/redis_password`
Пароли подставляются в `DATABASE_URL` и `REDIS_URL` на место `{password}`

### 1. Тесты

```bash
make test
```
Ожидаемый результат: `9 passed`

Тесты запускаются на реальной базе `warehouse_test` (создается автоматически) и отдельном redis.
Зависимости ставятся в чистое окружение `.venv-test` в корне проекта, которое удаляется после прогона
Набор тестов минимальный: проверяется создание прихода/расхода, отправка сообщений в редис

### 2. Запуск из wheel (терминал 1)

```bash
make wheel
```

- сборка wheel в `dist/`
- установка в чистое окружение `.venv-wheel` в корне проекта
- применение миграций (`inventory-api migrate`)
- запуск сервисов `analytics-worker` и `inventory-api`

При старте и после каждого переподключения к redis воркер сначала применяет все события
с `applied = f` и потом начинает обрабатывать новые

Сервисы читают `.env` и каталог `secrets/` из текущего каталога. При запуске из другого места
пути задаются переменными `WAREHOUSE_ENV_FILE` и `WAREHOUSE_SECRETS_DIR`:

```bash
WAREHOUSE_ENV_FILE=/path/to/.env WAREHOUSE_SECRETS_DIR=/path/to/secrets inventory-api
```

### 3. Проверка (терминал 2)

Проверка, что API запущен:
```bash
curl localhost:8080/health
# {"status": "ok"}
```

Отправка запросов:
```bash
H='Content-Type: application/json'
curl -X POST localhost:8080/receipts -H "$H" -d '{"sku": "A-100", "qty": 50, "warehouse": "WH-1"}'
curl -X POST localhost:8080/issues   -H "$H" -d '{"sku": "A-100", "qty": 20, "warehouse": "WH-1"}'
curl -X POST localhost:8080/receipts -H "$H" -d '{"sku": "B-200", "qty": 5,  "warehouse": "WH-1"}'
curl -X POST localhost:8080/receipts -H "$H" -d '{"sku": "A-100", "qty": 10, "warehouse": "WH-2"}'
```

Пример ответа:
`{"event_id": 1, "type": "receipt", "warehouse": "WH-1", "sku": "A-100", "qty": 50}`.

Получение данных:
```bash
curl 'localhost:8080/stock?warehouse=WH-1'
# {"items": [{"warehouse": "WH-1", "sku": "A-100", "qty": 30}, {"warehouse": "WH-1", "sku": "B-200", "qty": 5}]}

curl 'localhost:8080/stock/summary'
# {"warehouses": [{"warehouse": "WH-1", "total_qty": 35, "sku_count": 2},
#                 {"warehouse": "WH-2", "total_qty": 10, "sku_count": 1}],
#  "top_skus": [{"sku": "A-100", "total_qty": 40}, {"sku": "B-200", "total_qty": 5}]}

curl 'localhost:8080/stock/summary?top_n=1'
# ... "top_skus": [{"sku": "A-100", "total_qty": 40}]
```

Товар с нулевым остатком не считается лежащим на складе: он не попадает в итоговую выдачу

Ошибки:
```bash
curl -X POST localhost:8080/issues -H "$H" -d '{"sku": "A-100", "qty": 999, "warehouse": "WH-1"}'
# 409 {"error": "not enough stock", "available": 30, "requested": 999}

curl -X POST localhost:8080/receipts -H "$H" -d '{"sku": "A-100", "qty": -1, "warehouse": "WH-1"}'
# 422 {"error": "validation error", "details": [{"type": "greater_than", "loc": ["qty"], "msg": "Input should be greater than 0"}]}

curl -X POST localhost:8080/receipts -H "$H" -d 'oops'
# 400 {"error": "request body must be valid JSON"}

curl 'localhost:8080/stock'
# 422 {"error": "validation error", "details": [{"type": "missing", "loc": ["warehouse"], "msg": "Field required"}]}

curl 'localhost:8080/unknown'
# 404 {"error": "not found"}

curl -X DELETE 'localhost:8080/stock'
# 405 {"error": "method not allowed"}
```

Все ошибки, включая необработанные, возвращаются в JSON

### 4. Таблицы в базе

```bash
docker exec bfg_postgres psql -U warehouse -d warehouse \
  -c 'SELECT id, event_type, warehouse, sku, qty, applied FROM stock_events ORDER BY id' \
  -c 'SELECT warehouse, sku, qty FROM stock_agg ORDER BY 1, 2'
```

В `stock_events` четыре операции с `applied = t`
В `stock_agg` - три строки

Остаток в API считается как `stock_agg` плюс события с `applied = f`, поэтому `/stock`,
`/stock/summary` и проверка расхода видят одно и то же число, даже если воркер отстал

### 5. Остановка

```bash
# Ctrl+C в терминале 1
make down         # остановить контейнеры; данные остаются в томе bfg_pgdata
make down-v       # то же самое с удалением данных
```

При повторном прогоне сценария остатки складываются с прежними (если не удалять данные)

### 6. Ограничения

- `POST /receipts` и `POST /issues` при повторном запросе клиентом создадут вторую операцию
- события, не примененные воркером (сообщение не отправлено или потеряно в pub/sub, ошибка базы при обработке), остаются в `stock_events` с `applied = f` и попадают в `stock_agg` только при следующем запуске воркера или его переподключении к redis. Нужно решение для устранения разрыва в моменте между ошибкой и пересчетом. При этом остатки считаются без ошибок, так как такие события досчитываются при чтении
