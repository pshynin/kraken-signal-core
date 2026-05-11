.PHONY: build run dry-run logs help

IMAGE = kraken-scanner:local

help:
	@echo "make build    — build the Docker image"
	@echo "make run      — run one scan (production, reads .env)"
	@echo "make dry-run  — run without DB writes or alerts"
	@echo "make logs     — tail logs from the last container"

build:
	docker build -t $(IMAGE) .

run: build
	docker run --rm --env-file .env $(IMAGE)

dry-run: build
	docker run --rm --env-file .env $(IMAGE) --dry-run

logs:
	docker logs $$(docker ps -lq) --follow
