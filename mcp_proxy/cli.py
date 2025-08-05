#!/usr/bin/env python3
"""
Command Line Interface for MCP Proxy

Provides a CLI for starting the MCP proxy with different AI clients
and generating configurations.
"""

import argparse
import json
import signal
import sys
import time
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from .proxy import MCPProxy, MCPServerConfig


def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    print("\n\nShutting down proxy...")
    sys.exit(0)


def create_parser() -> argparse.ArgumentParser:
    """Create the command line argument parser"""
    parser = argparse.ArgumentParser(
        description="MCP Proxy - Manage multiple MCP servers with access control",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --client gemini --config-path ~/.gemini/
  %(prog)s --client claude --config-path ./configs/
  %(prog)s --client gemini --servers "playwright:npx @playwright/mcp@latest"
  %(prog)s --client gemini --servers "filesystem:npx @modelcontextprotocol/server-filesystem@latest" "browser:npx @playwright/mcp@latest"
  %(prog)s --client gemini --config-file servers.json
        """,
    )

    parser.add_argument(
        "--client",
        "-c",
        choices=["gemini", "claude"],
        default="gemini",
        help="AI client type to generate configuration for (default: %(default)s)",
    )

    parser.add_argument(
        "--config-path",
        "-p",
        type=Path,
        help="Path where to save the generated configuration file (default: temp directory)",
    )

    parser.add_argument(
        "--servers",
        "-s",
        nargs="*",
        help="MCP servers to add in format 'name:command args' (e.g., 'playwright:npx @playwright/mcp@latest')",
    )

    parser.add_argument(
        "--config-file", type=Path, help="Load server configurations from JSON file"
    )

    parser.add_argument(
        "--name",
        "-n",
        default="mcp-proxy",
        help="Name for the proxy instance (default: %(default)s)",
    )

    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="Show detailed status of running servers and exit",
    )

    parser.add_argument(
        "--no-auto-start",
        action="store_true",
        help="Don't automatically start servers (manual start required)",
    )

    return parser


def parse_server_spec(server_spec: str) -> tuple[str, str]:
    """
    Parse a server specification string.

    Args:
        server_spec: String in format "name:command args"

    Returns:
        Tuple of (name, command_string)
    """
    if ":" not in server_spec:
        raise ValueError(
            f"Invalid server spec '{server_spec}'. Must be in format 'name:command args'"
        )

    name, command_str = server_spec.split(":", 1)
    return name.strip(), command_str.strip()


def add_servers_from_specs(
    proxy: MCPProxy, server_specs: list[str], auto_start: bool = True
) -> None:
    """Add servers to proxy from command line specifications"""
    for spec in server_specs:
        try:
            name, command_str = parse_server_spec(spec)

            # Create proper MCPServerConfig instead of using add_server_from_dict
            import shlex

            command_parts = shlex.split(command_str)
            if not command_parts:
                raise ValueError(f"Invalid or empty command: '{command_str}'")

            config = MCPServerConfig(
                name=name,
                command=command_parts[0],
                args=command_parts[1:],
                auto_start=auto_start,
                inherit_env=True,  # Preserve previous behavior for external CLIs like npx
            )

            proxy.add_server(config)
            print(f"✅ Added server: {name} -> {command_str}")
        except Exception as e:
            print(f"❌ Error adding server '{spec}': {e}")
            sys.exit(1)


def display_status(proxy: MCPProxy) -> None:
    """Display detailed status of the proxy and servers"""
    print("\n📊 MCP Proxy Status")
    print("=" * 50)

    # Get status
    status = proxy.get_status()

    print(
        f"🔌 Proxy Status: {'✅ Running' if status['proxy_running'] else '❌ Stopped'}"
    )
    if status.get("socket_path"):
        print(f"📍 Socket Path: {status['socket_path']}")

    print(f"\n📡 Servers:")
    for server_name, server_info in status["servers"].items():
        status_icon = "🟢" if server_info["running"] else "🔴"
        server_type = server_info.get("type", "external")
        print(f"   {status_icon} {server_name} ({server_type})")

        if server_info.get("whitelist"):
            print(f"      Whitelist: {', '.join(server_info['whitelist'])}")
        if server_info.get("blacklist"):
            print(f"      Blacklist: {', '.join(server_info['blacklist'])}")

    # Show socket information
    if hasattr(proxy, "server_sockets") and proxy.server_sockets:
        print(f"\n🔌 Server Sockets:")
        for server_name, socket_path in proxy.server_sockets.items():
            print(f"   {server_name}: {socket_path}")

    # Show thread status
    if hasattr(proxy, "server_threads") and proxy.server_threads:
        print(f"\n🧵 Thread Status:")
        for server_name, thread in proxy.server_threads.items():
            status = "✅ Running" if thread.is_alive() else "❌ Stopped"
            print(f"   {server_name}: {status}")


def main():
    """Main CLI function"""
    parser = create_parser()
    args = parser.parse_args()

    # Set up signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)

    # Set up logging
    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

    # Create proxy instance
    proxy = MCPProxy(name=args.name)

    if args.verbose:
        proxy.logger.setLevel(logging.DEBUG)

    try:
        print(f"🚀 MCP Proxy CLI - {args.client.upper()} Configuration")
        print("=" * 50)

        # Load servers from various sources
        servers_added = False

        # Load from config file if provided
        if args.config_file:
            if not args.config_file.exists():
                print(f"❌ Config file not found: {args.config_file}")
                sys.exit(1)

            try:
                with open(args.config_file) as f:
                    config_data = json.load(f)

                proxy.load_config(config_data)
                servers_added = True
                print(f"📝 Loaded configuration from: {args.config_file}")
            except json.JSONDecodeError as e:
                print(f"❌ Invalid JSON in config file: {e}")
                sys.exit(1)
            except Exception as e:
                print(f"❌ Error loading config file: {e}")
                sys.exit(1)

        # Add servers from command line specs
        if args.servers:
            add_servers_from_specs(
                proxy, args.servers, auto_start=not args.no_auto_start
            )
            servers_added = True

        # If no servers specified, add a default one for demonstration
        if not servers_added:
            print("📝 No servers specified, adding default Playwright server...")
            default_config = MCPServerConfig(
                name="playwright",
                command="npx",
                args=["@playwright/mcp@latest"],
                auto_start=not args.no_auto_start,
            )
            proxy.add_server(default_config)

        # Display configured servers
        print(f"\n📋 Configured Servers:")
        for name, config in proxy.servers.items():
            auto_start_status = "auto-start" if config.auto_start else "manual-start"
            print(
                f"   - {name}: {config.command} {' '.join(config.args)} ({auto_start_status})"
            )
            if config.whitelist:
                print(f"     Whitelist: {', '.join(config.whitelist)}")
            if config.blacklist:
                print(f"     Blacklist: {', '.join(config.blacklist)}")

        # If status-only mode, show status and exit
        if args.status:
            display_status(proxy)
            return 0

        # Start proxy and generate config
        print(
            f"\n🚀 Starting MCP servers and generating {args.client} configuration..."
        )

        try:
            config_file = proxy.startup_with_config(args.client, args.config_path)
        except Exception as e:
            print(f"❌ Error starting proxy: {e}")
            if args.verbose:
                import traceback

                traceback.print_exc()
            return 1

        # Wait a moment for servers to fully start
        time.sleep(2)

        # Show status
        display_status(proxy)

        print(f"\n" + "=" * 60)
        print(f"🎉 SUCCESS! MCP Proxy is running")
        if config_file:
            print(f"📄 Config file: {config_file}")
        print(f"" + "=" * 60)

        print(f"\n📋 Usage Instructions for {args.client.upper()}:")
        if args.client == "gemini":
            if config_file:
                print(f"   Configuration saved to: {config_file}")
                print(f"   You can now use Gemini CLI normally.")
            else:
                print(f"   1. Copy the config above to ~/.gemini/settings.json, or")
                print(f"   2. Use --config-path to save directly to ~/.gemini/")
        else:
            if config_file:
                print(f"   Configuration ready at: {config_file}")
            else:
                print(f"   Use --config-path to save the configuration to a file")

        print(f"\n⏰ Proxy will run until you press Ctrl+C...")
        print(f"💡 Use --status to check server status")

        # Keep the proxy running
        try:
            while True:
                time.sleep(1)

                # Check if any servers have died
                dead_servers = []
                for server_name, process in proxy.active_processes.items():
                    if process.poll() is not None:
                        dead_servers.append(server_name)

                if dead_servers:
                    print(f"⚠️  Servers died: {dead_servers}")
                    break

        except KeyboardInterrupt:
            pass

    except Exception as e:
        print(f"❌ Error: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1

    finally:
        print(f"\n🧹 Cleaning up...")
        proxy.cleanup()
        print(f"✅ Cleanup complete")

    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
