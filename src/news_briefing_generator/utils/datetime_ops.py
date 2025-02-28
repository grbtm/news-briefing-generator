from datetime import datetime, timezone


# TODO change to ISO_8601_FORMAT = "%Y-%m-%dT%H:%M:%S%z" -> confirm works w sqlite
def get_utc_now_formatted() -> str:
    """Get the current UTC time formatted as a string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S%z")


def get_utc_now_simple() -> str:
    """Get the current UTC time formatted as a simple string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M")
