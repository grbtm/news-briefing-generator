import tempfile
from pathlib import Path
from typing import Dict, Generator
from unittest.mock import MagicMock, patch

import pytest
import yaml

from news_briefing_generator.logging.manager import LoggerManager
from news_briefing_generator.model.task.base import Task, TaskContext
from news_briefing_generator.model.task.result import TaskResult


class MockTask(Task):
    """Mock task for testing workflow execution."""

    def __init__(self, context: TaskContext, should_succeed: bool = True) -> None:
        super().__init__(context)
        self.should_succeed: bool = should_succeed
        self.executed: bool = False

    @property
    def name(self) -> str:
        return self.context.params.get("task_name", "mock_task")

    @property
    def requires_llm(self) -> bool:
        return False

    async def execute(self) -> TaskResult:
        """Record that execution happened and return success/failure."""
        self.executed = True
        if self.should_succeed:
            return TaskResult(
                task_name=self.name,
                success=True,
                created_at="2023-01-01T00:00:00Z",
                data={"result": "Test passed"},
                metrics={"execution_count": 1},
            )
        else:
            return TaskResult(
                task_name=self.name,
                success=False,
                created_at="2023-01-01T00:00:00Z",
                error="Task configured to fail",
                metrics={"execution_count": 1},
            )


@pytest.fixture(scope="module")
def temp_workflow_config() -> Generator[Path, None, None]:
    """Create a temporary workflow config file."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        workflow_path = temp_dir_path / "workflow_configs.yaml"

        # Create a workflow config with proper structure
        workflow_config = {
            "workflows": {  # Note: This key is required by WorkflowHandler._load_workflow_config
                "test_workflow": {
                    "tasks": [
                        {
                            "name": "task1",
                            "task_type": "mock_task",
                            "params": {"task_name": "task1", "should_succeed": True},
                        },
                        {
                            "name": "task2",
                            "task_type": "mock_task",
                            "params": {"task_name": "task2", "should_succeed": True},
                            "depends_on": ["task1"],
                        },
                        {
                            "name": "task3",
                            "task_type": "mock_task",
                            "params": {"task_name": "task3", "should_succeed": True},
                            "depends_on": ["task1"],
                        },
                        {
                            "name": "task4",
                            "task_type": "mock_task",
                            "params": {"task_name": "task4", "should_succeed": True},
                            "depends_on": ["task2", "task3"],
                        },
                    ]
                },
                "test_workflow_with_failure": {
                    "tasks": [
                        {
                            "name": "task1",
                            "task_type": "mock_task",
                            "params": {"task_name": "task1", "should_succeed": True},
                        },
                        {
                            "name": "task2",
                            "task_type": "mock_task",
                            "params": {"task_name": "task2", "should_succeed": False},
                            "depends_on": ["task1"],
                        },
                        {
                            "name": "task3",
                            "task_type": "mock_task",
                            "params": {"task_name": "task3", "should_succeed": True},
                            "depends_on": [
                                "task2"
                            ],  # Should not run due to dependency failure
                        },
                    ]
                },
            }
        }

        with open(workflow_path, "w") as f:
            yaml.dump(workflow_config, f)

        yield workflow_path


@pytest.mark.asyncio
async def test_successful_workflow_execution(
    monkeypatch: pytest.MonkeyPatch, temp_workflow_config: Path
) -> None:
    """Test that a workflow executes all tasks successfully in dependency order."""
    # Mock path resolution BEFORE importing WorkflowHandler
    import news_briefing_generator.utils.path_utils

    def mock_resolve_config_path(filename: str) -> Path:
        return temp_workflow_config

    monkeypatch.setattr(
        news_briefing_generator.utils.path_utils,
        "resolve_config_path",
        mock_resolve_config_path,
    )

    # Import WorkflowHandler after mocking
    from news_briefing_generator.workflow.workflow_handler import WorkflowHandler

    # Mock dependencies
    db_mock: MagicMock = MagicMock()
    llm_mock: MagicMock = MagicMock()
    conf_mock: MagicMock = MagicMock()
    logger_manager: LoggerManager = LoggerManager()

    # Set up workflow handler
    with patch(
        "news_briefing_generator.workflow.workflow_handler.TASK_REGISTRY",
        {
            "mock_task": lambda ctx: MockTask(
                ctx, ctx.params.get("should_succeed", True)
            )
        },
    ):
        handler: WorkflowHandler = WorkflowHandler(
            db=db_mock,
            default_llm=llm_mock,
            conf=conf_mock,
            logger_manager=logger_manager,
            workflow_config_file=None,  # Will be redirected by mock
        )

        # Execute workflow
        results: Dict[str, TaskResult] = await handler.execute_workflow("test_workflow")

        # Verify all tasks executed successfully
        assert len(results) == 4
        for task_name, result in results.items():
            assert result.success, f"Task {task_name} failed unexpectedly"

        # Verify execution order respected dependencies
        task1_time: str = results["task1"].created_at
        task2_time: str = results["task2"].created_at
        task3_time: str = results["task3"].created_at
        task4_time: str = results["task4"].created_at

        # Check dependency order
        assert task1_time <= task2_time
        assert task1_time <= task3_time
        assert task2_time <= task4_time
        assert task3_time <= task4_time


@pytest.mark.asyncio
async def test_workflow_with_failed_dependency(
    monkeypatch: pytest.MonkeyPatch, temp_workflow_config: Path
) -> None:
    """Test that dependent tasks are skipped when a dependency fails."""
    # Mock path resolution BEFORE importing WorkflowHandler
    import importlib

    import news_briefing_generator.utils.path_utils

    importlib.reload(news_briefing_generator.utils.path_utils)

    def mock_resolve_config_path(filename: str) -> Path:
        return temp_workflow_config

    monkeypatch.setattr(
        news_briefing_generator.utils.path_utils,
        "resolve_config_path",
        mock_resolve_config_path,
    )

    # Import WorkflowHandler after mocking
    from news_briefing_generator.workflow.workflow_handler import WorkflowHandler

    # Mock dependencies
    db_mock: MagicMock = MagicMock()
    llm_mock: MagicMock = MagicMock()
    conf_mock: MagicMock = MagicMock()
    logger_manager: LoggerManager = LoggerManager()

    # Set up workflow handler
    with patch(
        "news_briefing_generator.workflow.workflow_handler.TASK_REGISTRY",
        {
            "mock_task": lambda ctx: MockTask(
                ctx, ctx.params.get("should_succeed", True)
            )
        },
    ):
        handler: WorkflowHandler = WorkflowHandler(
            db=db_mock,
            default_llm=llm_mock,
            conf=conf_mock,
            logger_manager=logger_manager,
            workflow_config_file=None,  # Will be redirected by mock
        )

        # Execute workflow with failure
        results: Dict[str, TaskResult] = await handler.execute_workflow(
            "test_workflow_with_failure"
        )

        # Verify task1 succeeded
        assert "task1" in results
        assert results["task1"].success

        # Verify task2 failed
        assert "task2" in results
        assert not results["task2"].success
        assert "configured to fail" in results["task2"].error

        # Verify task3 was skipped due to dependency failure

        assert "task3" in results
        assert not results["task3"].success
        assert "Skipped due to failure of" in results["task3"].error
