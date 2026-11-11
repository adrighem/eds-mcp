.PHONY: help install-bridge lock-check lint format format-check typecheck test check

help:
	@echo "Available commands:"
	@echo "  make test            - Run the Python unit test suite"
	@echo "  make lint            - Run Ruff linter"
	@echo "  make format          - Format Python code with Ruff"
	@echo "  make format-check    - Check formatting with Ruff"
	@echo "  make typecheck       - Run Mypy static type checker"
	@echo "  make lock-check      - Verify uv.lock is up to date"
	@echo "  make check           - Run lock, lint, format, typecheck, and test checks"
	@echo "  make install-bridge  - Build and install the Evolution MCP Automation Bridge plugin"

lock-check:
	uv lock --check

lint:
	uv run ruff check src tests

format:
	uv run ruff format src tests

format-check:
	uv run ruff format --check src tests

typecheck:
	uv run mypy src tests

test:
	uv run pytest

check: lock-check lint format-check typecheck test

install-bridge:
	@echo "Installing Evolution MCP Automation Bridge..."
	@cd evolution-mcp-automation-bridge && ./scripts/install.sh
	@echo "Done!"
