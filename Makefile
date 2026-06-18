.PHONY: setup lint lint-md format test test-all check check-all coverage coverage-all version version-check bump

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
	pytest -n auto

test-all:
	@echo "==> Running all tests (including slow)..."
	pytest -m "" -n auto

version:
	@python3 scripts/version.py

version-check:
	@echo "==> Checking version consistency..."
	@python3 scripts/version.py --check

bump:
	@python3 scripts/version.py --bump $(VERSION)

check: version-check lint lint-md test

check-all: version-check lint lint-md test-all

coverage:
	@echo "==> Running tests with coverage..."
	pytest -n auto --cov=scripts --cov-report=term-missing

coverage-all:
	@echo "==> Running all tests with coverage..."
	pytest -m "" -n auto --cov=scripts --cov-report=term-missing
