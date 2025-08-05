# MCP Proxy

MCP proxy is a Python library for finally reclaiming all control over MCP servers!

You can black/whitelist MCP tools, intercept tool calls or simply write your own MCP server in a few lines of code!

> You can start this from within your main application and use it to govern MCP servers passed to your CLI AI agent!

## Scenario when you can use this
You are writing an application that relies on launching Google Gemini CLI as  subprocess and you want to check if it calls certain tools or make sure Gemini does not leak sensitive data to MCP servers.

## Features

- **Multiple MCP Server Management** - Run and manage multiple MCP servers simultaneously
- **Access Control** - Whitelist/blacklist tools per server for security
- **Python MCP Servers** - Define MCP servers directly in Python with automatic tool discovery
- **Per-Server Interceptors** - Add custom logic before/after tool calls (logging, validation, security, response modification)
- **Multi-Socket Routing** - Each server gets its own dedicated socket for proper request routing
- **Configuration Generation** - Generate configurations for AI clients (Gemini CLI, Claude, etc.)
- **Automatic Tool Discovery** - Python MCP servers automatically expose methods as tools with type hints and docstrings

## Installation

```bash
git clone https://github.com/VinzSpring/mcp_proxy
pip install -e mcp-proxy
```

## Quick Start

### As a Library

```python
from mcp_proxy import MCPProxy, MCPServerConfig, BaseMCP

# Create proxy
proxy = MCPProxy("my-proxy")

# Add external MCP server
proxy.add_server(MCPServerConfig(
    name="playwright",
    command="npx",
    args=["@playwright/mcp@latest"],
    auto_start=True
))

# Add Python MCP server
class MathMCP(BaseMCP):
    def add_numbers(self, a: int, b: int) -> int:
        """Add two numbers together"""
        return a + b

math_server = MathMCP("math-server")
proxy.add_python_server(math_server)

# Start and generate config
config_file = proxy.startup_with_config("gemini")
print(f"Config saved to: {config_file}")
```

### As CLI

The MCP Proxy provides a powerful command-line interface for managing MCP servers:

```bash
# Basic usage with default server
mcp-proxy --client gemini

# Specify custom servers
mcp-proxy --client gemini --servers "playwright:npx @playwright/mcp@latest"

# Multiple servers
mcp-proxy --client gemini --servers "playwright:npx @playwright/mcp@latest" "filesystem:npx @modelcontextprotocol/server-filesystem@latest"

# Save to specific path
mcp-proxy --client gemini --config-path ~/.gemini/

# Load from configuration file
mcp-proxy --client gemini --config-file servers.json

# Show detailed status and exit
mcp-proxy --status

# Manual server start (don't auto-start)
mcp-proxy --no-auto-start --servers "playwright:npx @playwright/mcp@latest"

# Verbose logging
mcp-proxy --verbose --client gemini
```

#### CLI Options

- `--client, -c` - AI client type (gemini, claude) [default: gemini]
- `--config-path, -p` - Path to save configuration file
- `--servers, -s` - MCP servers in format 'name:command args'
- `--config-file` - Load server configurations from JSON file
- `--name, -n` - Proxy instance name [default: mcp-proxy]
- `--verbose, -v` - Enable verbose logging
- `--status` - Show detailed status and exit
- `--no-auto-start` - Don't automatically start servers

#### Server Configuration Format

Servers can be specified in the format `name:command args`:

```bash
# Playwright browser automation
mcp-proxy --servers "browser:npx @playwright/mcp@latest"

# Filesystem access
mcp-proxy --servers "filesystem:npx @modelcontextprotocol/server-filesystem@latest"

# Multiple servers
mcp-proxy --servers "browser:npx @playwright/mcp@latest" "filesystem:npx @modelcontextprotocol/server-filesystem@latest"
```

#### Status Information

Use `--status` to get detailed information about the proxy:

```bash
mcp-proxy --status
```

This shows:
- Proxy running status
- Individual server status with icons
- Socket paths for multi-socket routing
- Thread status
- Whitelist/blacklist information

## Python MCP Servers

Define MCP servers directly in Python with automatic tool discovery:

```python
from mcp_proxy import BaseMCP

class MyMCP(BaseMCP):
    """A custom MCP server for math operations"""
    
    def add_numbers(self, a: int, b: int) -> int:
        """Add two numbers together
        
        Args:
            a: First number to add
            b: Second number to add
            
        Returns:
            The sum of a and b
        """
        return a + b
    
    def multiply(self, x: float, y: float) -> float:
        """Multiply two numbers"""
        return x * y

# Add to proxy
math_server = MyMCP("math-server")
proxy.add_python_server(math_server)
```

