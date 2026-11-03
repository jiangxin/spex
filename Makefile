.PHONY: setup dev-env lint lint-md format test test-all check check-all coverage coverage-all version version-check bump

PYTHON = python3
VENV_PYTHON = .venv/bin/python
export PATH := $(CURDIR)/.venv/bin:$(PATH)

setup: dev-env
	@echo "==> Installing Node.js dependencies..."
	npm install
	@echo "==> Setup complete."

dev-env: .venv/.dev-ready

.venv/bin/python:
	@echo "==> Creating project virtual environment..."
	$(PYTHON) -m venv .venv

.venv/.dev-ready: .venv/bin/python skills/spex/pyproject.toml
	@echo "==> Installing Python dev dependencies..."
	$(VENV_PYTHON) -m pip install -e 'skills/spex/[dev]'
	touch $@

lint: dev-env
	@echo "==> Linting Python files..."
	$(VENV_PYTHON) -m ruff check skills/spex/scripts/ skills/git-commit/scripts/ tests/

lint-md:
	@echo "==> Linting Markdown files..."
	npx markdownlint-cli2

format: dev-env
	@echo "==> Formatting Python files..."
	$(VENV_PYTHON) -m ruff format skills/spex/scripts/ tests/

test: dev-env
	@echo "==> Running fast tests..."
	$(VENV_PYTHON) -m pytest -n auto

test-all: dev-env
	@echo "==> Running all tests (including slow)..."
	$(VENV_PYTHON) -m pytest -m "" -n auto

version:
	@$(PYTHON) skills/spex/scripts/version.py

version-check:
	@echo "==> Checking version consistency..."
	@$(PYTHON) skills/spex/scripts/version.py --check

bump:
	@$(PYTHON) skills/spex/scripts/version.py --bump $(VERSION)

check: version-check lint lint-md test

check-all: version-check lint lint-md test-all

coverage: dev-env
	@echo "==> Running tests with coverage..."
	$(VENV_PYTHON) -m pytest -n auto --cov=skills/spex/scripts --cov-report=term-missing

coverage-all: dev-env
	@echo "==> Running all tests with coverage..."
	$(VENV_PYTHON) -m pytest -m "" -n auto --cov=skills/spex/scripts --cov-report=term-missing
