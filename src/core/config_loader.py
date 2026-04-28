"""
Config Loader - Loads and caches configuration files

Provides centralized access to configuration like domains, settings, etc.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml
import os


class ConfigLoader:
    """
    Singleton config loader that caches configuration files.
    """

    _instance = None
    _cache: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigLoader, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize config loader."""
        # Get project root (go up from src/core/)
        self.project_root = Path(__file__).parent.parent.parent
        self.config_dir = self.project_root / "config"

    def load_config(self, config_name: str, reload: bool = False) -> Dict[str, Any]:
        """
        Load a configuration file.

        Args:
            config_name: Name of config file (without .yaml extension)
            reload: Force reload even if cached

        Returns:
            Configuration dictionary

        Raises:
            FileNotFoundError: If config file doesn't exist
        """
        if not reload and config_name in self._cache:
            return self._cache[config_name]

        config_path = self.config_dir / f"{config_name}.yaml"

        if not config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {config_path}\n"
                f"Please ensure {config_name}.yaml exists in the config/ directory."
            )

        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        self._cache[config_name] = config
        return config

    def get_domains_config(self) -> Dict[str, Any]:
        """
        Get domains configuration.

        Returns:
            Domains config dictionary with keys:
            - default_domain: Default domain for unknown domains
            - domains: Dict of domain configurations
            - validation: Validation settings
        """
        return self.load_config('domains')

    def get_valid_domains(self) -> List[str]:
        """
        Get list of valid domain names.

        Returns:
            List of domain names (keys from domains config)
        """
        config = self.get_domains_config()
        return list(config.get('domains', {}).keys())

    def get_default_domain(self) -> str:
        """
        Get the default domain to use for unknown domains.

        Returns:
            Default domain name
        """
        config = self.get_domains_config()
        return config.get('default_domain', 'artificial_intelligence')

    def is_domain_valid(self, domain: str) -> bool:
        """
        Check if a domain is in the valid domains list.

        Args:
            domain: Domain name to check

        Returns:
            True if domain is valid
        """
        return domain in self.get_valid_domains()

    def should_allow_unknown_domains(self) -> bool:
        """
        Check if unknown domains should be allowed (with fallback).

        Returns:
            True if unknown domains are allowed
        """
        config = self.get_domains_config()
        return config.get('validation', {}).get('allow_unknown', True)

    def domain_has_template(self, domain: str) -> bool:
        """
        Check if a domain has a specific template.

        Args:
            domain: Domain name

        Returns:
            True if domain has a template, False if should use default
        """
        config = self.get_domains_config()
        domain_config = config.get('domains', {}).get(domain, {})
        return domain_config.get('has_template', False)

    def get_default_paper_style(self) -> str:
        """
        Get the global default paper style (used when a domain has no
        specific paper_style set).

        Returns:
            Paper style name (e.g. 'neurips')
        """
        config = self.get_domains_config()
        return config.get('default_paper_style', 'neurips')

    def get_domain_paper_style(self, domain: str) -> str:
        """
        Get the paper style for a domain. Falls back to the global
        default_paper_style if the domain has no specific style set.

        Args:
            domain: Domain name

        Returns:
            Paper style name (e.g. 'ams', 'finance', 'neurips')
        """
        config = self.get_domains_config()
        domain_config = config.get('domains', {}).get(domain, {})
        return domain_config.get('paper_style') or self.get_default_paper_style()

    def get_domain_keywords(self, domain: str) -> List[str]:
        """
        Get the keyword list used for inferring this domain from text.

        Args:
            domain: Domain name

        Returns:
            List of keywords (empty list if none defined)
        """
        config = self.get_domains_config()
        domain_config = config.get('domains', {}).get(domain, {})
        return domain_config.get('keywords', []) or []

    def get_all_domain_keywords(self) -> Dict[str, List[str]]:
        """
        Get the full {domain_name: keywords} mapping for all configured domains.

        Used by the IdeaHub fetcher to infer the most likely domain from
        an idea's title/description/tags.

        Returns:
            Dict mapping domain name to its keyword list
        """
        config = self.get_domains_config()
        return {
            name: (entry.get('keywords') or [])
            for name, entry in config.get('domains', {}).items()
        }

    def get_domain_display_name(self, domain: str) -> str:
        """
        Get the display name for a domain.

        Args:
            domain: Domain name

        Returns:
            Display name or the domain name itself if not found
        """
        config = self.get_domains_config()
        domain_config = config.get('domains', {}).get(domain, {})
        return domain_config.get('name', domain.replace('_', ' ').title())

    def get_workspace_config(self) -> Dict[str, Any]:
        """
        Get workspace configuration.

        Falls back to workspace.yaml.example template if workspace.yaml doesn't exist.
        This allows users to customize their local config without pushing to git.

        Returns:
            Workspace config dictionary
        """
        config_path = self.config_dir / "workspace.yaml"
        template_path = self.config_dir / "workspace.yaml.example"

        # Check cache first
        if 'workspace' in self._cache:
            return self._cache['workspace']

        # Try loading user config first
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            self._cache['workspace'] = config
            return config

        # Fall back to template
        if template_path.exists():
            with open(template_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            self._cache['workspace'] = config
            return config

        # Fallback defaults if neither file exists
        return {'workspace': {'parent_dir': 'workspaces', 'auto_create': True, 'permissions': 0o755}}

    def get_workspace_parent_dir(self) -> Path:
        """
        Get the workspace parent directory path.

        Priority (highest to lowest):
        1. NEURICO_WORKSPACE environment variable (for Docker override)
        2. Config file value (workspace.yaml)
        3. Default: 'workspaces' relative to project root

        Config file supports:
        - Absolute paths: /data/hypogenicai/workspaces
        - Relative paths: workspaces (relative to project root)
        - Environment variable syntax: ${NEURICO_WORKSPACE}

        Returns:
            Resolved Path object for workspace parent directory
        """
        # Check for environment variable override first (used in Docker containers)
        env_workspace = os.getenv('NEURICO_WORKSPACE')
        if env_workspace:
            return Path(env_workspace)

        config = self.get_workspace_config()
        parent_dir = config.get('workspace', {}).get('parent_dir', 'workspaces')

        # Handle environment variable substitution in config value
        if parent_dir.startswith('${') and parent_dir.endswith('}'):
            env_var = parent_dir[2:-1]
            parent_dir = os.getenv(env_var, 'workspaces')

        parent_path = Path(parent_dir)

        # If relative, make it relative to project root
        if not parent_path.is_absolute():
            parent_path = self.project_root / parent_path

        return parent_path

    def should_auto_create_workspace(self) -> bool:
        """
        Check if workspace parent directory should be auto-created.

        Returns:
            True if auto-create is enabled
        """
        config = self.get_workspace_config()
        return config.get('workspace', {}).get('auto_create', True)


# Convenience functions for direct access
def get_valid_domains() -> List[str]:
    """Get list of valid domains."""
    loader = ConfigLoader()
    return loader.get_valid_domains()


def get_default_domain() -> str:
    """Get default domain."""
    loader = ConfigLoader()
    return loader.get_default_domain()


def normalize_domain(domain: str) -> str:
    """
    Normalize a domain, falling back to default if invalid.

    Args:
        domain: Domain to normalize

    Returns:
        Valid domain name (original or default)
    """
    loader = ConfigLoader()

    if loader.is_domain_valid(domain):
        return domain

    if loader.should_allow_unknown_domains():
        default = loader.get_default_domain()
        return default

    # If not allowing unknown, return as-is and let validation fail
    return domain


def main():
    """Test config loader."""
    loader = ConfigLoader()

    print("Valid domains:")
    for domain in loader.get_valid_domains():
        has_template = "✓" if loader.domain_has_template(domain) else "○"
        display_name = loader.get_domain_display_name(domain)
        print(f"  {has_template} {domain:30s} - {display_name}")

    print(f"\nDefault domain: {loader.get_default_domain()}")
    print(f"Allow unknown: {loader.should_allow_unknown_domains()}")

    print("\nTest normalization:")
    print(f"  'machine_learning' -> '{normalize_domain('machine_learning')}'")
    print(f"  'unknown_domain' -> '{normalize_domain('unknown_domain')}'")


if __name__ == "__main__":
    main()
