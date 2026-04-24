"""Tests for core.config_loader module."""

import os
import yaml
import pytest
from unittest.mock import patch

from core.config_loader import ConfigLoader, normalize_domain, get_valid_domains, get_default_domain


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset ConfigLoader singleton between tests."""
    ConfigLoader._instance = None
    ConfigLoader._cache = {}
    yield
    ConfigLoader._instance = None
    ConfigLoader._cache = {}


@pytest.fixture
def loader(tmp_config_dir):
    """Return a ConfigLoader pointing at the tmp config directory."""
    loader = ConfigLoader()
    loader.config_dir = tmp_config_dir
    loader.project_root = tmp_config_dir.parent
    return loader


class TestLoadConfig:
    # Verify a valid YAML file is loaded and parsed into a dict
    def test_loads_valid_yaml(self, loader):
        config = loader.load_config("domains")
        assert "domains" in config
        assert "artificial_intelligence" in config["domains"]

    # Verify FileNotFoundError is raised for a missing config file
    def test_missing_config_raises(self, loader):
        with pytest.raises(FileNotFoundError):
            loader.load_config("nonexistent")

    # Verify second call returns the same cached object (no disk read)
    def test_caches_on_second_call(self, loader):
        first = loader.load_config("domains")
        second = loader.load_config("domains")
        assert first is second

    # Verify reload=True bypasses cache and picks up on-disk changes
    def test_reload_bypasses_cache(self, loader, tmp_config_dir):
        first = loader.load_config("domains")

        # Modify the file on disk
        config_path = tmp_config_dir / "domains.yaml"
        updated = first.copy()
        updated["default_domain"] = "data_science"
        with open(config_path, "w") as f:
            yaml.dump(updated, f)

        reloaded = loader.load_config("domains", reload=True)
        assert reloaded["default_domain"] == "data_science"


class TestSingletonBehavior:
    # Verify __new__ returns the same instance (singleton pattern)
    def test_two_instances_are_same_object(self):
        a = ConfigLoader()
        b = ConfigLoader()
        assert a is b

    # Verify cache is shared across singleton references
    def test_shared_cache(self, tmp_config_dir):
        a = ConfigLoader()
        a.config_dir = tmp_config_dir
        a.load_config("domains")

        b = ConfigLoader()
        # b should see a's cached value without needing config_dir set
        assert "domains" in b._cache


class TestDomainHelpers:
    # Verify get_valid_domains returns domain keys from config
    def test_get_valid_domains(self, loader):
        domains = loader.get_valid_domains()
        assert "machine_learning" in domains
        assert "artificial_intelligence" in domains

    # Verify known domain returns True, unknown returns False
    def test_is_domain_valid(self, loader):
        assert loader.is_domain_valid("machine_learning") is True
        assert loader.is_domain_valid("underwater_basket_weaving") is False

    # Verify default domain matches the config file value
    def test_get_default_domain(self, loader):
        assert loader.get_default_domain() == "artificial_intelligence"

    # Verify display name is pulled from config's 'name' field
    def test_get_domain_display_name(self, loader):
        assert loader.get_domain_display_name("machine_learning") == "Machine Learning"

    # Verify unknown domain falls back to title-cased slug
    def test_get_domain_display_name_fallback(self, loader):
        name = loader.get_domain_display_name("unknown_domain")
        assert name == "Unknown Domain"

    # Verify has_template flag is read correctly (True and False cases)
    def test_domain_has_template(self, loader):
        assert loader.domain_has_template("artificial_intelligence") is True
        assert loader.domain_has_template("data_science") is False

    # Verify allow_unknown setting is read from validation config
    def test_should_allow_unknown_domains(self, loader):
        assert loader.should_allow_unknown_domains() is True


class TestConvenienceFunctions:
    # Verify module-level get_valid_domains() returns domains from config
    def test_get_valid_domains(self, loader):
        domains = get_valid_domains()
        assert "machine_learning" in domains
        assert "artificial_intelligence" in domains

    # Verify module-level get_default_domain() returns the default from config
    def test_get_default_domain(self, loader):
        assert get_default_domain() == "artificial_intelligence"


class TestWorkspaceConfig:
    # Verify workspace.yaml is loaded when it exists
    def test_loads_workspace_yaml(self, loader, tmp_config_dir):
        workspace_cfg = {"workspace": {"parent_dir": "/custom/path", "auto_create": False}}
        with open(tmp_config_dir / "workspace.yaml", "w") as f:
            yaml.dump(workspace_cfg, f)

        config = loader.get_workspace_config()
        assert config["workspace"]["parent_dir"] == "/custom/path"

    # Verify fallback to workspace.yaml.example when workspace.yaml is missing
    
    def test_falls_back_to_template(self, loader, tmp_config_dir):
        template_cfg = {"workspace": {"parent_dir": "from_template", "auto_create": True}}
        with open(tmp_config_dir / "workspace.yaml.example", "w") as f:
            yaml.dump(template_cfg, f)

        config = loader.get_workspace_config()
        assert config["workspace"]["parent_dir"] == "from_template"

    # Verify hardcoded defaults when neither yaml nor template exists
    def test_falls_back_to_defaults_when_no_files(self, loader):
        config = loader.get_workspace_config()
        assert config["workspace"]["parent_dir"] == "workspaces"
        assert config["workspace"]["auto_create"] is True

    # Verify workspace config is cached after first load
    def test_caches_workspace_config(self, loader, tmp_config_dir):
        template_cfg = {"workspace": {"parent_dir": "cached"}}
        with open(tmp_config_dir / "workspace.yaml.example", "w") as f:
            yaml.dump(template_cfg, f)

        first = loader.get_workspace_config()
        second = loader.get_workspace_config()
        assert first is second

    # Verify auto_create flag is read from workspace config
    def test_should_auto_create_workspace(self, loader, tmp_config_dir):
        cfg = {"workspace": {"parent_dir": "ws", "auto_create": False}}
        with open(tmp_config_dir / "workspace.yaml", "w") as f:
            yaml.dump(cfg, f)
        assert loader.should_auto_create_workspace() is False


class TestGetWorkspaceParentDir:
    # Verify NEURICO_WORKSPACE env var takes highest priority (Docker override)
    def test_env_var_override(self, loader):
        with patch.dict(os.environ, {"NEURICO_WORKSPACE": "/docker/workspace"}):
            result = loader.get_workspace_parent_dir()
        assert str(result) == "/docker/workspace"

    # Verify absolute path from config is used as-is
    def test_absolute_path_from_config(self, loader, tmp_config_dir):
        cfg = {"workspace": {"parent_dir": "/absolute/workspaces"}}
        with open(tmp_config_dir / "workspace.yaml", "w") as f:
            yaml.dump(cfg, f)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NEURICO_WORKSPACE", None)
            result = loader.get_workspace_parent_dir()
        assert str(result) == "/absolute/workspaces"

    # Verify relative path is resolved against project root
    def test_relative_path_resolves_to_project_root(self, loader, tmp_config_dir):
        cfg = {"workspace": {"parent_dir": "my_workspaces"}}
        with open(tmp_config_dir / "workspace.yaml", "w") as f:
            yaml.dump(cfg, f)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NEURICO_WORKSPACE", None)
            result = loader.get_workspace_parent_dir()
        assert result == loader.project_root / "my_workspaces"

    # Verify ${VAR} syntax in config is substituted from environment
    def test_env_var_substitution_in_config(self, loader, tmp_config_dir):
        cfg = {"workspace": {"parent_dir": "${MY_CUSTOM_DIR}"}}
        with open(tmp_config_dir / "workspace.yaml", "w") as f:
            yaml.dump(cfg, f)

        with patch.dict(os.environ, {"MY_CUSTOM_DIR": "/from/env"}, clear=False):
            os.environ.pop("NEURICO_WORKSPACE", None)
            result = loader.get_workspace_parent_dir()
        assert str(result) == "/from/env"


class TestNormalizeDomain:
    # Verify a valid domain is returned unchanged
    def test_valid_domain_passes_through(self, loader):
        assert normalize_domain("machine_learning") == "machine_learning"

    # Verify unknown domain falls back to default when allow_unknown is True
    def test_unknown_domain_falls_back_to_default(self, loader):
        result = normalize_domain("quantum_computing")
        assert result == "artificial_intelligence"

    # Verify unknown domain is returned as-is when allow_unknown is False
    def test_unknown_domain_no_fallback_when_disallowed(self, loader, tmp_config_dir):
        config_path = tmp_config_dir / "domains.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        config["validation"]["allow_unknown"] = False
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        loader.load_config("domains", reload=True)

        result = normalize_domain("quantum_computing")
        assert result == "quantum_computing"
