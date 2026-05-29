.PHONY: setup lint lint-md format test check coverage

setup:
	@if [ ! -f package.json ]; then \
		ln -s package.dev.json package.json && \
		echo "Created symlink: package.json -> package.dev.json"; \
	fi
	npm install

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
