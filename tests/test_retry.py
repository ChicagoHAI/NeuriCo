"""Tests for the retry module."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add src to path so we can import core modules
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.retry import call_with_retry, retry_with_backoff


class TestRetryWithBackoff:
    """Tests for the retry_with_backoff decorator."""

    def test_succeeds_on_first_try(self):
        call_count = 0

        @retry_with_backoff(max_retries=3, base_delay=0.01)
        def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert succeed() == "ok"
        assert call_count == 1

    def test_retries_on_transient_failure(self):
        call_count = 0

        @retry_with_backoff(
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=(ConnectionError,),
        )
        def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("transient")
            return "ok"

        assert fail_then_succeed() == "ok"
        assert call_count == 3

    def test_raises_after_max_retries(self):
        call_count = 0

        @retry_with_backoff(
            max_retries=2,
            base_delay=0.01,
            retryable_exceptions=(ConnectionError,),
        )
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("permanent")

        with pytest.raises(ConnectionError, match="permanent"):
            always_fail()
        # 1 initial + 2 retries = 3 total
        assert call_count == 3

    def test_does_not_retry_non_retryable_exceptions(self):
        call_count = 0

        @retry_with_backoff(
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=(ConnectionError,),
        )
        def raise_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError, match="not retryable"):
            raise_value_error()
        assert call_count == 1

    @patch("core.retry.time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep):
        call_count = 0

        @retry_with_backoff(
            max_retries=3,
            base_delay=1.0,
            backoff_factor=2.0,
            max_delay=60.0,
            retryable_exceptions=(ConnectionError,),
        )
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            always_fail()

        # Should have slept 3 times (before retries 1, 2, 3)
        assert mock_sleep.call_count == 3
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays[0] == 1.0
        assert delays[1] == 2.0
        assert delays[2] == 4.0

    @patch("core.retry.time.sleep")
    def test_max_delay_cap(self, mock_sleep):
        call_count = 0

        @retry_with_backoff(
            max_retries=4,
            base_delay=10.0,
            backoff_factor=3.0,
            max_delay=25.0,
            retryable_exceptions=(ConnectionError,),
        )
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            always_fail()

        delays = [call.args[0] for call in mock_sleep.call_args_list]
        # base=10, 10*3=30->capped to 25, 25*3=75->capped to 25, ...
        assert delays[0] == 10.0
        assert delays[1] == 25.0  # capped
        assert delays[2] == 25.0  # stays capped


class TestCallWithRetry:
    """Tests for the call_with_retry helper."""

    def test_calls_function_with_args(self):
        def add(a, b):
            return a + b

        result = call_with_retry(add, 2, 3, base_delay=0.01)
        assert result == 5

    def test_calls_function_with_kwargs(self):
        def greet(name, greeting="hello"):
            return f"{greeting} {name}"

        result = call_with_retry(greet, "world", greeting="hi", base_delay=0.01)
        assert result == "hi world"

    def test_retries_on_failure(self):
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise TimeoutError("timeout")
            return "done"

        result = call_with_retry(
            flaky,
            max_retries=3,
            base_delay=0.01,
            retryable_exceptions=(TimeoutError,),
        )
        assert result == "done"
        assert call_count == 2

    def test_raises_after_exhaustion(self):
        def always_fail():
            raise OSError("network down")

        with pytest.raises(OSError, match="network down"):
            call_with_retry(
                always_fail,
                max_retries=2,
                base_delay=0.01,
                retryable_exceptions=(OSError,),
            )
