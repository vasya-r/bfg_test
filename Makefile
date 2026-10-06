PROJECT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

WHEEL_VENV := $(PROJECT_DIR)/.venv-wheel
TEST_VENV  := $(PROJECT_DIR)/.venv-test

.PHONY: setup test wheel down down-v

setup:
	[ -f .env ] || cp .env.example .env
	[ -f secrets/postgres_password ] || cp secrets/postgres_password.example secrets/postgres_password
	[ -f secrets/redis_password ] || cp secrets/redis_password.example secrets/redis_password

# Тесты на настоящих PostgreSQL и Redis в чистом тестовом окружении.
test:
	docker compose up -d --wait postgres redis_test
	rm -rf $(TEST_VENV) && python3 -m venv $(TEST_VENV)
	$(TEST_VENV)/bin/pip install -q -e '.[dev]'
	$(TEST_VENV)/bin/pytest; status=$$?; rm -rf $(TEST_VENV); exit $$status

# Собрать wheel, поставить в чистое окружение и запустить оба сервиса
# Ctrl+C - остановить.
wheel:
	docker compose up -d --wait postgres redis
	rm -rf dist $(WHEEL_VENV) && python3 -m venv $(WHEEL_VENV)
	$(WHEEL_VENV)/bin/pip install -q build
	$(WHEEL_VENV)/bin/python -m build
	$(WHEEL_VENV)/bin/pip install -q dist/*.whl
	$(WHEEL_VENV)/bin/inventory-api migrate
	$(WHEEL_VENV)/bin/analytics-worker & trap 'kill $$! 2>/dev/null' EXIT INT TERM; $(WHEEL_VENV)/bin/inventory-api

# Остановить и удалить контейнеры; данные остаются в томе bfg_pgdata.
down:
	docker compose down --remove-orphans
# то же самое, но с удалением данных
down-v:
	docker compose down -v