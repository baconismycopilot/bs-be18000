.PHONY: clean clean-build clean-pyc clean-test lint format typecheck check test build sync install uninstall help
.DEFAULT_GOAL := help

define PRINT_HELP_PYSCRIPT
import re, sys

for line in sys.stdin:
	match = re.match(r'^([a-zA-Z_-]+):.*?## (.*)$$', line)
	if match:
		target, help = match.groups()
		print("%-20s %s" % (target, help))
endef
export PRINT_HELP_PYSCRIPT

help:
	@python3 -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)

clean: clean-build clean-pyc clean-test ## remove all build, Python, and test artifacts

clean-build: ## remove build artifacts
	rm -fr build/
	rm -fr dist/
	find . -name '*.egg-info' -exec rm -fr {} +

clean-pyc: ## remove Python file artifacts
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

clean-test: ## remove test, lint, and type-check caches
	find . -name '.pytest_cache' -exec rm -rf {} +
	find . -name '.ruff_cache' -exec rm -rf {} +
	find . -name '.mypy_cache' -exec rm -rf {} +

sync: ## install/sync project dependencies
	uv sync

lint: ## check code style with ruff
	uv run ruff check .

format: ## auto-format code with ruff
	uv run ruff format .

typecheck: ## run mypy in strict mode
	uv run mypy src tests

test: ## run tests
	uv run pytest

check: lint typecheck test ## run lint, typecheck, and tests

build: ## build the sdist and wheel
	uv build

install: ## install the bs-be18000 CLI to ~/.local/bin via uv tool (editable)
	uv tool install --editable .

uninstall: ## remove the bs-be18000 CLI installed via uv tool
	uv tool uninstall bs-be18000
