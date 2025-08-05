"""
Python-based MCP Server Implementation

Allows defining MCP servers directly in Python code with automatic tool discovery,
parameter extraction from type hints, and documentation from docstrings.
"""

import inspect
import re
from abc import ABC
from typing import Dict, Any, List, Optional, get_type_hints, Union
from dataclasses import dataclass
import logging


@dataclass
class MCPTool:
    """Represents a tool available in an MCP server"""

    name: str
    description: str
    parameters: Dict[str, Any]
    function: callable


class BaseMCP(ABC):
    """
    Base class for Python-based MCP servers.

    Subclass this and define methods that should be exposed as tools.
    Method names become tool names, type hints become parameter schemas,
    and docstrings provide descriptions.

    Example:
        class MyMCP(BaseMCP):
            '''A custom MCP server for math operations'''

            def add_numbers(self, a: int, b: int) -> int:
                '''Add two numbers together

                Args:
                    a: First number to add
                    b: Second number to add

                Returns:
                    The sum of a and b
                '''
                return a + b
    """

    def __init__(self, name: str):
        """
        Initialize the MCP server.

        Args:
            name: Name of the MCP server
        """
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{name}")
        self._tools: Dict[str, MCPTool] = {}
        self._discover_tools()

    def _discover_tools(self):
        """Automatically discover tools from methods that explicitly opt in."""
        exposed_map = getattr(self, "_exposed_tools", {}) or {}
        for method_name in dir(self):
            method = getattr(self, method_name)

            # Skip private methods and inherited methods
            if (
                method_name.startswith("_")
                or not callable(method)
                or hasattr(BaseMCP, method_name)
            ):
                continue

            # Require explicit exposure
            is_explicit = getattr(method, "__mcp_expose__", False) or exposed_map.get(method_name, False)
            if not is_explicit:
                continue

            try:
                tool = self._create_tool_from_method(method_name, method)
                if tool:
                    self._tools[tool.name] = tool
                    self.logger.debug(f"Discovered tool: {tool.name}")
            except Exception as e:
                self.logger.warning(
                    f"Failed to create tool from method {method_name}: {e}"
                )

    def _create_tool_from_method(
        self, method_name: str, method: callable
    ) -> Optional[MCPTool]:
        """Create an MCPTool from a method"""
        # Get method signature and type hints
        signature = inspect.signature(method)
        type_hints = get_type_hints(method)

        # Parse docstring
        description, param_descriptions = self._parse_docstring(method.__doc__ or "")

        # Build parameter schema
        parameters = {"type": "object", "properties": {}, "required": []}

        for param_name, param in signature.parameters.items():
            # Skip 'self' parameter
            if param_name == "self":
                continue

            param_schema = self._get_parameter_schema(
                param_name, param, type_hints, param_descriptions
            )
            parameters["properties"][param_name] = param_schema

            # Add to required if no default value
            if param.default is inspect.Parameter.empty:
                parameters["required"].append(param_name)

        return MCPTool(
            name=method_name,
            description=description or f"Execute {method_name}",
            parameters=parameters,
            function=method,
        )

    def _parse_docstring(self, docstring: str) -> tuple[str, Dict[str, str]]:
        """
        Parse docstring to extract description and parameter descriptions.

        Supports Google-style and NumPy-style docstrings.
        """
        if not docstring:
            return "", {}

        lines = docstring.strip().split("\n")
        description_lines = []
        param_descriptions = {}

        current_section = "description"
        current_param = None

        for line in lines:
            line = line.strip()

            # Check for Args/Parameters section
            if line.lower() in ["args:", "arguments:", "parameters:", "params:"]:
                current_section = "params"
                continue
            elif line.lower() in ["returns:", "return:", "yields:", "yield:"]:
                current_section = "returns"
                continue
            elif line.lower() in ["raises:", "except:", "exceptions:"]:
                current_section = "raises"
                continue

            if current_section == "description":
                if line:
                    description_lines.append(line)
            elif current_section == "params":
                # Parse parameter descriptions like "param_name: description" or "param_name (type): description"
                param_match = re.match(r"(\w+)(?:\s*\([^)]+\))?\s*:\s*(.+)", line)
                if param_match:
                    current_param = param_match.group(1)
                    param_descriptions[current_param] = param_match.group(2)
                elif current_param and line:
                    # Continuation of previous parameter description
                    param_descriptions[current_param] += " " + line

        description = " ".join(description_lines).strip()
        return description, param_descriptions

    def _get_parameter_schema(
        self,
        param_name: str,
        param: inspect.Parameter,
        type_hints: Dict[str, Any],
        param_descriptions: Dict[str, str],
    ) -> Dict[str, Any]:
        """Generate JSON schema for a parameter"""
        schema = {}

        # Get type information
        param_type = type_hints.get(param_name, param.annotation)
        schema.update(self._type_to_schema(param_type))

        # Add description if available
        if param_name in param_descriptions:
            schema["description"] = param_descriptions[param_name]

        # Add default value if present
        if param.default is not inspect.Parameter.empty:
            schema["default"] = param.default

        return schema

    def _type_to_schema(self, type_annotation: Any) -> Dict[str, Any]:
        """Convert Python type annotation to JSON schema"""
        # Handle basic types
        if type_annotation == int:
            return {"type": "integer"}
        elif type_annotation == float:
            return {"type": "number"}
        elif type_annotation == str:
            return {"type": "string"}
        elif type_annotation == bool:
            return {"type": "boolean"}
        elif type_annotation == list:
            return {"type": "array"}
        elif type_annotation == dict:
            return {"type": "object"}

        # Handle typing module types
        origin = getattr(type_annotation, "__origin__", None)
        args = getattr(type_annotation, "__args__", ())

        if origin is Union:
            # Handle Optional[Type] which is Union[Type, None]
            if len(args) == 2 and type(None) in args:
                non_none_type = args[0] if args[1] is type(None) else args[1]
                schema = self._type_to_schema(non_none_type)
                # Don't set as required since it's optional
                return schema
            else:
                # Multiple types - use anyOf
                return {"anyOf": [self._type_to_schema(arg) for arg in args]}
        elif origin is list:
            schema = {"type": "array"}
            if args:
                schema["items"] = self._type_to_schema(args[0])
            return schema
        elif origin is dict:
            schema = {"type": "object"}
            if len(args) >= 2:
                schema["additionalProperties"] = self._type_to_schema(args[1])
            return schema

        # Default for unknown types
        return {"type": "string", "description": f"Type: {type_annotation}"}

    def get_tools(self) -> List[Dict[str, Any]]:
        """Get list of available tools in MCP format"""
        tools = []
        for tool in self._tools.values():
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.parameters,
                }
            )
        return tools


