"""
Retry utilities for transient failures in API calls and subprocess launches.

Provides a decorator and helper for retrying operations that may fail
due to rate limits, network issues, or temporary server errors.
"""

import time
import random
import functools
import logging
from typing import Tuple, Type, Optional, Callable

logger = logging.getLogger(__name__)

# Default exceptions considered retryable (network / OS-level transient errors)
RETRYABLE_EXCEPTIONS: Tuple[Type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: Tuple[Type[BaseException], ...] = RETRYABLE_EXCEPTIONS,
    on_retry: Optional[Callable] = None,
):
    """
    Decorator that retries a function with exponential backoff and jitter.

    Jitter is applied as ``delay * uniform(0.5, 1.5)`` to avoid thundering-herd
    problems when multiple processes retry concurrently.

    Args:
        max_retries: Maximum number of retry attempts (not counting the initial call).
        base_delay: Initial delay in seconds before the first retry.
        max_delay: Maximum delay in seconds between retries.
        backoff_factor: Multiplier applied to the delay after each retry.
        retryable_exceptions: Tuple of exception types that trigger a retry.
        on_retry: Optional callback(attempt, max_retries, error, delay) called
                  before each retry sleep. If None, uses default logger.info.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            delay = base_delay

            for attempt in range(1, max_retries + 2):  # +2: 1 initial + max_retries
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt == max_retries + 1:
                        logger.warning(
                            "All %d retries exhausted for %s: %s",
                            max_retries, func.__name__, e,
                        )
                        raise

                    # Apply jitter to avoid thundering herd
                    jittered_delay = delay * (0.5 + random.random())

                    if on_retry:
                        on_retry(attempt, max_retries, e, jittered_delay)
                    else:
                        logger.info(
                            "Retry %d/%d for %s after error: %s (waiting %.1fs)",
                            attempt, max_retries, func.__name__, e, jittered_delay,
                        )

                    time.sleep(jittered_delay)
                    delay = min(delay * backoff_factor, max_delay)

            raise last_exception  # pragma: no cover

        return wrapper
    return decorator


def retry_call(
    func: Callable,
    args: tuple = (),
    kwargs: Optional[dict] = None,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: Tuple[Type[BaseException], ...] = RETRYABLE_EXCEPTIONS,
    on_retry: Optional[Callable] = None,
):
    """
    Call a function with retry logic (non-decorator form).

    Useful when you can't decorate the function (e.g., third-party code)
    or want per-call retry configuration.

    Args:
        func: Callable to invoke.
        args: Positional arguments for func.
        kwargs: Keyword arguments for func.
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay cap in seconds.
        backoff_factor: Multiplier for delay between retries.
        retryable_exceptions: Exception types that trigger a retry.
        on_retry: Optional callback before each retry.

    Returns:
        The return value of func.
    """
    if kwargs is None:
        kwargs = {}

    @retry(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        backoff_factor=backoff_factor,
        retryable_exceptions=retryable_exceptions,
        on_retry=on_retry,
    )
    def _inner():
        return func(*args, **kwargs)

    return _inner()
