.PHONY: help install-bridge lock-check test check

help:
	@echo "Available commands:"
	@echo "  make test            - Run the Python unit test suite"
	@echo "  make lock-check      - Verify uv.lock is up to date"
	@echo "  make check           - Run lock and unit-test checks"
	@echo "  make install-bridge  - Build and install the Evolution MCP Automation Bridge plugin"

lock-check:
	uv lock --check

test:
	uv run pytest

check: lock-check test

install-bridge:
	@echo "Installing Evolution MCP Automation Bridge..."
	@cd evolution-mcp-automation-bridge && ./scripts/install.sh
	@echo "Done!"
