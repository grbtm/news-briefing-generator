import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

import pytest
import yaml
from pytest import MonkeyPatch

from news_briefing_generator.config.config_manager import ConfigManager, ConfigSource


@pytest.fixture
def temp_config_files() -> Generator[Path, None, None]:
    """Create temporary config files for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)

        # Create base settings.yaml
        base_settings = {"test_param": "base_value", "base_only": "base_only_value"}
        base_settings_path = temp_dir_path / "settings.yaml"
        with open(base_settings_path, "w") as f:
            yaml.dump(base_settings, f)

        # Create environment-specific settings
        env_settings = {"test_param": "env_value", "env_only": "env_only_value"}
        env_settings_path = temp_dir_path / "settings.development.yaml"
        with open(env_settings_path, "w") as f:
            yaml.dump(env_settings, f)

        yield temp_dir_path


def test_parameter_resolution_precedence(
    temp_config_files: Path, monkeypatch: MonkeyPatch
) -> None:
    """Test that parameters are resolved in the correct order of precedence."""
    # Set up environment variables
    monkeypatch.setenv("NBG_TEST_PARAM", "env_var_value")
    monkeypatch.setenv("NBG_ENV_VAR_ONLY", "env_var_only_value")

    # Create a mock typer context
    mock_typer_ctx = MagicMock()
    mock_typer_ctx.params = {"test-param": "cli_value", "cli-only": "cli_only_value"}

    # Set up workflow params
    workflow_params = {
        "test_param": "workflow_value",
        "workflow_only": "workflow_only_value",
    }

    # Create config manager
    config_manager = ConfigManager(
        config_path=temp_config_files / "settings.yaml",
        environment="development",
        typer_ctx=mock_typer_ctx,
    )

    # Test CLI argument precedence (highest)
    param = config_manager.get_param("test_param", workflow_params=workflow_params)

    assert param.value == "cli_value"
    assert param.source == ConfigSource.CLI_ARGUMENT

    # Test workflow param precedence (when no CLI arg)
    config_manager.typer_ctx = None  # Clear CLI args
    param = config_manager.get_param("test_param", workflow_params=workflow_params)
    assert param.value == "workflow_value"
    assert param.source == ConfigSource.WORKFLOW

    # Test environment variable precedence
    workflow_params = {}  # Clear workflow params
    param = config_manager.get_param("test_param", workflow_params=workflow_params)
    assert param.value == "env_var_value"
    assert param.source == ConfigSource.ENVIRONMENT_VARIABLE

    # Test environment settings precedence
    monkeypatch.delenv("NBG_TEST_PARAM", raising=False)
    param = config_manager.get_param("test_param", workflow_params=workflow_params)
    assert param.value == "env_value"
    assert param.source == ConfigSource.ENVIRONMENT_SETTINGS

    # Test base settings precedence
    param = config_manager.get_param("base_only", workflow_params=workflow_params)
    assert param.value == "base_only_value"
    assert param.source == ConfigSource.BASE_SETTINGS

    # Test default value
    param = config_manager.get_param(
        "non_existent", workflow_params=workflow_params, default="default_value"
    )
    assert param.value == "default_value"
    assert param.source == ConfigSource.DEFAULT


def test_task_scoped_parameter_resolution(temp_config_files: Path) -> None:
    """Test that task-scoped parameters are resolved correctly."""
    # Update base settings with task-scoped parameter
    task_name = "test_task"
    base_settings = {
        "test_param": "base_value",
        f"{task_name}": {"scoped_param": "base_scoped_value"},
    }
    with open(temp_config_files / "settings.yaml", "w") as f:
        yaml.dump(base_settings, f)

    # Create config manager
    config_manager = ConfigManager(
        config_path=temp_config_files / "settings.yaml", environment="development"
    )

    # Test task-scoped parameter resolution
    param = config_manager.get_param(
        "scoped_param", workflow_params={}, task_scope=task_name
    )
    assert param.value == "base_scoped_value"
    assert param.source == ConfigSource.BASE_SETTINGS
