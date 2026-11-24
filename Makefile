ENV_FILE := $(wildcard .env)
.PHONY: up down
up:
	$(if $(ENV_FILE),,$(error .env missing - copy .env.example to .env and add two keys))
	docker compose up -d --build
down:
	docker compose down
