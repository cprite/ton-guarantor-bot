.PHONY: install dev test lint fmt typecheck run doctor wallet docker

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check src tests

fmt:
	ruff check --fix src tests
	ruff format src tests

typecheck:
	mypy

run:
	python -m guarantor run

doctor:
	python -m guarantor doctor

wallet:
	python -m guarantor new-wallet

docker:
	docker compose up --build -d
