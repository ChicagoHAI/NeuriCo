"""
Retry utilities for transient failures in API calls.

Provides a decorator and helper for retrying operations that may fail
due to rate limits, network issues, or temporary server errors.
"""

import time
import logging
from functools import wraps
from typing import Tuple, Type

logger = logging.getLogger(__name__)

# Default exceptions considered retryable
RETRYABLE_EXCEPTIONS: Tuple[Type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: Tuple[Type[BaseException], ...] = RETRYABLE_EXCEPTIONS,
):
    """
    Decorator that retries a function with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts (not counting the initial call).
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Maximum delay in seconds between retries.
        backoff_factor: Multiplier applied to the delay after each retry.
        retryable_exceptions: Tuple of exception types that trigger a retry.

    Returns:
        Decorated function that will retry on specified exceptions.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            delay = base_delay

            for attempt in range(1, max_retries + 2):  # +2: 1 initial + max_retries
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt == max_retries + 1:
                        # Exhausted all retries
                        logger.warning(
                            "All %d retries exhausted for %s: %s",
                            max_retries,
                            func.__name__,
                            e,
                        )
                        raise
                    logger.info(
                        "Retry %d/%d for %s after error: %s (waiting %.1fs)",
                        attempt,
                        max_retries,
                        func.__name__,
                        e,
                        delay,
                    )
                    time.sleep(delay)
                    delay = min(delay * backoff_factor, max_delay)

            # Should not be reached, but raise last exception as safety net
            raise last_exception  # pragma: no cover

        return wrapper

    return decorator


def call_with_retry(
    func,
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: Tuple[Type[BaseException], ...] = RETRYABLE_EXCEPTIONS,
    **kwargs,
):
    """
    Call a function with retry logic (non-decorator form).

    Args:
        func: Callable to invoke.
        *args: Positional arguments for func.
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay cap in seconds.
        backoff_factor: Multiplier for delay between retries.
        retryable_exceptions: Exception types that trigger a retry.
        **kwargs: Keyword arguments for func.

    Returns:
        The return value of func.

    Raises:
        The last exception if all retries are exhausted.
    """

    @retry_with_backoff(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        backoff_factor=backoff_factor,
        retryable_exceptions=retryable_exceptions,
    )
    def _inner():
        return func(*args, **kwargs)

    return _inner()
