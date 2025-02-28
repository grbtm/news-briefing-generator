from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import typer

from news_briefing_generator.config.config_manager import (
    ConfigManager,
    ConfigSource,
    Parameter,
)
from news_briefing_generator.db.sqlite import DatabaseManager
from news_briefing_generator.llm.base import LLM
from news_briefing_generator.logging.manager import LoggerManager
from news_briefing_generator.model.task.result import TaskResult


@dataclass()
class TaskContext:
    """Common context for all tasks."""

    db: DatabaseManager
    conf: ConfigManager
    logger_manager: LoggerManager
    params: Dict[str, Any] = field(
        default_factory=dict
    )  # parameters from worflow config
    param_sources: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    workflow_data: Dict[str, Any] = field(default_factory=dict)  # For inter-task data
    llm: Optional[LLM] = None


class Task(ABC):
    """Base interface for workflow tasks."""

    def __init__(self, context: TaskContext):
        """Initialize task with application context.

        Args:
            context: Application context providing access to core dependencies
        """
        self.context = context
        self.logger = context.logger_manager.get_logger(
            f"tasks.{self.__class__.__name__}"
        )

    @abstractmethod
    async def execute(self) -> TaskResult:
        """Execute task with unified context."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Task identifier."""
        pass

    @property
    def requires_human_review(self) -> bool:
        """Whether task requires human review."""
        return False

    @property
    def requires_llm(self) -> bool:
        """Whether task requires LLM access."""
        return False

    def validate_context(self, context: TaskContext) -> None:
        """Validate task context requirements.

        Args:
            context: Task context to validate

        Raises:
            ValueError: If required LLM is missing
        """
        if self.requires_llm and context.llm is None:
            raise ValueError(f"Task {self.name} requires LLM but none provided")

    def get_parameter(self, name: str, default: Any = None) -> Any:
        """Get parameter with automatic resolution and tracking."""

        parameter: Parameter = self.context.conf.get_param(
            key=name,
            workflow_params=self.context.params,
            task_scope=self.name,
            default=default,
        )
        self._track_param_resolution(name, parameter.value, parameter.source)
        return parameter.value

    def get_user_review(self, result: TaskResult) -> str:
        """Handle user input about task results.

        Args:
            result: Task execution result

        Returns:
            str: "accepted", "rejected", or "re-run"
        """
        typer.echo(f"\nReview output for task: {self.name}")
        typer.echo("\nMetrics:")
        for key, value in result.metrics.items():
            typer.echo(f"  {key}: {value}")
        typer.echo("\nWarnings:")
        typer.echo(result.warning or "None")

        while True:
            typer.echo("\nOptions:")
            typer.echo("1. Approve")
            typer.echo("2. Re-run with different parameters")
            typer.echo("3. Reject")

            choice = typer.prompt("\nSelect option (1-3)", type=int)

            if choice == 1:
                return "accepted"
            elif choice == 2:
                try:
                    updated_params = self._get_updated_parameters()
                    self._update_task_parameters(updated_params)
                    return "re-run"
                except (ValueError, TypeError) as e:
                    self.logger.error(f"Parameter update failed: {e}")
                    typer.echo(f"Error updating parameters: {e}")
                return "rejected"
            elif choice == 3:
                return "rejected"
            else:
                typer.echo("Invalid choice, please try again")

    @staticmethod
    def _safe_convert_value(value: str, expected_type: type) -> Any:
        """Safely convert string value to expected type.

        Args:
            value: String value to convert
            expected_type: Target type for conversion

        Returns:
            Converted value

        Raises:
            ValueError: If conversion fails or type not supported
        """
        if expected_type == bool:
            return value.lower() in ("true", "1", "yes")
        elif expected_type == int:
            return int(value)
        elif expected_type == float:
            return float(value)
        elif expected_type == list:
            return [item.strip() for item in value.strip("[]").split(",")]
        elif expected_type == str:
            return value
        raise ValueError(f"Unsupported type: {expected_type}")

    def _track_param_resolution(
        self, name: str, value: Any, source: ConfigSource
    ) -> None:
        """Track parameter resolution internally."""
        self.context.param_sources[name] = {"value": value, "source": source.name}

    def _get_updated_parameters(self) -> Dict[str, Any]:
        """Get updated parameters from user input with source tracking.

        Shows all available parameters and their sources, allows updating any resolved
        parameter. New values will be added to workflow parameters, overriding any
        existing sources.

        Returns:
            Dict[str, Any]: Updated parameter dictionary
        """
        # Show all known parameters
        typer.echo("\nCurrent parameters:")

        def _get_status_indicator(name: str, source: str) -> str:
            """Get parameter status indicator."""
            if source == ConfigSource.WORKFLOW.name:
                return "[source= workflow config]"
            elif source == ConfigSource.ENVIRONMENT_VARIABLE.name:
                return "[source= environment variable]"
            elif source == ConfigSource.ENVIRONMENT_SETTINGS.name:
                return "[source= environment settings yaml]"
            elif source == ConfigSource.BASE_SETTINGS.name:
                return "[source= base settings yaml]"
            return "[default value]"

        # Show all parameters with clear source indication
        for name, param_info in self.context.param_sources.items():
            value = param_info["value"]
            source = param_info["source"]
            status = _get_status_indicator(name, source)
            typer.echo(f"  {name}: {value} ({source}) {status}")

        typer.echo("\nNote: Parameters can be overridden in order of precedence:")
        typer.echo("1. Workflow config (active overrides)")
        typer.echo("2. Environment variables")
        typer.echo("3. Environment settings")
        typer.echo("4. Base settings")
        typer.echo("5. Default values")

        # Get parameter updates
        updated_params = self.context.params.copy()
        typer.echo(
            "\nEnter parameters to update or override (parameter=value), empty line to finish:"
        )
        typer.echo(
            "Note: Updates will be added to workflow config, overriding all other sources"
        )

        while True:
            line = typer.prompt(
                "Parameter (parameter=value)", default="", show_default=False
            )
            if not line:
                break

            try:
                key, value = line.split("=")
                key = key.strip()

                # Allow any parameter that has been resolved
                if key in self.context.param_sources:
                    try:
                        param_type = type(self.context.param_sources[key]["value"])
                        value = self._safe_convert_value(value.strip(), param_type)
                        current_source = self.context.param_sources[key]["source"]
                        updated_params[key] = value
                        typer.echo(
                            f"Updated {key} = {value} "
                            f"(overriding previous value from {current_source})"
                        )
                    except Exception as e:
                        typer.echo(
                            f"Error converting value: {e}. "
                            f"Make sure the value matches the parameter type."
                        )
                else:
                    typer.echo(
                        f"Warning: '{key}' is not a known parameter. "
                        "Parameters must be defined in settings or workflow config first."
                    )
            except Exception as e:
                typer.echo(
                    f"Error parsing input: {e}\n"
                    f"Use format: parameter=value (e.g., timeout=30)"
                )

        return updated_params

    def _update_task_parameters(self, new_params: Dict[str, Any]) -> None:
        """Update task parameters with proper tracking and validation.

        Args:
            new_params: Dictionary of new parameter values
        """
        for name, value in new_params.items():
            # Validate parameter exists
            if name not in self.context.param_sources:
                raise ValueError(f"Unknown parameter: {name}")

            # Validate parameter type
            expected_type = type(self.context.param_sources[name]["value"])
            if not isinstance(value, expected_type):
                raise TypeError(
                    f"Parameter {name} must be of type {expected_type.__name__}"
                )

            # Update parameter value and tracking
            self.context.params[name] = value
            self._track_param_resolution(name, value, ConfigSource.WORKFLOW)
