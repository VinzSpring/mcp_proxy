"""
Standalone MCP Proxy Module

A reusable module for managing multiple MCP servers with access control,
whitelisting/blacklisting, and automatic server lifecycle management.
"""

import subprocess
import json
import tempfile
import time
import shlex
import logging
import os
import socket
import threading
import select
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field

from .config_generators import (
    BaseConfigGenerator,
    GeminiConfigGenerator,
    ClaudeConfigGenerator,
)

from .python_mcp import BaseMCP, PythonMCPServer


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server"""

    name: str
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    cwd: str = "."
    whitelist: Optional[List[str]] = None
    blacklist: Optional[List[str]] = None
    auto_start: bool = True
    python_mcp: Optional[BaseMCP] = None  # For Python-based MCP servers
    inherit_env: bool = False
    intercept_before: Optional[
        Dict[str, Callable[[Dict[str, Any], str, str], Optional[Dict[str, Any]]]]
    ] = None
    intercept_after: Optional[
        Dict[
            str,
            Callable[
                [Dict[str, Any], Dict[str, Any], str, str], Optional[Dict[str, Any]]
            ],
        ]
    ] = None

    def __post_init__(self):
        """Validate configuration after initialization"""
        if self.python_mcp is None and self.command is None:
            raise ValueError("Either command or python_mcp must be provided")
        if self.python_mcp is not None and self.command is not None:
            raise ValueError("Cannot specify both command and python_mcp")

        # Initialize interceptor dictionaries if not provided
        if self.intercept_before is None:
            self.intercept_before = {}
        if self.intercept_after is None:
            self.intercept_after = {}

    @property
    def is_python_mcp(self) -> bool:
        """Check if this is a Python MCP server"""
        return self.python_mcp is not None


class MCPProxy:
    """
    Standalone MCP Proxy that manages multiple MCP servers

    Features:
    - Multiple MCP server management
    - Access control via whitelist/blacklist
    - Automatic server lifecycle management
    - Unix socket proxy server
    - JSON-RPC message forwarding and filtering
    - Integration with various AI clients (Gemini CLI, etc.)
    """

    def __init__(self, name: str = "mcp-proxy"):
        self.name = name
        self.servers: Dict[str, MCPServerConfig] = {}
        self.active_processes: Dict[str, subprocess.Popen] = {}
        self.python_servers: Dict[str, PythonMCPServer] = {}
        self.temp_dir: Optional[Path] = None
        self.socket_path: Optional[Path] = None
        # Multi-socket support: each server gets its own socket
        self.server_sockets: Dict[str, Path] = {}
        self.server_listeners: Dict[str, socket.socket] = {}
        self.server_threads: Dict[str, threading.Thread] = {}
        self.proxy_server: Optional[socket.socket] = None
        self.proxy_thread: Optional[threading.Thread] = None
        self.running = False
        self.logger = logging.getLogger(f"{__name__}.{name}")
        self.max_connections: int = 100
        self.max_message_bytes: int = 1024 * 1024  # 1 MiB per line/message
        self.connection_semaphore = threading.BoundedSemaphore(self.max_connections)

        # Set up logging
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                f"%(asctime)s - {name.upper()} - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def add_server(self, config: MCPServerConfig):
        """Add an MCP server configuration"""
        self.servers[config.name] = config
        self.logger.info(f"Added MCP server: {config.name}")

    def _build_subprocess_env(self, config: MCPServerConfig) -> Optional[Dict[str, str]]:
        """Build an environment for external subprocesses."""
        base_env: Dict[str, str]
        if config.inherit_env:
            base_env = dict(os.environ)
        else:
            base_env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
                "LANG": os.environ.get("LANG", "C.UTF-8"),
            }
        if config.env:
            base_env.update(config.env)
        return base_env

    def _log_received_message(self, server_name: Optional[str], raw_message: Dict[str, Any]) -> None:
        """Log a redacted view of an incoming message at DEBUG level.

        - Only logs method and, for tools/call, the tool name.
        - Avoids leaking arguments or sensitive params at INFO level.
        """
        method = raw_message.get("method")
        params = raw_message.get("params", {}) if isinstance(raw_message, dict) else {}
        suffix = f" for {server_name}" if server_name else ""
        if method == "tools/call":
            tool_name = params.get("name")
            self.logger.debug(f"Received tools/call{suffix}: tool={tool_name}")
        else:
            self.logger.debug(f"Received method{suffix}: {method}")

    def _process_server_interceptors_before(
        self, request: Dict[str, Any], server_name: str, tool_name: str
    ) -> Optional[Dict[str, Any]]:
        """Process per-server before interceptors"""
        if server_name not in self.servers:
            return request

        config = self.servers[server_name]
        if not config.intercept_before:
            return request

        current_request = request

        # Check for specific tool interceptor first
        if tool_name in config.intercept_before:
            try:
                interceptor = config.intercept_before[tool_name]
                current_request = interceptor(current_request, server_name, tool_name)
                if current_request is None:
                    self.logger.warning(
                        f"Interceptor blocked tool call {server_name}.{tool_name}"
                    )
                    return None
            except Exception as e:
                self.logger.error(
                    f"Error in before interceptor for {server_name}.{tool_name}: {e}"
                )
                return None

        # Check for wildcard interceptor
        if "*" in config.intercept_before:
            try:
                interceptor = config.intercept_before["*"]
                current_request = interceptor(current_request, server_name, tool_name)
                if current_request is None:
                    self.logger.warning(
                        f"Wildcard interceptor blocked tool call {server_name}.{tool_name}"
                    )
                    return None
            except Exception as e:
                self.logger.error(
                    f"Error in wildcard before interceptor for {server_name}.{tool_name}: {e}"
                )
                return None

        return current_request

    def _process_server_interceptors_after(
        self,
        request: Dict[str, Any],
        response: Dict[str, Any],
        server_name: str,
        tool_name: str,
    ) -> Optional[Dict[str, Any]]:
        """Process per-server after interceptors"""
        if server_name not in self.servers:
            return response

        config = self.servers[server_name]
        if not config.intercept_after:
            return response

        current_response = response

        # Check for specific tool interceptor first
        if tool_name in config.intercept_after:
            try:
                interceptor = config.intercept_after[tool_name]
                current_response = interceptor(
                    request, current_response, server_name, tool_name
                )
                if current_response is None:
                    self.logger.warning(
                        f"Interceptor blocked response for {server_name}.{tool_name}"
                    )
                    return None
            except Exception as e:
                self.logger.error(
                    f"Error in after interceptor for {server_name}.{tool_name}: {e}"
                )
                return None

        # Check for wildcard interceptor
        if "*" in config.intercept_after:
            try:
                interceptor = config.intercept_after["*"]
                current_response = interceptor(
                    request, current_response, server_name, tool_name
                )
                if current_response is None:
                    self.logger.warning(
                        f"Wildcard interceptor blocked response for {server_name}.{tool_name}"
                    )
                    return None
            except Exception as e:
                self.logger.error(
                    f"Error in wildcard after interceptor for {server_name}.{tool_name}: {e}"
                )
                return None

        return current_response

    def add_python_server(
        self,
        mcp_instance: BaseMCP,
        whitelist: Optional[List[str]] = None,
        blacklist: Optional[List[str]] = None,
    ) -> None:
        """
        Add a Python-based MCP server.

        Args:
            mcp_instance: Instance of a class that inherits from BaseMCP
            whitelist: Optional list of allowed tools
            blacklist: Optional list of blocked tools
        """
        config = MCPServerConfig(
            name=mcp_instance.name,
            python_mcp=mcp_instance,
            whitelist=whitelist,
            blacklist=blacklist,
            auto_start=True,
        )
        self.add_server(config)

    def add_server_from_dict(self, name: str, server_dict: Dict[str, Any]):
        """Add MCP server from dictionary configuration"""
        if "start" in server_dict:
            command_str = server_dict["start"]
        elif "command" in server_dict and "args" in server_dict:
            command_str = server_dict["command"] + " " + " ".join(server_dict["args"])
        else:
            raise ValueError(
                f"Invalid server configuration for {name}: missing 'start' or 'command'+'args'"
            )

        command_parts = shlex.split(command_str)
        if not command_parts:
            raise ValueError(
                f"Invalid or empty command for server {name}: '{command_str}'"
            )

        config = MCPServerConfig(
            name=name,
            command=command_parts[0],
            args=command_parts[1:],
            env=server_dict.get("env", {}),
            cwd=server_dict.get("cwd", "."),
            whitelist=server_dict.get("whitelist"),
            blacklist=server_dict.get("blacklist"),
            auto_start=server_dict.get("auto_start", True),
            inherit_env=server_dict.get("inherit_env", False),
        )
        self.add_server(config)

    def load_config(self, config_data: Dict[str, Any]):
        """Load multiple MCP servers from configuration data"""
        mcp_servers = config_data.get("mcpServers", {})
        for server_name, server_config in mcp_servers.items():
            try:
                self.add_server_from_dict(server_name, server_config)
            except Exception as e:
                self.logger.error(f"Failed to add server {server_name}: {e}")

    def is_tool_allowed(self, server_name: str, tool_name: str) -> bool:
        """Check if a tool is allowed based on whitelist/blacklist"""
        if server_name not in self.servers:
            return False

        config = self.servers[server_name]

        # Check blacklist first
        if config.blacklist and tool_name in config.blacklist:
            self.logger.warning(
                f"Tool {tool_name} blocked by blacklist for {server_name}"
            )
            return False

        # Check whitelist if present
        if config.whitelist and tool_name not in config.whitelist:
            self.logger.warning(f"Tool {tool_name} not in whitelist for {server_name}")
            return False

        return True

    def start_server(self, server_name: str) -> bool:
        """Start an MCP server (external process or Python-based)"""
        if server_name not in self.servers:
            self.logger.error(f"Unknown server: {server_name}")
            return False

        config = self.servers[server_name]

        # Handle Python MCP servers
        if config.is_python_mcp:
            if server_name in self.python_servers:
                self.logger.info(f"Python MCP server {server_name} already running")
                return True

            try:
                python_server = PythonMCPServer(config.python_mcp)
                self.python_servers[server_name] = python_server
                self.logger.info(
                    f"Successfully started Python MCP server: {server_name}"
                )
                return True
            except Exception as e:
                self.logger.error(
                    f"Error starting Python MCP server {server_name}: {e}"
                )
                return False

        # Handle external process servers
        # Check if already running
        if server_name in self.active_processes:
            proc = self.active_processes[server_name]
            if proc.poll() is None:
                self.logger.info(f"Server {server_name} already running")
                return True
            else:
                # Process died, remove it
                del self.active_processes[server_name]

        try:
            cmd = [config.command] + config.args
            env = self._build_subprocess_env(config)

            self.logger.info(f"Starting MCP server: {server_name}")
            self.logger.debug(f"Command: {' '.join(cmd)}")

            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                cwd=config.cwd,
            )

            # Wait briefly for startup
            time.sleep(1)

            if process.poll() is None:
                self.active_processes[server_name] = process
                self.logger.info(f"Successfully started MCP server: {server_name}")
                return True
            else:
                stdout, stderr = process.communicate()
                self.logger.error(f"Failed to start {server_name}: {stderr}")
                return False

        except Exception as e:
            self.logger.error(f"Error starting server {server_name}: {e}")
            return False

    def stop_server(self, server_name: str):
        """Stop an MCP server (external process or Python-based)"""
        # Stop Python MCP server
        if server_name in self.python_servers:
            del self.python_servers[server_name]
            self.logger.info(f"Stopped Python MCP server: {server_name}")
            return

        # Stop external process server
        if server_name not in self.active_processes:
            return

        process = self.active_processes[server_name]
        try:
            process.terminate()
            time.sleep(1)
            if process.poll() is None:
                process.kill()
            del self.active_processes[server_name]
            self.logger.info(f"Stopped MCP server: {server_name}")
        except Exception as e:
            self.logger.error(f"Error stopping server {server_name}: {e}")

    def stop_all_servers(self):
        """Stop all active MCP servers"""
        # Stop external process servers
        for server_name in list(self.active_processes.keys()):
            self.stop_server(server_name)

        # Stop Python MCP servers
        for server_name in list(self.python_servers.keys()):
            self.stop_server(server_name)

    def start_proxy_server(self) -> bool:
        """Start Unix socket servers for each MCP server"""
        if self.running:
            self.logger.info("Proxy servers already running")
            return True

        if not self.temp_dir:
            self.temp_dir = Path(tempfile.mkdtemp(prefix=f"{self.name}_"))

        # Set running flag BEFORE creating threads
        self.running = True

        # Create a socket for each server
        for server_name in self.servers.keys():
            socket_path = self.temp_dir / f"{server_name}.sock"
            self.server_sockets[server_name] = socket_path

            # Remove existing socket file if it exists
            if socket_path.exists():
                socket_path.unlink()

            try:
                server_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server_listener.bind(str(socket_path))
                server_listener.listen(5)
                self.server_listeners[server_name] = server_listener

                # Start a thread for this server's socket
                thread = threading.Thread(
                    target=self._server_socket_loop,
                    args=(server_name, server_listener),
                    daemon=True,
                )
                thread.start()
                self.server_threads[server_name] = thread

                self.logger.info(
                    f"Socket server started for {server_name} on: {socket_path}"
                )

            except Exception as e:
                self.logger.error(
                    f"Failed to start socket server for {server_name}: {e}"
                )
                self.stop_proxy_server()
                return False

        # Keep legacy socket_path for backward compatibility
        if self.server_sockets:
            self.socket_path = next(iter(self.server_sockets.values()))

        return True

    def stop_proxy_server(self):
        """Stop all proxy servers"""
        self.running = False

        # Close all server listeners
        for server_name, listener in self.server_listeners.items():
            try:
                listener.close()
            except Exception as e:
                self.logger.error(f"Error closing listener for {server_name}: {e}")

        # Remove all socket files
        for server_name, socket_path in self.server_sockets.items():
            if socket_path.exists():
                try:
                    socket_path.unlink()
                except Exception as e:
                    self.logger.error(
                        f"Error removing socket file for {server_name}: {e}"
                    )

        # Wait for all threads to finish
        for server_name, thread in self.server_threads.items():
            if thread.is_alive():
                thread.join(timeout=10)

        # Clear all socket data
        self.server_listeners.clear()
        self.server_sockets.clear()
        self.server_threads.clear()

        # Legacy cleanup
        if self.proxy_server:
            try:
                self.proxy_server.close()
            except Exception as e:
                self.logger.error(f"Error closing proxy server: {e}")
            self.proxy_server = None

        if self.proxy_thread and self.proxy_thread.is_alive():
            self.proxy_thread.join(timeout=10)

        self.logger.info("All proxy servers stopped")

    def _proxy_server_loop(self):
        """Main proxy server loop"""
        while self.running:
            try:
                client_socket, addr = self.proxy_server.accept()
                self.logger.info(f"Client connected: {addr}")

                # Handle client in a separate thread
                client_thread = threading.Thread(
                    target=self._handle_client, args=(client_socket,), daemon=True
                )
                client_thread.start()

            except Exception as e:
                if self.running:
                    self.logger.error(f"Error accepting client connection: {e}")
                break

    def _server_socket_loop(self, server_name: str, server_listener: socket.socket):
        """Socket loop for a specific MCP server"""
        try:
            self.logger.info(f"Starting socket loop for {server_name}")
            while self.running:
                try:
                    client_socket, addr = server_listener.accept()
                    self.logger.info(f"Client connected to {server_name}: {addr}")

                    # Handle client in a separate thread, passing the server name
                    client_thread = threading.Thread(
                        target=self._handle_client_for_server,
                        args=(client_socket, server_name),
                        daemon=True,
                    )
                    client_thread.start()

                except Exception as e:
                    if self.running:
                        self.logger.error(
                            f"Error accepting client connection for {server_name}: {e}"
                        )
                    break
        except Exception as e:
            self.logger.error(
                f"Fatal error in socket loop for {server_name}: {e}", exc_info=True
            )

    def _handle_client(self, client_socket: socket.socket):
        """Handle a single client connection"""
        try:
            if not self.connection_semaphore.acquire(blocking=False):
                try:
                    client_socket.close()
                finally:
                    self.logger.warning("Connection refused: too many concurrent clients")
                return
            self.logger.debug("Setting up client communication...")
            # Set up communication with client
            client_file = client_socket.makefile("rw")

            self.logger.debug("Starting client message loop...")
            while self.running:
                try:
                    # Read JSON-RPC message from client
                    self.logger.debug("Waiting for client message...")
                    line = client_file.readline()
                    if line and len(line.encode("utf-8", errors="ignore")) > self.max_message_bytes:
                        self.logger.warning("Dropping oversized client message")
                        break

                    if not line:
                        self.logger.debug("Empty line received, client disconnected")
                        break

                    message = json.loads(line.strip())
                    self._log_received_message(None, message)

                    # Route and forward the message
                    self.logger.debug("Routing message...")
                    response = self._route_message(message)

                    if response:
                        response_line = json.dumps(response) + "\n"
                        client_file.write(response_line)
                        client_file.flush()
                        self.logger.debug("Sent response to client")
                    else:
                        self.logger.debug("No response to send")

                except json.JSONDecodeError as e:
                    self.logger.error(
                        f"Invalid JSON from client: {e}, data: {repr(line)}"
                    )
                    break
                except Exception as e:
                    self.logger.error(f"Error handling client message: {e}")
                    import traceback

                    traceback.print_exc()
                    break

        except Exception as e:
            self.logger.error(f"Error in client handler: {e}")
            import traceback

            traceback.print_exc()
        finally:
            try:
                client_socket.close()
            except:
                pass
            try:
                self.connection_semaphore.release()
            except Exception:
                pass
            self.logger.info("Client disconnected")

    def _handle_client_for_server(self, client_socket: socket.socket, server_name: str):
        """Handle a client connection for a specific MCP server"""
        try:
            if not self.connection_semaphore.acquire(blocking=False):
                try:
                    client_socket.close()
                finally:
                    self.logger.warning(f"Connection refused for {server_name}: too many concurrent clients")
                return
            self.logger.debug(
                f"Setting up client communication for server: {server_name}"
            )
            # Set up communication with client
            client_file = client_socket.makefile("rw")

            self.logger.debug(f"Starting client message loop for server: {server_name}")
            while self.running:
                try:
                    # Read JSON-RPC message from client
                    self.logger.debug(
                        f"Waiting for client message for server: {server_name}"
                    )
                    line = client_file.readline()
                    if line and len(line.encode("utf-8", errors="ignore")) > self.max_message_bytes:
                        self.logger.warning(f"Dropping oversized message for {server_name}")
                        break
                    self.logger.debug(
                        f"Read line from client for {server_name}: {repr(line)}"
                    )

                    if not line:
                        self.logger.debug(
                            f"Empty line received, client disconnected from {server_name}"
                        )
                        break

                    message = json.loads(line.strip())
                    self._log_received_message(server_name, message)

                    # Route message to the specific server
                    self.logger.debug(f"Routing message to server: {server_name}")

                    # For tools/list, only return tools from this specific server
                    if message.get("method") == "tools/list":
                        response = self._handle_tools_list_for_server(
                            message, server_name
                        )
                    elif message.get("method") == "tools/call":
                        # Route tool calls directly to this server
                        response = self._route_tool_call_to_server(message, server_name)
                    elif message.get("method") == "initialize":
                        # Initialize just this server
                        response = self._handle_initialize_for_server(
                            message, server_name
                        )
                    else:
                        # Forward other messages directly to this server
                        response = self._forward_to_server(server_name, message)

                    if response:
                        response_line = json.dumps(response) + "\n"
                        client_file.write(response_line)
                        client_file.flush()
                        self.logger.debug(
                            f"Sent response to client from {server_name}"
                        )
                    else:
                        self.logger.debug(
                            f"No response to send from {server_name} (likely a notification)"
                        )

                except json.JSONDecodeError as e:
                    self.logger.error(
                        f"Invalid JSON from client for {server_name}: {e}, data: {repr(line)}"
                    )
                    break
                except Exception as e:
                    self.logger.error(
                        f"Error handling client message for {server_name}: {e}"
                    )
                    import traceback

                    traceback.print_exc()
                    break

        except Exception as e:
            self.logger.error(f"Error in client handler for {server_name}: {e}")
            import traceback

            traceback.print_exc()
        finally:
            try:
                client_socket.close()
            except:
                pass
            try:
                self.connection_semaphore.release()
            except Exception:
                pass
            self.logger.info(f"Client disconnected from {server_name}")

    def _route_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Route a JSON-RPC message to the appropriate MCP server"""
        # Validate incoming message
        if not self._is_valid_jsonrpc_message(message):
            return self._create_error_response(message, -32600, "Invalid Request")

        method = message.get("method")
        params = message.get("params", {})

        # Check if this is a notification (no id field)
        is_notification = "id" not in message

        # Handle notifications - they don't expect responses
        if is_notification:
            self.logger.info(f"Received notification: {method}")

            # Some notifications we handle locally
            if method == "notifications/initialized":
                # Client has initialized, we can ignore this
                self.logger.info("Client initialized notification received")
                return None  # No response for notifications

            if method == "tools/call":
                self.logger.warning("Blocked tools/call notification")
                return None

            # Forward other notifications to servers without expecting response
            if self.servers:
                for server_name in self.servers.keys():
                    if server_name in self.active_processes:
                        try:
                            process = self.active_processes[server_name]
                            notification_line = json.dumps(message) + "\n"
                            process.stdin.write(notification_line)
                            process.stdin.flush()
                            self.logger.debug(
                                f"Forwarded notification to {server_name}"
                            )
                        except Exception as e:
                            self.logger.error(
                                f"Error forwarding notification to {server_name}: {e}"
                            )

            return None  # No response for notifications

        # Handle requests (messages with id field)
        # Handle initialization
        if method == "initialize":
            return self._handle_initialize(message)

        # Handle tools/list - this is what Gemini calls to discover tools
        if method == "tools/list":
            return self._handle_tools_list(message)

        # Handle tool calls
        if method == "tools/call":
            tool_name = params.get("name")
            if not tool_name:
                return self._create_error_response(message, -32602, "Missing tool name")

            # Check access control for all servers
            allowed_servers = []
            for server_name in self.servers.keys():
                if self.is_tool_allowed(server_name, tool_name):
                    allowed_servers.append(server_name)

            if not allowed_servers:
                self.logger.warning(f"Tool {tool_name} not allowed on any server")
                return self._create_error_response(
                    message, -32001, f"Tool {tool_name} not allowed"
                )

            # Select target server (first allowed server)
            target_server = allowed_servers[0]

            # Process per-server interceptors before tool call
            processed_request = self._process_server_interceptors_before(
                message, target_server, tool_name
            )
            if processed_request is None:
                # Server interceptor blocked the call
                return self._create_error_response(
                    message, -32001, f"Tool call blocked by interceptor"
                )

            # Forward to server and get response
            response = self._forward_to_server(target_server, processed_request)
            if response is None:
                return self._create_error_response(
                    message, -32003, "No response from server"
                )

            # Process per-server interceptors after tool call
            processed_response = self._process_server_interceptors_after(
                processed_request, response, target_server, tool_name
            )
            if processed_response is None:
                # Server interceptor blocked the response
                return self._create_error_response(
                    message, -32001, f"Response blocked by interceptor"
                )

            return processed_response

        # Handle other methods - forward to first available server
        if self.servers:
            first_server = next(iter(self.servers.keys()))
            return self._forward_to_server(first_server, message)

        return self._create_error_response(message, -32001, "No servers available")

    def _is_valid_jsonrpc_message(self, message: Dict[str, Any]) -> bool:
        """Validate that a message conforms to JSON-RPC 2.0 specification"""
        if not isinstance(message, dict):
            return False

        # Must have jsonrpc field set to "2.0"
        if message.get("jsonrpc") != "2.0":
            return False

        # Must have either method (for requests) or result/error (for responses)
        has_method = "method" in message
        has_result = "result" in message
        has_error = "error" in message

        if has_method:
            # This is a request
            if has_result or has_error:
                return False  # Request shouldn't have result or error
        else:
            # This is a response
            if not (has_result or has_error):
                return False  # Response must have either result or error
            if has_result and has_error:
                return False  # Can't have both result and error

        return True

    def _handle_initialize(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP initialize request"""
        return {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": self.name, "version": "1.0.0"},
            },
        }

    def _handle_initialize_for_server(
        self, message: Dict[str, Any], server_name: str
    ) -> Dict[str, Any]:
        """Handle initialize request for a specific server"""
        # Forward initialize to the specific server
        server_response = self._forward_to_server(server_name, message)

        if server_response and "result" in server_response:
            # Return the server's response directly
            return server_response
        else:
            # Return a default response if server doesn't respond properly
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": server_name, "version": "1.0.0"},
                },
            }

    def _handle_tools_list(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/list request by aggregating tools from all servers"""
        all_tools = []

        for server_name, config in self.servers.items():
            # Check if server is running (either external process or Python server)
            if (
                server_name in self.active_processes
                or server_name in self.python_servers
            ):
                try:
                    # Forward tools/list to each server and collect results
                    server_response = self._forward_to_server(server_name, message)
                    if server_response and "result" in server_response:
                        tools = server_response["result"].get("tools", [])
                        # Filter tools based on access control
                        filtered_tools = []
                        for tool in tools:
                            tool_name = tool.get("name")
                            if tool_name and self.is_tool_allowed(
                                server_name, tool_name
                            ):
                                filtered_tools.append(tool)
                        all_tools.extend(filtered_tools)
                except Exception as e:
                    self.logger.error(f"Error getting tools from {server_name}: {e}")

        return {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {"tools": all_tools},
        }

    def _handle_tools_list_for_server(
        self, message: Dict[str, Any], server_name: str
    ) -> Dict[str, Any]:
        """Handle tools/list request for a specific server"""
        # Forward tools/list to the specific server
        server_response = self._forward_to_server(server_name, message)

        if server_response and "result" in server_response:
            tools = server_response["result"].get("tools", [])
            # Filter tools based on access control
            filtered_tools = []
            for tool in tools:
                tool_name = tool.get("name")
                if tool_name and self.is_tool_allowed(server_name, tool_name):
                    filtered_tools.append(tool)
                elif tool_name:
                    self.logger.warning(
                        f"Tool {tool_name} not in whitelist for {server_name}"
                    )

            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "result": {"tools": filtered_tools},
            }
        else:
            # Return empty tools list if server doesn't respond
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "result": {"tools": []},
            }

    def _route_tool_call_to_server(
        self, message: Dict[str, Any], server_name: str
    ) -> Optional[Dict[str, Any]]:
        """Route a tool call to a specific server"""
        params = message.get("params", {})
        tool_name = params.get("name")

        if not tool_name:
            return self._create_error_response(message, -32602, "Missing tool name")

        # Check if tool is allowed on this server
        if not self.is_tool_allowed(server_name, tool_name):
            self.logger.warning(f"Tool {tool_name} not allowed on server {server_name}")
            return self._create_error_response(
                message, -32001, f"Tool {tool_name} not allowed"
            )

        # Process per-server interceptors before tool call
        processed_request = self._process_server_interceptors_before(
            message, server_name, tool_name
        )
        if processed_request is None:
            # Server interceptor blocked the call
            return self._create_error_response(
                message, -32001, f"Tool call blocked by interceptor"
            )

        # Forward to server and get response
        response = self._forward_to_server(server_name, processed_request)
        if response is None:
            return self._create_error_response(
                message, -32003, "No response from server"
            )

        # Process per-server interceptors after tool call
        processed_response = self._process_server_interceptors_after(
            processed_request, response, server_name, tool_name
        )
        if processed_response is None:
            # Server interceptor blocked the response
            return self._create_error_response(
                message, -32001, f"Response blocked by interceptor"
            )

        return processed_response

    def _forward_to_server(
        self, server_name: str, message: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Forward a message to a specific MCP server (external process or Python-based)"""
        # Handle Python MCP servers
        if server_name in self.python_servers:
            python_server = self.python_servers[server_name]
            try:
                # Ensure message has proper JSON-RPC structure
                if not self._is_valid_jsonrpc_message(message):
                    self.logger.error(
                        f"Invalid JSON-RPC message being forwarded to {server_name}: {message}"
                    )
                    return self._create_error_response(
                        message, -32600, "Invalid Request"
                    )

                # Handle request directly
                response = python_server.handle_request(message)

                # Validate server response
                if not self._is_valid_jsonrpc_response(response):
                    self.logger.error(
                        f"Invalid JSON-RPC response from Python server {server_name}: {response}"
                    )
                    return self._create_error_response(
                        message, -32603, "Internal error"
                    )
                req_id = message.get("id")
                if req_id is not None and response.get("id") != req_id:
                    self.logger.error(
                        f"Mismatched response id from Python server {server_name}: got {response.get('id')} expected {req_id}"
                    )
                    return self._create_error_response(
                        message, -32603, "Internal error"
                    )
                return response

            except Exception as e:
                self.logger.error(f"Error calling Python MCP server {server_name}: {e}")
                return self._create_error_response(
                    message, -32003, f"Python server error: {e}"
                )

        # Handle external process servers
        if server_name not in self.active_processes:
            return self._create_error_response(
                message, -32001, f"Server {server_name} not running"
            )

        process = self.active_processes[server_name]

        try:
            # Ensure message has proper JSON-RPC structure
            if not self._is_valid_jsonrpc_message(message):
                self.logger.error(
                    f"Invalid JSON-RPC message being forwarded to {server_name}: {message}"
                )
                return self._create_error_response(message, -32600, "Invalid Request")

            # Send message to server
            message_line = json.dumps(message) + "\n"
            process.stdin.write(message_line)
            process.stdin.flush()

            # Read response from server with timeout
            response = self._read_server_response_with_timeout(process, timeout=30.0)
            if response:
                if not self._is_valid_jsonrpc_response(response):
                    self.logger.error(
                        f"Invalid JSON-RPC response from {server_name}: {response}"
                    )
                    return self._create_error_response(
                        message, -32603, "Internal error"
                    )
                req_id = message.get("id")
                if req_id is not None and response.get("id") != req_id:
                    self.logger.error(
                        f"Mismatched response id from {server_name}: got {response.get('id')} expected {req_id}"
                    )
                    return self._create_error_response(
                        message, -32603, "Internal error"
                    )
                return response
            else:
                return self._create_error_response(
                    message, -32003, "No response from server (timeout)"
                )

        except Exception as e:
            self.logger.error(f"Error forwarding to server {server_name}: {e}")
            return self._create_error_response(
                message, -32003, f"Server communication error: {e}"
            )

    def _is_valid_jsonrpc_response(self, message: Dict[str, Any]) -> bool:
        """Validate that a response conforms to JSON-RPC 2.0 specification"""
        if not isinstance(message, dict):
            return False

        # Must have jsonrpc field set to "2.0"
        if message.get("jsonrpc") != "2.0":
            return False

        # Must have id field
        if "id" not in message:
            return False

        # Must have either result or error, but not both
        has_result = "result" in message
        has_error = "error" in message

        if not (has_result or has_error):
            return False

        if has_result and has_error:
            return False

        return True

    def _read_server_response_with_timeout(
        self, process: subprocess.Popen, timeout: float = 30.0
    ) -> Optional[Dict[str, Any]]:
        """Read response from server with timeout using select"""
        try:
            # Use select to check if stdout has data available
            ready, _, _ = select.select([process.stdout], [], [], timeout)

            if ready:
                # Data is available, read it
                response_line = process.stdout.readline()
                if response_line:
                    response = json.loads(response_line.strip())
                    self.logger.debug(f"Received response from server: {response}")
                    return response
            else:
                # Timeout occurred
                self.logger.warning(
                    f"Timeout waiting for server response after {timeout} seconds"
                )
                return None

        except Exception as e:
            self.logger.error(f"Error reading server response: {e}")
            return None

    def _create_error_response(
        self, original_message: Dict[str, Any], code: int, message: str
    ) -> Dict[str, Any]:
        """Create a JSON-RPC error response"""
        # Get the id from the original message, default to None if not present
        message_id = original_message.get("id") if original_message else None

        # If there's no id (it's a notification), we shouldn't send an error response
        if message_id is None:
            self.logger.warning(
                f"Cannot create error response for notification: {message}"
            )
            return None

        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "error": {"code": code, "message": message},
        }

    def get_config_generator(self, client_type: str = "gemini") -> BaseConfigGenerator:
        """Get a config generator for a specific AI client"""
        if not self.socket_path:
            # Start proxy server if not already running
            if not self.start_proxy_server():
                raise RuntimeError("Failed to start proxy server")

        if not self.temp_dir:
            self.temp_dir = Path(tempfile.mkdtemp(prefix=f"{self.name}_"))

        if client_type == "gemini":
            return GeminiConfigGenerator(
                self.name, self.socket_path, self.temp_dir, self.servers
            )
        elif client_type == "claude":
            return ClaudeConfigGenerator(
                self.name, self.socket_path, self.temp_dir, self.servers
            )
        else:
            raise ValueError(f"Unsupported client type: {client_type}")

    def generate_client_config(self, client_type: str = "gemini") -> Dict[str, Any]:
        """Generate configuration for a specific AI client"""
        generator = self.get_config_generator(client_type)
        return generator.generate_config()

    def create_temp_config(self, client_type: str = "gemini") -> Path:
        """Create a temporary configuration file for the client"""
        generator = self.get_config_generator(client_type)
        config_file = generator.create_temp_config()
        self.logger.info(f"Created temp config: {config_file}")
        return config_file

    def auto_start_servers(self):
        """Start all servers marked for auto-start and the proxy server"""
        # IMPORTANT: Start the proxy server FIRST to create all sockets
        # This must happen before starting individual servers so that
        # the sockets are available when clients try to connect
        self.start_proxy_server()

        # Now start individual MCP servers
        for server_name, config in self.servers.items():
            if config.auto_start:
                self.start_server(server_name)

    def startup_with_config(
        self, client_type: str = "gemini", config_path: Optional[Path] = None
    ) -> Optional[Path]:
        """
        Start the proxy and generate configuration for the specified client.

        This is the main method library users should call to start the proxy
        and get a configuration file for their AI client.

        Args:
            client_type: Type of AI client ("gemini", "claude", etc.)
            config_path: Optional path where to save the configuration file.
                        If not provided, prints configuration to screen.

        Returns:
            Path to the generated configuration file if saved, None if printed to screen
        """
        # Start all servers and the proxy
        self.auto_start_servers()

        # Generate configuration
        generator = self.get_config_generator(client_type)
        config = generator.generate_config()

        if config_path:
            config_path.mkdir(parents=True, exist_ok=True)
            try:
                if config_path.is_symlink():
                    raise RuntimeError("Refusing to write config into a symlinked directory")
            except Exception:
                pass

            if client_type == "gemini":
                config_file = config_path / "settings.json"
            else:
                config_file = config_path / f"{client_type}_config.json"

            import tempfile as _tempfile
            tmp = _tempfile.NamedTemporaryFile("w", dir=str(config_path), delete=False)
            try:
                json.dump(config, tmp, indent=2)
                tmp.flush()
                os.fchmod(tmp.fileno(), 0o600)
                tmp.close()
                os.replace(tmp.name, config_file)
            finally:
                try:
                    if os.path.exists(tmp.name):
                        os.unlink(tmp.name)
                except Exception:
                    pass

            self.logger.info(f"Configuration saved to: {config_file}")
            return config_file
        else:
            # No path specified - print to screen
            import json as json_module

            print(json_module.dumps(config, indent=2))
            return None

    def get_status(self) -> Dict[str, Any]:
        """Get status of all MCP servers and proxy"""
        status = {
            "proxy_name": self.name,
            "proxy_running": self.running,
            "socket_path": str(self.socket_path) if self.socket_path else None,
            "server_sockets": {
                name: str(path) for name, path in self.server_sockets.items()
            },
            "total_servers": len(self.servers),
            "active_servers": len(self.active_processes) + len(self.python_servers),
            "temp_dir": str(self.temp_dir) if self.temp_dir else None,
            "servers": {},
        }

        for server_name, config in self.servers.items():
            if config.is_python_mcp:
                # Python MCP server
                is_running = server_name in self.python_servers
                status["servers"][server_name] = {
                    "type": "python",
                    "class": config.python_mcp.__class__.__name__,
                    "running": is_running,
                    "auto_start": config.auto_start,
                    "whitelist": config.whitelist,
                    "blacklist": config.blacklist,
                    "socket_path": (
                        str(self.server_sockets.get(server_name, ""))
                        if server_name in self.server_sockets
                        else None
                    ),
                }
            else:
                # External process server
                is_running = server_name in self.active_processes
                if is_running:
                    proc = self.active_processes[server_name]
                    is_running = proc.poll() is None

                status["servers"][server_name] = {
                    "type": "external",
                    "command": f"{config.command} {' '.join(config.args)}",
                    "running": is_running,
                    "auto_start": config.auto_start,
                    "whitelist": config.whitelist,
                    "blacklist": config.blacklist,
                    "socket_path": (
                        str(self.server_sockets.get(server_name, ""))
                        if server_name in self.server_sockets
                        else None
                    ),
                }

        return status

    def cleanup(self):
        """Clean up all resources"""
        # Stop proxy server first
        self.stop_proxy_server()

        # Stop all MCP servers
        self.stop_all_servers()

        # Clean up temp directory
        if self.temp_dir and self.temp_dir.exists():
            try:
                import shutil

                shutil.rmtree(self.temp_dir)
                self.logger.info(f"Cleaned up temp directory: {self.temp_dir}")
            except Exception as e:
                self.logger.error(f"Failed to clean up temp directory: {e}")
            finally:
                self.temp_dir = None
                self.socket_path = None

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources"""
        self.cleanup()


# Convenience function for quick usage
def create_proxy_from_config(
    config_data: Dict[str, Any], name: str = "mcp-proxy"
) -> MCPProxy:
    """Create and configure an MCP proxy from configuration data"""
    proxy = MCPProxy(name)
    proxy.load_config(config_data)
    return proxy
