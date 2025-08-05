"""
Claude CLI Config Generator (Template)

This is a template/example for how to add a new config generator for Claude CLI.
Since Claude CLI doesn't exist yet, this serves as an example of the extensibility.
"""

import json
from pathlib import Path
from typing import Dict, Any

from .base import BaseConfigGenerator


class ClaudeConfigGenerator(BaseConfigGenerator):
    """
    Config generator for Claude CLI (hypothetical/future).

    This serves as an example of how easy it is to add new config generators
    by inheriting from the BaseConfigGenerator abstract class.
    """

    @property
    def client_type(self) -> str:
        """Return the client type identifier"""
        return "claude"

    def generate_config(self) -> Dict[str, Any]:
        """
        Generate Claude CLI compatible MCP configuration.

        Each individual MCP server appears as a separate entry in the config,
        connecting to its own dedicated socket. This ensures proper routing
        of requests to the correct server.

        Note: This is a hypothetical format since Claude CLI doesn't exist yet.
        This demonstrates how easy it would be to add support for new clients.

        Returns:
            Dict containing the Claude-compatible configuration
        """
        mcp_servers = {}

        # Create an entry for each individual server with its own socket
        for server_name, server_config in self.servers.items():
            # Get the server-specific socket path
            server_socket_path = self.temp_dir / f"{server_name}.sock"

            mcp_servers[server_name] = {
                "transport": "unix_socket",
                "socket_path": str(server_socket_path),
                "protocol": "stdio",
            }

        # If no servers are configured, create a default proxy entry
        if not mcp_servers:
            mcp_servers[self.proxy_name] = {
                "transport": "unix_socket",
                "socket_path": str(self.socket_path),
                "protocol": "stdio",
            }

        return {"mcp_servers": mcp_servers}  # Hypothetical Claude format

    def create_temp_config(self) -> Path:
        """
        Create a temporary configuration file for Claude CLI.

        Returns:
            Path to the created configuration file
        """
        self._ensure_temp_dir_exists()

        config = self.generate_config()
        config_file = self.get_config_file_path()

        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)

        return config_file
