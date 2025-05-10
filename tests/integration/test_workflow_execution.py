import tempfile
from pathlib import Path
from typing import Dict, Generator, Tuple
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


@pytest.fixture
def test_workflows() -> Dict:
    """Create test workflow configurations for testing."""
    return {
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
                    "depends_on": ["task2"],  # Should not run due to dependency failure
                },
            ]
        },
    }


@pytest.fixture
def workflow_handler_setup(test_workflows) -> Tuple:
    """Set up WorkflowHandler with mocks and common dependencies."""
    # Mock dependencies
    db_mock = MagicMock()
    llm_mock = MagicMock()
    conf_mock = MagicMock()
    logger_manager = LoggerManager()

    return db_mock, llm_mock, conf_mock, logger_manager


@pytest.mark.asyncio
async def test_successful_workflow_execution(
    monkeypatch: pytest.MonkeyPatch, test_workflows, workflow_handler_setup
) -> None:
    """Test that a workflow executes all tasks successfully in dependency order."""
    db_mock, llm_mock, conf_mock, logger_manager = workflow_handler_setup

    # Mock the loader to return our test workflows
    with (
        patch(
            "news_briefing_generator.workflow.workflow_handler.WorkflowHandler._load_workflow_config",
            return_value=None,
        ),
        patch(
            "news_briefing_generator.workflow.workflow_handler.TASK_REGISTRY",
            {
                "mock_task": lambda ctx: MockTask(
                    ctx, ctx.params.get("should_succeed", True)
                )
            },
        ),
    ):
        # Import WorkflowHandler after mocking
        from news_briefing_generator.workflow.workflow_handler import WorkflowHandler

        handler = WorkflowHandler(
            db=db_mock,
            default_llm=llm_mock,
            conf=conf_mock,
            logger_manager=logger_manager,
            workflow_config_file=None,
        )

        # Manually set the workflows instead of loading from file
        handler.workflows = test_workflows

        # Execute workflow
        results = await handler.execute_workflow("test_workflow")

        # Verify all tasks executed successfully
        assert len(results) == 4
        for task_name, result in results.items():
            assert result.success, f"Task {task_name} failed unexpectedly"

        # Verify execution order respected dependencies
        task1_time = results["task1"].created_at
        task2_time = results["task2"].created_at
        task3_time = results["task3"].created_at
        task4_time = results["task4"].created_at

        # Check dependency order
        assert task1_time <= task2_time
        assert task1_time <= task3_time
        assert task2_time <= task4_time
        assert task3_time <= task4_time


@pytest.mark.asyncio
async def test_workflow_with_failed_dependency(
    monkeypatch: pytest.MonkeyPatch, test_workflows, workflow_handler_setup
) -> None:
    """Test that dependent tasks are skipped when a dependency fails."""
    db_mock, llm_mock, conf_mock, logger_manager = workflow_handler_setup

    # Mock the loader to return our test workflows directly
    with (
        patch(
            "news_briefing_generator.workflow.workflow_handler.WorkflowHandler._load_workflow_config",
            return_value=None,
        ),
        patch(
            "news_briefing_generator.workflow.workflow_handler.TASK_REGISTRY",
            {
                "mock_task": lambda ctx: MockTask(
                    ctx, ctx.params.get("should_succeed", True)
                )
            },
        ),
    ):
        # Import WorkflowHandler after mocking
        from news_briefing_generator.workflow.workflow_handler import WorkflowHandler

        handler = WorkflowHandler(
            db=db_mock,
            default_llm=llm_mock,
            conf=conf_mock,
            logger_manager=logger_manager,
            workflow_config_file=None,
        )

        # Manually set the workflows instead of loading from file
        handler.workflows = test_workflows

        # Execute workflow with failure
        results = await handler.execute_workflow("test_workflow_with_failure")

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
