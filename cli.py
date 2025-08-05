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
from pathlib import Path

from mcp_proxy import MCPProxy, MCPServerConfig


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
  %(prog)s --client gemini --servers playwright:npx @playwright/mcp@latest
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


def add_servers_from_specs(proxy: MCPProxy, server_specs: list[str]) -> None:
    """Add servers to proxy from command line specifications"""
    for spec in server_specs:
        try:
            name, command_str = parse_server_spec(spec)
            proxy.add_server_from_dict(name, {"start": command_str})
            print(f"📝 Added server: {name} -> {command_str}")
        except Exception as e:
            print(f"❌ Error adding server '{spec}': {e}")
            sys.exit(1)


def main():
    """Main CLI function"""
    parser = create_parser()
    args = parser.parse_args()

    # Set up signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)

    # Create proxy instance
    proxy = MCPProxy(name=args.name)

    if args.verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)
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

            with open(args.config_file) as f:
                config_data = json.load(f)

            proxy.load_config(config_data)
            servers_added = True
            print(f"📝 Loaded configuration from: {args.config_file}")

        # Add servers from command line specs
        if args.servers:
            add_servers_from_specs(proxy, args.servers)
            servers_added = True

        # If no servers specified, add a default one for demonstration
        if not servers_added:
            print("📝 No servers specified, adding default Playwright server...")
            default_config = MCPServerConfig(
                name="playwright",
                command="npx",
                args=["@playwright/mcp@latest"],
                auto_start=True,
                inherit_env=True,
            )
            proxy.add_server(default_config)

        # Display configured servers
        print(f"\n📋 Configured Servers:")
        for name, config in proxy.servers.items():
            print(f"   - {name}: {config.command} {' '.join(config.args)}")

        # Start proxy and generate config using the new startup method
        print(
            f"\n🚀 Starting MCP servers and generating {args.client} configuration..."
        )
        config_file = proxy.startup_with_config(args.client, args.config_path)

        # Wait a moment for servers to fully start
        time.sleep(2)

        # Show status
        print(f"\n📊 Proxy Status:")
        status = proxy.get_status()
        print(
            json.dumps(
                {
                    "proxy_running": status["proxy_running"],
                    "active_servers": status["active_servers"],
                    "socket_path": status["socket_path"],
                },
                indent=2,
            )
        )

        # Display the generated configuration
        print(f"\n📄 Generated Configuration:")
        with open(config_file) as f:
            config_content = json.load(f)
        print(json.dumps(config_content, indent=2))

        print(f"\n" + "=" * 60)
        print(f"🎉 SUCCESS! MCP Proxy is running")
        print(f"📍 Socket path: {proxy.socket_path}")
        print(f"📄 Config file: {config_file}")
        print(f"" + "=" * 60)

        print(f"\n📋 Usage Instructions for {args.client.upper()}:")
        if args.client == "gemini":
            if args.config_path:
                print(f"   Configuration saved to your specified path: {config_file}")
                print(f"   You can now use Gemini CLI normally.")
            else:
                print(f"   1. Copy config to ~/.gemini/settings.json, or")
                print(f"   2. Set GEMINI_CONFIG_DIR={config_file.parent}")
        else:
            print(f"   Configuration ready at: {config_file}")

        print(f"\n⏰ Proxy will run until you press Ctrl+C...")

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
