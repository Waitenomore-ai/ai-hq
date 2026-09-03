.PHONY: test lint up down config

test:
	python -m pytest -q

lint:
	python -m ruff check src tests

config:
	docker compose config

up:
	docker compose up -d --build

down:
	docker compose down
