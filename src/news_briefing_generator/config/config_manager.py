import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer
import yaml

from news_briefing_generator.utils.path_utils import resolve_config_path


class ConfigSource(Enum):
    CLI_ARGUMENT = "cli_arg"
    WORKFLOW = "workflow"
    ENVIRONMENT_VARIABLE = "env_var"
    ENVIRONMENT_SETTINGS = "env_settings"
    BASE_SETTINGS = "base_settings"
    DEFAULT = "default"


@dataclass
class Parameter:
    """Represents a configuration parameter with source tracking."""

    value: Any
    source: ConfigSource


@dataclass
class ConfigManager:
    """Class to manage the configuration file."""

    config_path: Path = field(
        default_factory=lambda: resolve_config_path("settings.yaml")
    )
    environment: str = field(default="development")
    ollama_url: Optional[str] = field(default=None)
    typer_ctx: Optional[typer.Context] = field(default=None)

    base_settings: Dict[str, Any] = field(init=False, default_factory=dict)
    env_settings: Dict[str, Any] = field(init=False, default_factory=dict)
    merged_settings: Dict[str, Any] = field(init=False, default_factory=dict)
    url_to_feedname: Dict[str, str] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        """Initializes the ConfigManager instance."""
        # Convert string path to Path object if needed
        if isinstance(self.config_path, str):
            self.config_path = Path(self.config_path)

        # Load base settings
        self.base_settings = self._load_settings_file(self.config_path)

        # Load environment-specific settings
        env_settings_path = (
            self.config_path.parent / f"settings.{self.environment}.yaml"
        )
        self.env_settings = self._load_settings_file(env_settings_path, required=False)

        # Merge settings
        self.merged_settings = self._merge_settings(
            self.base_settings, self.env_settings  # TODO consider adding env vars here
        )

        # Override with CLI arguments if provided
        if self.ollama_url:
            self.merged_settings["ollama"]["base_url"] = self.ollama_url

        # Generate URL to feed name map
        self.url_to_feedname = self._generate_url_to_feedname_map()

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value without parameter resolution chain.

        Used for core system configuration that shouldn't be overrideable.
        """
        base_value = self._get_from_dict(self.merged_settings, key)
        if base_value is not None:
            return base_value
        return default

    def get_param(
        self,
        key: str,
        workflow_params: Optional[Dict] = None,
        task_scope: Optional[str] = None,
        default: Any = None,
    ) -> Parameter:
        """Get parameter value with source tracking following precedence chain.

        Primary interface for Task classes to resolve parameters through Task.get_parameter().
        Follows parameter resolution precedence:
        1. CLI arguments
        2. Workflow config (from workflow_configs.yaml)
        3. Environment variables (NBG_ prefixed)
        4. Environment settings (settings.{env}.yaml)
        5. Base settings (settings.yaml)
        6. Default value

        Args:
            key: Parameter key to look up
            workflow_params: Optional workflow parameters from TaskContext
            task_scope: Task name for scoped parameter lookup (e.g. "feed_collection")
            default: Default value if parameter not found in any source

        Returns:
            Parameter: Value and source tracking object used by Task._track_param_resolution()
        """

        # Helper to try both scoped and unscoped keys
        def try_get_param(
            params: Dict, param_key: str, scope: Optional[str] = None
        ) -> Optional[Any]:
            # Try scoped key first if scope provided
            if scope:
                scoped_key = f"{scope}.{param_key}"
                value = self._get_from_dict(params, scoped_key)
                if value is not None:
                    return value
            # Fall back to unscoped key
            return self._get_from_dict(params, param_key)

        # 1. Check CLI arguments (if applicable)
        cli_value = self._get_cli_param(key)
        if cli_value is not None:
            return Parameter(cli_value, ConfigSource.CLI_ARGUMENT)

        # 2. Check workflow params
        resolved_workflow_param = try_get_param(workflow_params or {}, key)
        if resolved_workflow_param is not None:
            return Parameter(resolved_workflow_param, ConfigSource.WORKFLOW)

        # 3. Check environment variables
        env_var = f"NBG_{key.upper()}"
        if env_var in os.environ:
            return Parameter(os.environ[env_var], ConfigSource.ENVIRONMENT_VARIABLE)

        # 4. Check environment config (settings.{env}.yaml)
        env_value = try_get_param(self.env_settings, key, scope=task_scope)
        if env_value is not None:
            return Parameter(env_value, ConfigSource.ENVIRONMENT_SETTINGS)

        # 5. Check base settings (settings.yaml)
        base_value = try_get_param(self.base_settings, key, scope=task_scope)
        if base_value is not None:
            return Parameter(base_value, ConfigSource.BASE_SETTINGS)

        # 6. Return default value
        return Parameter(default, ConfigSource.DEFAULT)

    def get_all_configs(self) -> Dict[str, Any]:
        """Returns all configurations."""
        all_configs = {
            "base_configs": self.base_settings.copy(),
            "env_configs": self.env_settings.copy(),
        }
        return all_configs

    def override_feeds(self, feeds: List[Dict[str, str]]) -> None:
        """Override configured feeds with provided list.

        Args:
            feeds: List of feed dictionaries with 'name' and 'url' keys
        """
        # Update both base and merged settings to maintain consistency
        self.base_settings["feeds"] = feeds
        self.merged_settings["feeds"] = feeds

        # Regenerate feed name mapping
        self.url_to_feedname = self._generate_url_to_feedname_map()

    def _get_cli_param(self, key: str) -> Optional[str]:
        """Retrieve CLI argument value if available.

        Args:
            key: Parameter key to look up

        Returns:
            Optional[str]: CLI argument value if found, otherwise None
        """
        try:
            # Use Typer's context to access CLI arguments
            if self.typer_ctx is None:
                return None

            # Convert key to CLI argument format (e.g., "base_url" -> "base-url")
            cli_arg = key.replace("_", "-")

            # Check if the argument was passed
            if cli_arg in self.typer_ctx.params:
                return str(self.typer_ctx.params[cli_arg])

            # Check for short option (e.g., "b" for "base_url")
            short_cli_arg = key[0]
            if short_cli_arg in self.typer_ctx.params:
                return str(self.typer_ctx.params[short_cli_arg])

        except Exception as e:
            # Log or handle the exception as needed
            print(f"Error retrieving CLI parameter '{key}': {e}")

        return None

    def _load_settings_file(self, path: Path, required: bool = True) -> Dict[str, Any]:
        """Load settings from YAML file.

        Args:
            path: Path to settings file
            required: Whether file must exist

        Returns:
            Dict of settings, empty if file doesn't exist and not required

        Raises:
            FileNotFoundError: If required file doesn't exist
        """
        try:
            with open(path, "r") as file:
                return yaml.safe_load(file) or {}
        except FileNotFoundError:
            if required:
                raise FileNotFoundError(f"Required settings file not found: {path}")
            return {}
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in {path}: {e}")

    def _merge_settings(self, base: Dict, env: Dict) -> Dict:
        """Deep merge base and environment settings.

        Args:
            base: Base settings dictionary
            env: Environment-specific settings dictionary

        Returns:
            Dict: Merged settings with environment overriding base values

        Example:
            >>> base = {'db': {'host': 'localhost', 'port': 5432}}
            >>> env = {'db': {'port': 5433}}
            >>> _merge_settings(base, env)
            {'db': {'host': 'localhost', 'port': 5433}}
        """

        def deep_merge(base_dict: Dict, override_dict: Dict) -> Dict:
            merged = base_dict.copy()

            for key, value in override_dict.items():
                if (
                    key in merged
                    and isinstance(merged[key], dict)
                    and isinstance(value, dict)
                ):
                    # Recursively merge nested dictionaries
                    merged[key] = deep_merge(merged[key], value)
                else:
                    # Override or add value
                    merged[key] = value

            return merged

        return deep_merge(base, env)

    def _generate_url_to_feedname_map(self) -> Dict:
        """Generates a mapping of feed URLs to feed names."""
        feeds = self.get("feeds", {})
        mapping = {feed["url"]: feed["name"] for feed in feeds}
        return mapping

    def _get_from_dict(self, config_dict: Dict, path: str) -> Optional[Any]:
        """Get value from dictionary using dot notation."""
        try:
            value = config_dict
            for key in path.split("."):
                value = value[key]
            return value
        except (KeyError, TypeError, AttributeError):
            return None
            return None
