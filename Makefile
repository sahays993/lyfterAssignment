.PHONY: up down test

up:
	docker compose up --build

down:
	docker compose down

test:
	cd Backend && python -m pytest -q
