.PHONY: install test run migrate revision key up down fmt

install:
	uv sync --extra dev

test:
	uv run pytest -q

run:
	uv run uvicorn gateway.main:app --reload

migrate:
	uv run alembic upgrade head

revision:
	uv run alembic revision --autogenerate -m "$(m)"

key:
	uv run python scripts/create_key.py --workspace "Acme" --project "prod" \
		--models gpt-5.4 claude-sonnet-4-6 gemini-2.5-pro --credits 100

up:
	docker compose up --build

down:
	docker compose down -v
