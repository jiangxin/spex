.PHONY: lint lint-md format test check coverage

lint:
	ruff check scripts/ tests/

lint-md:
	npx markdownlint-cli2

format:
	ruff format scripts/ tests/

test:
	pytest

check: lint lint-md test

coverage:
	pytest --cov=scripts --cov-report=term-missing
