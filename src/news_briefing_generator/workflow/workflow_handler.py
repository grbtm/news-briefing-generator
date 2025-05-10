from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from news_briefing_generator.config.config_manager import ConfigManager
from news_briefing_generator.db.sqlite import DatabaseManager
from news_briefing_generator.llm.base import LLM
from news_briefing_generator.llm.ollama import OllamaModel
from news_briefing_generator.llm.openai import OpenAIModel
from news_briefing_generator.logging.manager import LoggerManager
from news_briefing_generator.model.task.base import Task, TaskContext
from news_briefing_generator.model.task.config import TaskConfig
from news_briefing_generator.model.task.result import TaskResult
from news_briefing_generator.tasks import TASK_REGISTRY
from news_briefing_generator.utils.datetime_ops import get_utc_now_formatted
from news_briefing_generator.utils.path_utils import resolve_config_path
from news_briefing_generator.utils.security import get_openai_api_key


class WorkflowHandler:
    """Manages workflow execution and task orchestration.

    The WorkflowHandler is responsible for loading workflow definitions from YAML files,
    instantiating tasks, executing them in dependency order, and managing the flow of data
    between tasks. It serves as the core orchestration engine for the news briefing generation
    system.

    Workflows are defined as a collection of tasks with dependencies, where each task is
    executed only after all its dependencies have completed successfully. Tasks can be
    configured with custom parameters, LLM configurations, and human review requirements.
    """

    def __init__(
        self,
        db: DatabaseManager,
        default_llm: LLM,
        conf: ConfigManager,
        logger_manager: LoggerManager,
        workflow_config_file: Optional[Path] = None,
    ):
        """Initialize a workflow handler with the specified configuration.

        Args:
            db: Database connection manager for task data persistence
            default_llm: Default LLM instance for tasks that don't specify their own
            conf: Configuration manager for accessing application settings
            logger_manager: Logger manager for creating task-specific loggers
            workflow_config_file: Path to workflow config file. If None, the default
                workflow_configs.yaml from the configs directory will be used. If provided,
                the file name will be resolved relative to the configs directory.
        """
        self.db = db
        self.default_llm = default_llm
        self.conf = conf
        self.logger_manager = logger_manager
        self.logger = logger_manager.get_logger(__name__)

        # Handle workflow config file path resolution
        if workflow_config_file is None:
            # Use default path resolution (workflow_configs.yaml in configs dir)
            self.workflow_path = resolve_config_path("workflow_configs.yaml")
        else:
            # If a file path/name is provided, use resolve_config_path to ensure
            # it's properly resolved relative to the configs directory
            self.workflow_path = resolve_config_path(workflow_config_file.name)

        # Verify file exists after resolution
        if not self.workflow_path.exists():
            raise FileNotFoundError(
                f"Workflow config file not found at {self.workflow_path}. "
                f"Make sure the file is placed inside the configs/ directory."
            )

        self._load_workflow_config(self.workflow_path)

    def _load_workflow_config(self, path: Path) -> None:
        """Load workflow definitions from YAML.

        The YAML file is expected to have the following structure:
        workflows:
            workflow_name1:
                tasks: [...]
            workflow_name2:
                tasks: [...]
        """
        try:
            with open(path) as f:
                config = yaml.safe_load(f)
                if not isinstance(config, dict) or "workflows" not in config:
                    raise ValueError(
                        f"Invalid workflow config format in {path}. "
                        "Expected top-level 'workflows' key"
                    )
                self.workflows = config["workflows"]
                self.logger.info(
                    f"Loaded {len(self.workflows)} workflow(s) from {path}: "
                    f"{', '.join(self.workflows.keys())}"
                )
        except Exception as e:
            self.logger.error(f"Failed to load workflow config: {str(e)}")
            raise

    def _get_task_instance(self, task_config: TaskConfig) -> Task:
        """Get task instance based on configuration."""
        if task_config.task_type not in TASK_REGISTRY:
            raise ValueError(f"Unknown task class: {task_config.task_type}")

        # Create task context
        context = TaskContext(
            db=self.db,
            conf=self.conf,
            logger_manager=self.logger_manager,
            llm=self._get_task_llm(task_config),
            params=task_config.params,
            workflow_data={},
        )

        # Instantiate task with context
        task_type = TASK_REGISTRY[task_config.task_type]
        return task_type(context)

    def _get_task_llm(self, task_config: TaskConfig) -> LLM:
        """Get LLM instance for task based on configuration."""
        if not task_config.llm_config:
            return self.default_llm

        llm_type = task_config.llm_config.get("type")
        if llm_type == "ollama":
            # Remove type from kwargs
            llm_kwargs = task_config.llm_config.copy()
            llm_kwargs.pop("type")

            # If default_llm is OllamaModel and base_url not specified in task config,
            # inherit from default_llm
            if (
                isinstance(self.default_llm, OllamaModel)
                and "base_url" not in llm_kwargs
                and hasattr(self.default_llm, "base_url")
            ):
                llm_kwargs["base_url"] = self.default_llm.base_url
                self.logger.debug(
                    f"Inheriting base_url from default LLM for task {task_config.name}"
                )

            return OllamaModel(**llm_kwargs)

        elif llm_type == "openai":
            # Remove type from kwargs
            llm_kwargs = task_config.llm_config.copy()
            llm_kwargs.pop("type")

            # Get API key from environment or config
            llm_kwargs["api_key"] = get_openai_api_key(self.conf)

            return OpenAIModel(**llm_kwargs)

        else:
            self.logger.warning(
                f"Unknown LLM type {llm_type} for task {task_config.name}, "
                "using default LLM"
            )
            return self.default_llm

    async def _execute_task(
        self, task_config: TaskConfig, workflow_context: Dict[str, Any]
    ) -> TaskResult:
        """Execute task instance with workflow context."""
        try:
            # Get task instance
            task = self._get_task_instance(task_config)

            # Update workflow data in context
            task.context.workflow_data = workflow_context.copy()

            # Log task configuration
            self.logger.info(
                f"\nExecuting task '{task_config.name}' of type '{task_config.task_type}' with config:"
                f"\n\tTask Context Parameters: {task.context.params}"
                f"\n\tLLM Config: {task.context.llm or 'None'}"
                f"\n\tHuman Review: {task_config.human_review}"
                f"\n\tDependencies: {task_config.depends_on or 'none'}"
            )

            # Execute task
            result = await task.execute()

            # Handle human review if configured
            while task_config.human_review and result.success:
                review_result = task.get_user_review(result)
                if review_result == "rejected":
                    result.success = False
                    result.error = "Rejected by human review"
                    return result
                elif review_result == "re-run":
                    self.logger.info(
                        f"Re-running task {task.name} with updated parameters:\n{task.context.params}"
                    )
                    result = await task.execute()
                else:
                    break

            return result

        except Exception as e:
            self.logger.error(f"Task execution failed: {str(e)}", exc_info=True)
            return TaskResult(
                task_name=task_config.name,
                success=False,
                created_at=get_utc_now_formatted(),
                error=str(e),
            )

    async def execute_workflow(self, workflow_name: str) -> Dict[str, TaskResult]:
        """Execute workflow by name."""
        if workflow_name not in self.workflows:
            raise ValueError(f"Unknown workflow: {workflow_name}")

        workflow = self.workflows[workflow_name]
        context: Dict[str, Any] = {}
        results: Dict[str, TaskResult] = {}

        self.logger.info(
            f"Executing workflow: {workflow_name} with configs: {self.conf.get_all_configs()}"
        )
        # Get all task configs first
        task_configs = [
            self._create_task_config(task_dict) for task_dict in workflow["tasks"]
        ]

        # Execute tasks in dependency order
        for i, task_config in enumerate(task_configs):

            # Check all dependencies first
            failed_deps = []
            for dep in task_config.depends_on:
                if dep not in results:
                    failed_deps.append(f"{dep} (not executed)")
                elif not results[dep].success:
                    failed_deps.append(f"{dep} (failed: {results[dep].error})")

            if failed_deps:
                error_msg = f"Dependencies failed for {task_config.name}: {', '.join(failed_deps)}"
                self.logger.error(error_msg)

                # Create failure result for this task
                results[task_config.name] = TaskResult(
                    task_name=task_config.name,
                    success=False,
                    created_at=get_utc_now_formatted(),
                    error=error_msg,
                    data={"failed_dependencies": failed_deps},
                    metrics={"dependency_failures": len(failed_deps)},
                )

                # Mark all remaining tasks as failed due to dependency chain
                self._mark_remaining_tasks_as_failed(
                    task_configs[i + 1 :],
                    results,
                    f"Skipped due to workflow failure: dependency chain broken",
                )

                # Stop workflow execution
                self.logger.error(
                    f"Workflow {workflow_name} stopped due to dependency failures"
                )
                break

            # Execute task
            result = await self._execute_task(task_config, context)
            results[task_config.name] = result

            # Stop on failure but mark remaining tasks as skipped
            if not result.success:
                self.logger.error(f"Workflow stopped: {task_config.name} failed")

                # Mark all remaining tasks as failed due to preceding task failure
                self._mark_remaining_tasks_as_failed(
                    task_configs[i + 1 :],
                    results,
                    f"Skipped due to failure of {task_config.name}",
                )

                break

            # Update context with result data
            context[task_config.name] = result.data or {}

        return results

    def _create_task_config(self, task_dict: Dict[str, Any]) -> TaskConfig:
        """Convert task dictionary from YAML to TaskConfig object.

        Args:
            task_dict: Raw task configuration from YAML

        Returns:
            TaskConfig object with parsed configuration
        """
        return TaskConfig(
            name=task_dict.get("name"),
            task_type=task_dict.get("task_type"),
            params=task_dict.get("params", {}),
            depends_on=task_dict.get("depends_on", []),
            human_review=task_dict.get("human_review", False),
            llm_config=task_dict.get("llm", None),
        )

    def _mark_remaining_tasks_as_failed(
        self,
        remaining_configs: list,
        results: Dict[str, TaskResult],
        error_message: str,
    ) -> None:
        """Mark all remaining tasks as failed with the provided error message."""
        for remaining_config in remaining_configs:
            results[remaining_config.name] = TaskResult(
                task_name=remaining_config.name,
                success=False,
                created_at=get_utc_now_formatted(),
                error=error_message,
                metrics={"skipped_due_to_workflow_failure": True},
            )
