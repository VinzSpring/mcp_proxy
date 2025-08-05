#!/usr/bin/env python3
"""
Comprehensive MCP Proxy Demo

This demo showcases all the major features of the MCP Proxy library:
- Basic proxy setup and server management
- Per-server interceptor functionality (validation, logging, security, etc.)
- Python-based MCP servers with automatic tool discovery
- Configuration generation for different AI providers

Run this demo and then test it with your AI agent!
"""

from mcp_proxy import (
    MCPProxy,
    MCPServerConfig,
    BaseMCP,
    expose_tool,
)
from typing import Dict, Any, Optional, List
import json
import time
import datetime
from pathlib import Path
import os


# ============================================================================
# PYTHON MCP SERVERS
# ============================================================================


class MathMCP(BaseMCP):
    """A mathematical operations MCP server"""

    @expose_tool
    def add_numbers(self, a: int, b: int) -> int:
        """Add two numbers together

        Args:
            a: First number to add
            b: Second number to add

        Returns:
            The sum of a and b
        """
        return a + b

    @expose_tool
    def multiply(self, x: float, y: float) -> float:
        """Multiply two numbers

        Args:
            x: First number
            y: Second number

        Returns:
            The product of x and y
        """
        return x * y

    @expose_tool
    def calculate_factorial(self, n: int) -> int:
        """Calculate the factorial of a number

        Args:
            n: The number to calculate factorial for (must be non-negative)

        Returns:
            The factorial of n
        """
        if n < 0:
            raise ValueError("Factorial is not defined for negative numbers")
        if n == 0 or n == 1:
            return 1

        result = 1
        for i in range(2, n + 1):
            result *= i
        return result

    @expose_tool
    def find_primes(self, limit: int) -> List[int]:
        """Find all prime numbers up to a given limit

        Args:
            limit: The upper limit to search for primes

        Returns:
            List of prime numbers up to the limit
        """
        if limit < 2:
            return []

        primes = []
        for num in range(2, limit + 1):
            is_prime = True
            for i in range(2, int(num**0.5) + 1):
                if num % i == 0:
                    is_prime = False
                    break
            if is_prime:
                primes.append(num)
        return primes


class TextMCP(BaseMCP):
    """A text processing MCP server"""

    @expose_tool
    def reverse_text(self, text: str) -> str:
        """Reverse the given text

        Args:
            text: The text to reverse

        Returns:
            The reversed text
        """
        return text[::-1]

    @expose_tool
    def count_words(self, text: str, word: Optional[str] = None) -> int:
        """Count words in text

        Args:
            text: The text to analyze
            word: Specific word to count (if None, counts all words)

        Returns:
            Number of words (or occurrences of specific word)
        """
        if word is None:
            return len(text.split())
        else:
            return text.lower().split().count(word.lower())

    @expose_tool
    def format_text(
        self, text: str, uppercase: bool = False, add_prefix: Optional[str] = None
    ) -> str:
        """Format text with various options

        Args:
            text: The text to format
            uppercase: Whether to convert to uppercase
            add_prefix: Optional prefix to add

        Returns:
            The formatted text
        """
        result = text

        if uppercase:
            result = result.upper()

        if add_prefix:
            result = f"{add_prefix}{result}"

        return result


class UtilityMCP(BaseMCP):
    """A utility functions MCP server"""

    @expose_tool
    def get_current_time(self) -> str:
        """Get the current time

        Returns:
            Current time as a formatted string
        """
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @expose_tool
    def sleep_and_return(self, duration: float, message: str = "Done!") -> str:
        """Sleep for a duration and return a message

        Args:
            duration: Number of seconds to sleep
            message: Message to return after sleeping

        Returns:
            The provided message
        """
        time.sleep(duration)
        return f"Slept for {duration} seconds. {message}"

    @expose_tool
    def dangerous_tool(self, action: str) -> str:
        """A dangerous tool that requires special access

        Args:
            action: The dangerous action to perform

        Returns:
            Confirmation of the dangerous action
        """
        return f"Performed dangerous action: {action}"


# ============================================================================
# MAIN DEMO FUNCTION
# ============================================================================


