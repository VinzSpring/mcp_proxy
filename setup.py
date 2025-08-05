#!/usr/bin/env python3
"""
Setup script for MCP Proxy package
"""

from setuptools import setup, find_packages
from pathlib import Path
import re

# Read the README file
this_directory = Path(__file__).parent
long_description = (
    (this_directory / "readme.md").read_text(encoding="utf-8")
    if (this_directory / "readme.md").exists()
    else ""
)

# Read version from package using regex instead of exec
def get_version():
    init_file = this_directory / "mcp_proxy" / "__init__.py"
    with open(init_file, "r", encoding="utf-8") as f:
        content = f.read()
        version_match = re.search(r'^__version__ = ["\']([^"\']*)["\']', content, re.M)
        if version_match:
            return version_match.group(1)
        raise RuntimeError("Unable to find version string.")

def get_author():
    init_file = this_directory / "mcp_proxy" / "__init__.py"
    with open(init_file, "r", encoding="utf-8") as f:
        content = f.read()
        author_match = re.search(r'^__author__ = ["\']([^"\']*)["\']', content, re.M)
        if author_match:
            return author_match.group(1)
        return "MCP Proxy Contributors"

def get_email():
    init_file = this_directory / "mcp_proxy" / "__init__.py"
    with open(init_file, "r", encoding="utf-8") as f:
        content = f.read()
        email_match = re.search(r'^__email__ = ["\']([^"\']*)["\']', content, re.M)
        if email_match:
            return email_match.group(1)
        return ""

def get_description():
    init_file = this_directory / "mcp_proxy" / "__init__.py"
    with open(init_file, "r", encoding="utf-8") as f:
        content = f.read()
        desc_match = re.search(r'^__description__ = ["\']([^"\']*)["\']', content, re.M)
        if desc_match:
            return desc_match.group(1)
        return "A reusable module for managing multiple MCP servers with access control and automatic configuration generation"

setup(
    name="mcp-proxy",
    version=get_version(),
    author=get_author(),
    author_email=get_email(),
    description=get_description(),
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/mcp-proxy",  # Update with actual repo URL
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Networking",
        "Topic :: Internet :: Proxy Servers",
    ],
    python_requires=">=3.8",
    install_requires=[
        # No external dependencies - uses only standard library
    ],
    extras_require={
        "dev": [
            "pytest>=6.0",
            "pytest-cov",
            "black",
            "flake8",
            "mypy",
        ],
    },
    entry_points={
        "console_scripts": [
            "mcp-proxy=mcp_proxy.cli:main",
        ],
    },
    include_package_data=True,
    package_data={
        "mcp_proxy": ["py.typed"],
    },
    project_urls={
        "Bug Reports": "https://github.com/yourusername/mcp-proxy/issues",
        "Source": "https://github.com/yourusername/mcp-proxy",
        "Documentation": "https://github.com/yourusername/mcp-proxy#readme",
    },
)
