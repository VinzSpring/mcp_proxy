"""
MCP Proxy - A reusable module for managing multiple MCP servers

This package provides a proxy server that can manage multiple MCP (Model Context Protocol)
servers with access control, whitelisting/blacklisting, and automatic server lifecycle
management. It supports generating configurations for various AI clients like Gemini CLI.

Main classes:
- MCPProxy: The main proxy server class
- MCPServerConfig: Configuration dataclass for individual MCP servers

Example usage:
    from mcp_proxy import MCPProxy, MCPServerConfig

    # Create proxy
    proxy = MCPProxy("my-proxy")

    # Add servers
    proxy.add_server(MCPServerConfig(
        name="playwright",
        command="npx",
        args=["@playwright/mcp@latest"],
        auto_start=True
    ))

    # Start and generate config for Gemini
    config_file = proxy.startup_with_config("gemini")
"""

__version__ = "1.0.0"
__author__ = "MCP Proxy Contributors"
__email__ = "vjvsp@yahoo.de"
__description__ = "A reusable module for managing multiple MCP servers with access control and automatic configuration generation"

# Import main classes for easy access
from .proxy import MCPProxy, MCPServerConfig

# Import config generators for advanced usage
from .config_generators import (
    BaseConfigGenerator,
    GeminiConfigGenerator,
    ClaudeConfigGenerator,
)


# Import Python MCP server functionality
from .python_mcp import BaseMCP, PythonMCPServer, expose_tool

__all__ = [
    "MCPProxy",
    "MCPServerConfig",
    "BaseConfigGenerator",
    "GeminiConfigGenerator",
    "ClaudeConfigGenerator",
    "BaseMCP",
    "PythonMCPServer",
    "expose_tool",
]
