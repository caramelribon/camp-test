"""Retry utility with exponential backoff."""

import asyncio
import logging
from functools import wraps

from campaign_agent.config import MAX_RETRIES, RETRY_BACKOFF_BASE

logger = logging.getLogger(__name__)


async def retry_async(func, *args, max_retries=MAX_RETRIES, backoff_base=RETRY_BACKOFF_BASE, **kwargs):
    """Execute an async function with retry and exponential backoff.

    Args:
        func: Async callable to execute.
        *args: Positional arguments for func.
        max_retries: Maximum number of retry attempts (default: 3).
        backoff_base: Base seconds for exponential backoff (default: 1.0).
        **kwargs: Keyword arguments for func.

    Returns:
        The return value of func.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                wait = backoff_base * (2 ** (attempt - 1))
                logger.warning(
                    "Retry %d/%d for %s failed: %s — retrying in %.1fs",
                    attempt,
                    max_retries,
                    func.__name__,
                    e,
                    wait,
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    "All %d retries exhausted for %s: %s",
                    max_retries,
                    func.__name__,
                    e,
                )
    raise last_exception


def retry_sync(func, *args, max_retries=MAX_RETRIES, backoff_base=RETRY_BACKOFF_BASE, **kwargs):
    """Execute a sync function with retry and exponential backoff.

    Args:
        func: Callable to execute.
        *args: Positional arguments for func.
        max_retries: Maximum number of retry attempts (default: 3).
        backoff_base: Base seconds for exponential backoff (default: 1.0).
        **kwargs: Keyword arguments for func.

    Returns:
        The return value of func.

    Raises:
        The last exception if all retries are exhausted.
    """
    import time

    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                wait = backoff_base * (2 ** (attempt - 1))
                logger.warning(
                    "Retry %d/%d for %s failed: %s — retrying in %.1fs",
                    attempt,
                    max_retries,
                    func.__name__,
                    e,
                    wait,
                )
                time.sleep(wait)
            else:
                logger.error(
                    "All %d retries exhausted for %s: %s",
                    max_retries,
                    func.__name__,
                    e,
                )
    raise last_exception
