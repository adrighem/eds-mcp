.PHONY: help install-bridge

help:
	@echo "Available commands:"
	@echo "  make install-bridge  - Build and install the Evolution MCP Automation Bridge plugin"

install-bridge:
	@echo "Installing Evolution MCP Automation Bridge..."
	@cd evolution-mcp-automation-bridge && ./scripts/install.sh
	@echo "Done!"