**Features:**
- **Automatic tool discovery** from class methods
- **Type hints** become parameter schemas  
- **Docstring parsing** for descriptions and parameter docs
- **Built-in validation** and error handling
- **No external processes** - runs directly in Python

## Per-Server Interceptors

Add custom logic before and after tool calls for each server:

```python
# Define interceptor functions
def log_before_tool_call(request, server_name, tool_name):
    """Log all tool calls"""
    print(f"🔍 About to execute {server_name}.{tool_name}")
    return request  # Return request to continue

def validate_navigation(request, server_name, tool_name):
    """Validate navigation URLs"""
    if tool_name == "playwright_navigate":
        url = request.get("params", {}).get("arguments", {}).get("url", "")
        if "malicious-site.com" in url:
            print(f"🚫 Blocked navigation to {url}")
            return None  # Return None to block
    return request

def modify_response(request, response, server_name, tool_name):
    """Add metadata to responses"""
    if "result" in response:
        response["result"]["_metadata"] = {
            "processed_by": "interceptor",
            "server": server_name,
            "tool": tool_name
        }
    return response

# Add server with interceptors
proxy.add_server(MCPServerConfig(
    name="playwright",
    command="npx",
    args=["@playwright/mcp@latest"],
    intercept_before={
        "playwright_navigate": validate_navigation,
        "*": log_before_tool_call  # Wildcard for all tools
    },
    intercept_after={
        "*": modify_response
    }
))
```

## Access Control

```python
# Whitelist specific tools
proxy.add_python_server(
    utility_server, 
    whitelist=["get_current_time", "sleep_and_return"]
)

# Blacklist dangerous tools
proxy.add_server(MCPServerConfig(
    name="filtered", 
    command="npx",
    args=["@other/server"],
    blacklist=["delete_file", "execute_command"]
))
```

## Multi-Socket Routing

Each server gets its own dedicated socket for proper request routing:

```python
# Each server has its own socket
for server_name, socket_path in proxy.server_sockets.items():
    print(f"{server_name}: {socket_path}")
```

This ensures that when AI clients connect to a specific server, requests are routed directly to that server without confusion.

## Generated Configuration

The proxy generates configuration where each MCP server appears as a separate entry, but all connect through the same proxy socket:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "socat",
      "args": [
        "STDIO",
        "UNIX-CONNECT:/path/to/proxy.sock"
      ]
    },
    "math-server": {
      "command": "socat",
      "args": [
        "STDIO",
        "UNIX-CONNECT:/path/to/proxy.sock"
      ]
    }
  }
}
```

This way the AI agent sees each server individually without knowing about the proxy.

## API Reference

### MCPProxy
- `add_server(config: MCPServerConfig)` - Add external MCP server
- `add_python_server(mcp_instance: BaseMCP, whitelist=None, blacklist=None)` - Add Python MCP server
- `startup_with_config(client_type, config_path=None)` - Start proxy and generate config
- `get_status()` - Get status of all servers
- `cleanup()` - Clean up resources

### MCPServerConfig
- `name` - Server name
- `command` - Command to execute (for external servers)
- `args` - Command arguments
- `env` - Environment variables (optional)
- `whitelist` - Allowed tools (optional)
- `blacklist` - Blocked tools (optional)
- `auto_start` - Auto-start server (default: True)
- `python_mcp` - Python MCP instance (for Python servers)
- `intercept_before` - Functions to run before tool calls
- `intercept_after` - Functions to run after tool calls

### BaseMCP
- `__init__(name: str)` - Initialize with server name
- Methods automatically become tools with type hints and docstrings

## Examples

### Comprehensive Demo

Run the comprehensive demo to see all features in action:

```bash
python comprehensive_demo.py
```

This demo showcases:
- External MCP servers with interceptors
- Python MCP servers with automatic tool discovery
- Access control and security features
- Multi-socket routing
- Configuration generation

### Real-World Usage

```python
from mcp_proxy import MCPProxy, MCPServerConfig, BaseMCP

# Create proxy
proxy = MCPProxy("production-proxy")

# Add external servers with security interceptors
proxy.add_server(MCPServerConfig(
    name="browser",
    command="npx",
    args=["@playwright/mcp@latest"],
    intercept_before={
        "playwright_navigate": validate_urls,
        "*": log_requests
    }
))

# Add custom Python servers
class DataProcessor(BaseMCP):
    def process_data(self, data: str) -> dict:
        """Process and analyze data"""
        # Your processing logic here
        return {"result": "processed", "data": data}

proxy.add_python_server(DataProcessor("data-processor"))

# Start and generate config
config_file = proxy.startup_with_config("gemini", Path("~/.gemini"))
print(f"Ready! Config: {config_file}")
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.