"""
NeuriCo version.

This file is baked into the Docker image at build time.
At runtime, it's compared against config/VERSION (mounted from host)
to detect version mismatches between the Docker image and host code.

Keep in sync with: config/VERSION, pyproject.toml
"""

__version__ = "0.4.0"
