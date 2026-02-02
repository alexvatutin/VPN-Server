PYTHON ?= python3

install:
	$(PYTHON) -m pip install -r requirements.txt

lint:
	@echo "No linters configured for MVP."

test:
	pytest -q

run-api:
	uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000

run-bot:
	$(PYTHON) -m apps.bot.main

migrate:
	cd apps/api && alembic upgrade head
