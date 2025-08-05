"""
Gemini CLI Config Generator

Generates configuration files and launcher scripts for the Gemini CLI tool.
"""

import json
from pathlib import Path
from typing import Dict, Any

from .base import BaseConfigGenerator


class GeminiConfigGenerator(BaseConfigGenerator):
    """
    Config generator for Gemini CLI.

    Creates MCP server configurations compatible with the Gemini CLI tool,
    using socat to proxy connections through Unix sockets.
    """

    @property
    def client_type(self) -> str:
        """Return the client type identifier"""
        return "gemini"

    def generate_config(self) -> Dict[str, Any]:
        """
        Generate Gemini CLI compatible MCP configuration using socat proxy.

        Each individual MCP server appears as a separate entry in the config,
        connecting to its own dedicated socket. This ensures proper routing
        of requests to the correct server.

        Returns:
            Dict containing the Gemini-compatible configuration
        """
        mcp_servers = {}

        # Create an entry for each individual server with its own socket
        for server_name, server_config in self.servers.items():
            # Get the server-specific socket path
            server_socket_path = self.temp_dir / f"{server_name}.sock"

            mcp_servers[server_name] = {
                "command": self._resolve_socat_path(),
                "args": ["STDIO", f"UNIX-CONNECT:{server_socket_path}"],
            }

        # If no servers are configured, create a default proxy entry
        if not mcp_servers:
            mcp_servers[self.proxy_name] = {
                "command": self._resolve_socat_path(),
                "args": ["STDIO", f"UNIX-CONNECT:{self.socket_path}"],
            }

        return {"mcpServers": mcp_servers}

    def _resolve_socat_path(self) -> str:
        """Resolve absolute path to socat if possible, fallback to 'socat'."""
        try:
            from shutil import which

            path = which("socat")
            return path or "socat"
        except Exception:
            return "socat"

    def create_temp_config(self) -> Path:
        """
        Create a temporary configuration file for Gemini CLI.

        Returns:
            Path to the created configuration file
        """
        self._ensure_temp_dir_exists()

        config = self.generate_config()
        config_file = self.get_config_file_path()

        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)

        return config_file
