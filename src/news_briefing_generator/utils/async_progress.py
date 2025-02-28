import logging
import asyncio
import tqdm
from typing import TypeVar, List, Awaitable, Any
from typing import TypeVar, List


T = TypeVar("T")


async def track_async_progress(
    coroutines: List[Awaitable[T]],
    desc: str,
    logger: logging.Logger,
    unit: str = "items",
) -> List[T]:
    """Track progress of multiple coroutines with tqdm progress bar.

    Maintains input order of coroutines in returned results.

    Args:
        coroutines: List of coroutines to execute and track
        desc: Description for the progress bar
        logger: Logger instance for error reporting
        unit: Unit label for the progress bar

    Returns:
        List of results in same order as input coroutines
    """
    # Create and start all tasks immediately
    tasks = [asyncio.create_task(coro) for coro in coroutines]
    results = [None] * len(tasks)

    with tqdm.tqdm(total=len(tasks), desc=desc, unit=unit) as pbar:
        for index, task in enumerate(tasks):
            try:
                results[index] = await task
            except Exception as e:
                logger.error(f"Task {index} failed: {e}")
                results[index] = None
            finally:
                pbar.update(1)

    return results
