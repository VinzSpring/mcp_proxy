"""
Abstract Base Class for Config Generators

Defines the interface that all config generators must implement.
This allows for easy extension to support new AI clients like Claude, etc.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional


class BaseConfigGenerator(ABC):
    """
    Abstract base class for generating client configurations.

    Each client type (Gemini, Claude, etc.) should inherit from this class
    and implement the required methods to generate appropriate configurations.
    """

    def __init__(
        self,
        proxy_name: str,
        socket_path: Path,
        temp_dir: Path,
        servers: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the config generator.

        Args:
            proxy_name: Name of the proxy instance
            socket_path: Path to the Unix socket for communication
            temp_dir: Temporary directory for storing config files
            servers: Dictionary of server configurations from the proxy
        """
        self.proxy_name = proxy_name
        self.socket_path = socket_path
        self.temp_dir = temp_dir
        self.servers = servers or {}

    @property
    @abstractmethod
    def client_type(self) -> str:
        """Return the client type identifier (e.g., 'gemini', 'claude')"""

    @abstractmethod
    def generate_config(self) -> Dict[str, Any]:
        """
        Generate the configuration dictionary for the client.

        Returns:
            Dict containing the client-specific configuration
        """

    @abstractmethod
    def create_temp_config(self) -> Path:
        """
        Create a temporary configuration file for the client.

        Returns:
            Path to the created configuration file
        """

    def _ensure_temp_dir_exists(self) -> None:
        """Ensure the temporary directory exists"""
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def get_config_file_path(self) -> Path:
        """Get the path where the config file should be stored"""
        return self.temp_dir / f"{self.client_type}_config.json"