def expose_tool(func):
    """Decorator to explicitly expose a method as an MCP tool."""
    setattr(func, "__mcp_expose__", True)
    return func

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool with the given arguments"""
        if tool_name not in self._tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        tool = self._tools[tool_name]

        try:
            # Filter out middleware-injected parameters that aren't part of the tool signature
            import inspect

            sig = inspect.signature(tool.function)
            filtered_args = {
                key: value for key, value in arguments.items() if key in sig.parameters
            }

            # Log if we're filtering out any parameters
            filtered_out = set(arguments.keys()) - set(filtered_args.keys())
            if filtered_out:
                self.logger.debug(
                    f"Filtered out middleware parameters for {tool_name}: {filtered_out}"
                )

            # Call the method with filtered arguments
            result = tool.function(**filtered_args)
            return result
        except Exception as e:
            self.logger.error(f"Error calling tool {tool_name}: {e}")
            raise

    def get_server_info(self) -> Dict[str, Any]:
        """Get server information"""
        return {
            "name": self.name,
            "description": self.__doc__ or f"Python MCP Server: {self.name}",
            "version": "1.0.0",
        }


class PythonMCPServer:
    """
    Wrapper that makes a Python MCP server compatible with the proxy system.

    This handles the JSON-RPC protocol communication with the proxy.
    """

    def __init__(self, mcp_instance: BaseMCP):
        """
        Initialize with a BaseMCP instance.

        Args:
            mcp_instance: Instance of a class that inherits from BaseMCP
        """
        self.mcp = mcp_instance
        self.logger = logging.getLogger(f"{__name__}.server.{mcp_instance.name}")

    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a JSON-RPC request"""
        try:
            method = request.get("method")
            params = request.get("params", {})
            request_id = request.get("id")

            if method == "initialize":
                return self._handle_initialize(request_id)
            elif method == "tools/list":
                return self._handle_tools_list(request_id)
            elif method == "tools/call":
                return self._handle_tool_call(request_id, params)
            else:
                return self._create_error_response(
                    request_id, -32601, f"Unknown method: {method}"
                )

        except Exception as e:
            self.logger.error(f"Error handling request: {e}")
            return self._create_error_response(request.get("id"), -32603, str(e))

    def _handle_initialize(self, request_id: Any) -> Dict[str, Any]:
        """Handle initialize request"""
        server_info = self.mcp.get_server_info()
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": server_info,
            },
        }

    def _handle_tools_list(self, request_id: Any) -> Dict[str, Any]:
        """Handle tools/list request"""
        tools = self.mcp.get_tools()
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}

    def _handle_tool_call(
        self, request_id: Any, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle tools/call request"""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            return self._create_error_response(request_id, -32602, "Missing tool name")

        try:
            result = self.mcp.call_tool(tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"content": [{"type": "text", "text": str(result)}]},
            }
        except Exception as e:
            return self._create_error_response(
                request_id, -32000, f"Tool execution failed: {e}"
            )

    def _create_error_response(
        self, request_id: Any, code: int, message: str
    ) -> Dict[str, Any]:
        """Create an error response"""
        # If there's no id (it's a notification), return None to indicate no response should be sent
        if request_id is None:
            return None

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
