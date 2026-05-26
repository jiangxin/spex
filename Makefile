.PHONY: lint lint-md format test check coverage

lint:
	ruff check scripts/ tests/

lint-md:
	npx markdownlint-cli2

format:
	ruff format scripts/ tests/

test:
	pytest

test-all:
	pytest -m ""

check: lint lint-md test

check-all: lint lint-md test-all

coverage:
	pytest --cov=scripts --cov-report=term-missing
