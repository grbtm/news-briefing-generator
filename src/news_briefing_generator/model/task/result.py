from dataclasses import dataclass
from typing import Any, Optional

# Warning message prefix for no-data scenarios
NO_DATA_WARNING = "NO_DATA_WARNING: "


@dataclass
class TaskResult:
    """Container for standardized task results.

    Attributes:
        task_name: Name of the task that generated this result
        success: Whether the task completed successfully
        created_at: Timestamp of result creation
        data: Task-specific output data
        error: Error message if task failed
        warning: Warning message for non-error edge cases (prefixed with NO_DATA_WARNING for no-data scenarios)
        metrics: Task-specific metrics
    """

    task_name: str
    success: bool
    created_at: str
    data: Optional[Any] = None
    error: Optional[str] = None
    warning: Optional[str] = None
    metrics: Optional[dict] = None