def main():
    """Comprehensive MCP Proxy Demo"""
    print("🚀 MCP Proxy Comprehensive Demo")
    print("=" * 50)
    print("This demo showcases all major features of the MCP Proxy library!")
    print()

    # Create proxy
    proxy = MCPProxy("comprehensive-demo")

    # Enable debug logging
    import logging

    logging.basicConfig(level=logging.DEBUG)
    proxy.logger.setLevel(logging.DEBUG)

    # ============================================================================
    # 1. ADD EXTERNAL MCP SERVERS
    # ============================================================================
    print("📡 1. Adding External MCP Servers")
    print("-" * 30)

    # Define example interceptor functions
    def log_before_tool_call(request, server_name, tool_name):
        """Example interceptor that logs tool calls before execution"""
        print(f"🔍 INTERCEPTOR: About to execute {server_name}.{tool_name}")
        params = request.get("params", {})
        if "arguments" in params:
            print(f"    Arguments: {params['arguments']}")
        return request  # Return request to continue execution

    def validate_playwright_navigation(request, server_name, tool_name):
        """Example interceptor that validates Playwright navigation calls"""
        if tool_name == "playwright_navigate":
            params = request.get("params", {})
            arguments = params.get("arguments", {})
            url = arguments.get("url", "")

            # Block navigation to certain domains
            if "malicious-site.com" in url:
                print(
                    f"🚫 BLOCKED: Navigation to {url} blocked by security interceptor"
                )
                return None  # Return None to block the call

            print(f"✅ ALLOWED: Navigation to {url}")

        return request

    def modify_response_after_tool_call(request, response, server_name, tool_name):
        """Example interceptor that modifies responses after execution"""
        print(f"📝 INTERCEPTOR: Tool {server_name}.{tool_name} completed")

        # Add metadata to successful responses
        if "result" in response:
            if isinstance(response["result"], dict):
                response["result"]["_interceptor_metadata"] = {
                    "processed_by": "demo_interceptor",
                    "server": server_name,
                    "tool": tool_name,
                }

        return response

    # Add Playwright server with interceptors (if available)
    try:
        proxy.add_server(
            MCPServerConfig(
                name="playwright",
                command="npx",
                args=["@playwright/mcp@latest"],
                auto_start=True,
                intercept_before={
                    "playwright_navigate": validate_playwright_navigation,
                    "*": log_before_tool_call,  # Wildcard for all tools
                },
                intercept_after={"*": modify_response_after_tool_call},
            )
        )
        print("   ✅ Added Playwright MCP server with interceptors")
        print("      • Before interceptors: navigation validation + logging")
        print("      • After interceptors: response modification")
    except Exception as e:
        print(f"   ⚠️  Could not add Playwright server: {e}")

    # ============================================================================
    # 2. ADD PYTHON MCP SERVERS
    # ============================================================================
    print("\n🐍 2. Adding Python MCP Servers")
    print("-" * 30)

    # Create and add Python MCP servers
    math_server = MathMCP("math-server")
    text_server = TextMCP("text-server")
    utility_server = UtilityMCP("utility-server")

    proxy.add_python_server(math_server)
    proxy.add_python_server(text_server)
    proxy.add_python_server(
        utility_server, whitelist=["get_current_time", "sleep_and_return"]
    )  # Restrict dangerous tool

    print("   ✅ Added Math MCP server")
    print("   ✅ Added Text MCP server")
    print("   ✅ Added Utility MCP server (with whitelist)")

    # ============================================================================
    # 3. START PROXY WITH CONFIG
    # ============================================================================
    print("\n\⚙️  3. Starting Proxy with Configuration")
    print("-" * 30)

    # Start with Gemini config
    # Get the directory where this script is located
    test_dir = Path(__file__).parent / "gemini_test" 
    config_file = proxy.startup_with_config("gemini", test_dir / ".gemini")
    print(f"   ✅ Started proxy with Gemini config: {config_file}")

    # ============================================================================
    # 4. DISPLAY STATUS AND CAPABILITIES
    # ============================================================================
    print("\n📊 4. Proxy Status and Capabilities")
    print("-" * 30)

    # Show server status
    status = proxy.get_status()
    print("   📡 Servers:")
    for server_name, server_info in status["servers"].items():
        status_icon = "🟢" if server_info["running"] else "🔴"
        print(f"      {status_icon} {server_name}: {server_info['type']}")
        if server_info["type"] == "python":
            print(f"         Class: {server_info['class']}")
        if server_info.get("whitelist"):
            print(f"         Whitelist: {server_info['whitelist']}")

    # Debug: Check thread status
    print("\n   🧵 Thread Status:")
    for server_name, thread in proxy.server_threads.items():
        print(
            f"      {server_name}: {'✅ Running' if thread.is_alive() else '❌ Not running'}"
        )
    print(f"      Total threads: {len(proxy.server_threads)}")

    # Show interceptors info
    print(f"\n   🔧 Interceptors:")
    interceptor_count = 0
    for server_name, config in proxy.servers.items():
        before_count = len(config.intercept_before) if config.intercept_before else 0
        after_count = len(config.intercept_after) if config.intercept_after else 0
        if before_count > 0 or after_count > 0:
            print(f"      - {server_name}: {before_count} before, {after_count} after")
            interceptor_count += before_count + after_count
    if interceptor_count == 0:
        print("      - No interceptors configured")

    # Show discovered tools
    print(f"\n   🛠️  Available Tools:")
    for server_name in proxy.servers:
        if server_name in proxy.python_servers:
            python_server = proxy.python_servers[server_name]
            tools = python_server.mcp.get_tools()
            print(f"\n      {server_name}:")
            for tool in tools:
                if proxy.is_tool_allowed(server_name, tool["name"]):
                    print(f"        ✅ {tool['name']}: {tool['description']}")
                else:
                    print(f"        ❌ {tool['name']}: {tool['description']} (blocked)")

    # ============================================================================
    # 5. TEST INTERCEPTOR SYSTEM
    # ============================================================================
    print("\n🔧 5. Testing Per-Server Interceptor System")
    print("-" * 30)

    # Test the new interceptor system with a simulated tool call
    print("   Testing interceptor functionality...")

    # Simulate a tool call request
    test_interceptor_request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "playwright_navigate",
            "arguments": {"url": "https://example.com"},
        },
    }

    print("\n   🧪 Testing before interceptors:")
    print(f"      Original request: {json.dumps(test_interceptor_request, indent=6)}")

    # Test the before interceptors directly
    if "playwright" in proxy.servers:
        processed_by_interceptors = proxy._process_server_interceptors_before(
            test_interceptor_request, "playwright", "playwright_navigate"
        )

        if processed_by_interceptors:
            print("\n   ✅ Request passed through interceptors successfully")
        else:
            print("\n   ❌ Request was blocked by interceptors")

    # Test with a blocked URL
    blocked_request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "playwright_navigate",
            "arguments": {"url": "https://malicious-site.com/bad-page"},
        },
    }

    print(f"\n   🧪 Testing with blocked URL:")
    print(f"      Blocked request: {json.dumps(blocked_request, indent=6)}")

    if "playwright" in proxy.servers:
        blocked_result = proxy._process_server_interceptors_before(
            blocked_request, "playwright", "playwright_navigate"
        )

        if blocked_result is None:
            print("\n   ✅ Malicious URL was properly blocked by interceptor")
        else:
            print("\n   ❌ Security interceptor failed to block malicious URL")

    # Test after interceptors
    print(f"\n   🧪 Testing after interceptors:")
    test_response = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {"status": "success", "data": "Page loaded successfully"},
    }

    if "playwright" in proxy.servers:
        modified_response = proxy._process_server_interceptors_after(
            test_interceptor_request, test_response, "playwright", "playwright_navigate"
        )

        if modified_response and "_interceptor_metadata" in modified_response.get(
            "result", {}
        ):
            print("\n   ✅ Response was successfully modified by after interceptor")
            print(f"      Modified response: {json.dumps(modified_response, indent=6)}")
        else:
            print("\n   ❌ After interceptor did not modify response as expected")

    # ============================================================================
    # 6. MULTI-SOCKET ROUTING INFO
    # ============================================================================
    print("\n🔌 6. Multi-Socket Routing")
    print("-" * 30)
    print("   Each server now has its own dedicated socket for proper routing:")
    print()

    for server_name, socket_path in proxy.server_sockets.items():
        print(f"   📡 {server_name}:")
        print(f"      Socket: {socket_path}")
        print(
            f"      Status: {'✅ Ready' if server_name in proxy.servers else '❌ Not configured'}"
        )

    print("\n   This ensures that when Gemini connects to a specific server,")
    print("   requests are routed directly to that server without confusion!")

    # ============================================================================
    # 7. DEMO SETUP COMPLETE
    # ============================================================================
    print("\n🎉 7. Demo Setup Complete!")
    print("-" * 30)
    print(f"   📡 Proxy running with {len(proxy.server_sockets)} server sockets")
    print(f"   📄 Config file: {config_file}")
    print()
    print("   🚀 Ready to test with your AI agent!")
    print("   💡 Try these example tool calls:")
    print("      - math-server.add_numbers(a=10, b=20)")
    print("      - text-server.reverse_text(text='Hello World')")
    print("      - utility-server.get_current_time()")
    print("      - text-server.count_words(text='Hello world hello', word='hello')")
    print()
    print("   🔧 Interceptors will:")
    print("      - Log tool calls for the playwright server")
    print("      - Validate and block malicious URLs for navigation")
    print("      - Add metadata to responses")
    print("      - Demonstrate per-server customization")
    print()
    print("   📁 To test with Gemini:")
    print(f"      cd {test_dir}")
    print("      gemini")
    print()
    print("   Press Ctrl+C to stop the proxy...")

    try:
        # Keep running...
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down proxy...")
    finally:
        proxy.cleanup()
        print("✅ Proxy cleanup complete!")


if __name__ == "__main__":
    main()
