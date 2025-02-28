from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class TaskConfig:
    """Task configuration container."""

    name: str
    task_type: str
    depends_on: List[str]
    params: Dict[str, Any] = field(default_factory=dict)
    llm_config: Optional[Dict[str, Any]] = None
    human_review: bool = False
    max_retries: int = 0