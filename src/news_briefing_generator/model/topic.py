from dataclasses import dataclass
from typing import Optional

@dataclass
class Topic:
    id: str
    title: str
    generated_at: str
    summary: Optional[str] = None