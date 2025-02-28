import tempfile
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def temp_config_files() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)
