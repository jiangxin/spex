.PHONY: setup lint lint-md format test test-all check check-all coverage coverage-all version version-check bump

PYTHON = python3

setup:
	@echo "==> Installing Python dev dependencies..."
	$(PYTHON) -m pip install -e 'skills/spex/[dev]'
	@if [ ! -f package.json ]; then \
		ln -s package.dev.json package.json && \
		echo "Created symlink: package.json -> package.dev.json"; \
	fi
	@echo "==> Installing Node.js dependencies..."
	npm install
	@echo "==> Setup complete."

lint:
	@echo "==> Linting Python files..."
	ruff check skills/spex/scripts/ tests/

lint-md:
	@echo "==> Linting Markdown files..."
	npx markdownlint-cli2

format:
	@echo "==> Formatting Python files..."
	ruff format skills/spex/scripts/ tests/

test:
	@echo "==> Running fast tests..."
	$(PYTHON) -m pytest -n auto

test-all:
	@echo "==> Running all tests (including slow)..."
	$(PYTHON) -m pytest -m "" -n auto

version:
	@$(PYTHON) skills/spex/scripts/version.py

version-check:
	@echo "==> Checking version consistency..."
	@$(PYTHON) skills/spex/scripts/version.py --check

bump:
	@$(PYTHON) skills/spex/scripts/version.py --bump $(VERSION)

check: version-check lint lint-md test

check-all: version-check lint lint-md test-all

coverage:
	@echo "==> Running tests with coverage..."
	$(PYTHON) -m pytest -n auto --cov=skills/spex/scripts --cov-report=term-missing

coverage-all:
	@echo "==> Running all tests with coverage..."
	$(PYTHON) -m pytest -m "" -n auto --cov=skills/spex/scripts --cov-report=term-missing
