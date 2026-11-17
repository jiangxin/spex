.DEFAULT_GOAL := help
.PHONY: help dev-env lint lint-md format test test-all check check-all coverage coverage-all version version-check bump

PYTHON = python3
VENV_PYTHON = .venv/bin/python

help:
	@printf '%s\n' \
		'Usage: make <target>' \
		'' \
		'  help                Show available targets' \
		'  dev-env             Set up the Python development environment' \
		'  lint                Lint Python files' \
		'  lint-md             Lint Markdown files' \
		'  format              Format Python files' \
		'  test                Run fast tests' \
		'  test-all            Run all tests, including slow tests' \
		'  check               Check versions, run linters and fast tests' \
		'  check-all           Check versions, run linters and all tests' \
		'  coverage            Measure coverage with fast tests' \
		'  coverage-all        Measure coverage with all tests' \
		'  version             Show the current version' \
		'  version-check       Check version consistency' \
		'  bump VERSION=x.y.z  Update the version'

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
	npx --yes markdownlint-cli2@0.18.1

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
