import os
from pathlib import Path


def resolve_config_path(filename: str, env_var_name: str = "NBG_CONFIGS_DIR") -> Path:
    """Resolve configuration file path by checking multiple locations.

    Follows this resolution order:
    1. Environment variable (default: NBG_CONFIGS_DIR)
    2. /app/configs directory (Docker standard)
    3. ./configs directory relative to current working directory
    4. Relative path from module location

    Args:
        filename: Name of the config file to find
        env_var_name: Environment variable to check for config directory

    Returns:
        Path: Resolved path to the configuration file
    """
    # Define default config directory relative to this file
    default_config_dir = Path(__file__).parent.parent.parent.parent / "configs"

    # Check environment variable first
    if env_var_name in os.environ:
        env_path = Path(os.environ[env_var_name]) / filename
        if env_path.exists():
            return env_path

    # Common locations to check
    locations = [
        Path("/app/configs") / filename,  # Docker standard
        Path.cwd() / "configs" / filename,  # Current directory
        default_config_dir / filename,  # Module relative
    ]

    # Return first existing path
    for path in locations:
        if path.exists():
            return path

    # Default to the most likely location even if it doesn't exist
    # Error will be raised later if file is not found
    return default_config_dir / filename
