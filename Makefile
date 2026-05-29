.PHONY: setup lint lint-md format test test-all check check-all coverage

setup:
	@echo "==> Installing Python dev dependencies..."
	pip install -e '.[dev]'
	@if [ ! -f package.json ]; then \
		ln -s package.dev.json package.json && \
		echo "Created symlink: package.json -> package.dev.json"; \
	fi
	@echo "==> Installing Node.js dependencies..."
	npm install
	@echo "==> Setup complete."

lint:
	@echo "==> Linting Python files..."
	ruff check scripts/ tests/

lint-md:
	@echo "==> Linting Markdown files..."
	npx markdownlint-cli2

format:
	@echo "==> Formatting Python files..."
	ruff format scripts/ tests/

test:
	@echo "==> Running fast tests..."
	pytest

test-all:
	@echo "==> Running all tests (including slow)..."
	pytest -m ""

check: lint lint-md test

check-all: lint lint-md test-all

coverage:
	@echo "==> Running tests with coverage..."
	pytest --cov=scripts --cov-report=term-missing
