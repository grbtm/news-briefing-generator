from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from pytest import MonkeyPatch

from news_briefing_generator.config.config_manager import ConfigManager
from news_briefing_generator.logging.manager import LoggerManager
from news_briefing_generator.model.task.base import Task, TaskContext
from news_briefing_generator.model.task.result import TaskResult


class MockTask(Task):
    """Test task implementation."""

    @property
    def name(self) -> str:
        return "test_task"

    @property
    def requires_llm(self) -> bool:
        return False

    async def execute(self) -> TaskResult:
        """Dummy execute method."""
        return TaskResult(
            task_name=self.name, success=True, created_at="", data={}, metrics={}
        )


@pytest.fixture
def setup_test_task(temp_config_files: Path, monkeypatch: MonkeyPatch) -> MockTask:
    """Setup a test task with environment."""
    # Set up environment variable
    monkeypatch.setenv("NBG_TEST_TASK_PARAM", "env_var_value")

    # Create config files with task-scoped parameters
    base_settings = {
        "global_param": "base_global_value",
        "test_task": {"task_param": "base_task_value"},
    }
    with open(temp_config_files / "settings.yaml", "w") as f:
        yaml.dump(base_settings, f)

    # Create config manager
    config_manager = ConfigManager(
        config_path=temp_config_files / "settings.yaml", environment="development"
    )

    # Setup task context with workflow params
    workflow_params = {"workflow_param": "workflow_value"}

    # Create mocks for dependencies
    db_mock = MagicMock()
    logger_manager = LoggerManager()

    task_context = TaskContext(
        db=db_mock,
        conf=config_manager,
        logger_manager=logger_manager,
        params=workflow_params,
    )

    return MockTask(task_context)


def test_task_parameter_resolution(setup_test_task: MockTask) -> None:
    """Test parameter resolution through Task.get_parameter()."""
    task = setup_test_task

    # Test resolving workflow parameter
    assert task.get_parameter("workflow_param") == "workflow_value"

    # Test resolving global parameter from base settings
    assert task.get_parameter("global_param") == "base_global_value"

    # Test resolving task-scoped parameter
    assert task.get_parameter("task_param") == "base_task_value"

    # Test resolving with default
    assert (
        task.get_parameter("non_existent", default="default_value") == "default_value"
    )
