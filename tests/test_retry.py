"""Tests for the retry module."""

from unittest.mock import MagicMock, patch

import pytest

from core.retry import retry, retry_call


class TestRetryDecorator:
    """Tests for the @retry decorator."""

    def test_succeeds_first_try(self):
        """Function that succeeds on first try is called once."""
        call_count = 0

        @retry(max_retries=3, base_delay=0.01)
        def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert succeed() == "ok"
        assert call_count == 1

    @patch("core.retry.time.sleep")
    def test_retries_on_failure_then_succeeds(self, mock_sleep):
        """Function that fails once then succeeds is retried."""
        call_count = 0

        @retry(max_retries=3, base_delay=1.0, retryable_exceptions=(ValueError,))
        def fail_once():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("transient error")
            return "ok"

        assert fail_once() == "ok"
        assert call_count == 2
        assert mock_sleep.call_count == 1

    @patch("core.retry.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep):
        """Function that always fails raises after max_retries."""
        call_count = 0

        @retry(max_retries=2, base_delay=1.0, retryable_exceptions=(RuntimeError,))
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("permanent error")

        with pytest.raises(RuntimeError, match="permanent error"):
            always_fail()

        # 1 initial + 2 retries = 3 total attempts
        assert call_count == 3
        assert mock_sleep.call_count == 2

    def test_only_retries_specified_exceptions(self):
        """Non-retryable exceptions are raised immediately."""
        call_count = 0

        @retry(max_retries=3, base_delay=0.01, retryable_exceptions=(ValueError,))
        def raise_type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("not retryable")

        with pytest.raises(TypeError, match="not retryable"):
            raise_type_error()

        assert call_count == 1  # No retry

    @patch("core.retry.time.sleep")
    def test_on_retry_callback_called(self, mock_sleep):
        """on_retry callback is invoked with correct arguments."""
        callback = MagicMock()
        call_count = 0

        @retry(max_retries=3, base_delay=1.0, on_retry=callback, retryable_exceptions=(ValueError,))
        def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError(f"fail {call_count}")
            return "ok"

        fail_twice()

        assert callback.call_count == 2
        # First retry: attempt=1, max_retries=3
        args = callback.call_args_list[0][0]
        assert args[0] == 1  # attempt
        assert args[1] == 3  # max_retries

    @patch("core.retry.time.sleep")
    @patch("core.retry.random.random", return_value=0.5)
    def test_exponential_backoff_with_jitter(self, mock_random, mock_sleep):
        """Backoff delays increase exponentially with jitter applied."""

        @retry(max_retries=3, base_delay=1.0, backoff_factor=2.0, retryable_exceptions=(ConnectionError,))
        def always_fail():
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            always_fail()

        # With random()=0.5, jitter factor = 0.5 + 0.5 = 1.0
        # So jittered delays = base * 1.0 = exact base values
        assert mock_sleep.call_count == 3
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays[0] == pytest.approx(1.0)   # 1.0 * 1.0
        assert delays[1] == pytest.approx(2.0)   # 2.0 * 1.0
        assert delays[2] == pytest.approx(4.0)   # 4.0 * 1.0

    @patch("core.retry.time.sleep")
    @patch("core.retry.random.random", return_value=0.5)
    def test_max_delay_cap(self, mock_random, mock_sleep):
        """Delay is capped at max_delay before jitter."""

        @retry(max_retries=4, base_delay=10.0, backoff_factor=3.0, max_delay=25.0,
               retryable_exceptions=(ConnectionError,))
        def always_fail():
            raise ConnectionError("fail")

        with pytest.raises(ConnectionError):
            always_fail()

        delays = [call.args[0] for call in mock_sleep.call_args_list]
        # base=10, 10*3=30->capped to 25, stays capped
        # With jitter factor 1.0: delays are exact base values
        assert delays[0] == pytest.approx(10.0)
        assert delays[1] == pytest.approx(25.0)   # capped from 30
        assert delays[2] == pytest.approx(25.0)   # stays capped

    def test_preserves_function_metadata(self):
        """Decorated function preserves original name and docstring."""

        @retry(max_retries=2)
        def my_function():
            """My docstring."""
            pass

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."

    @patch("core.retry.time.sleep")
    def test_jitter_varies_sleep_duration(self, mock_sleep):
        """Jitter ensures sleep duration varies (not pure exponential)."""

        @retry(max_retries=2, base_delay=1.0, retryable_exceptions=(ValueError,))
        def always_fail():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            always_fail()

        # With real random, jittered delay should be in range [0.5*base, 1.5*base)
        delay = mock_sleep.call_args_list[0].args[0]
        assert 0.5 <= delay < 1.5  # base_delay * jitter range


class TestRetryCall:
    """Tests for retry_call (non-decorator form)."""

    def test_succeeds_first_try(self):
        func = MagicMock(return_value="ok")
        result = retry_call(func, max_retries=3)
        assert result == "ok"
        assert func.call_count == 1

    @patch("core.retry.time.sleep")
    def test_retries_then_succeeds(self, mock_sleep):
        func = MagicMock(side_effect=[ValueError("fail"), "ok"])
        result = retry_call(func, max_retries=3, base_delay=1.0, retryable_exceptions=(ValueError,))
        assert result == "ok"

    def test_passes_args_and_kwargs(self):
        func = MagicMock(return_value="ok")
        retry_call(func, args=(1, 2), kwargs={"x": 3}, max_retries=1)
        func.assert_called_once_with(1, 2, x=3)

    @patch("core.retry.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep):
        func = MagicMock(side_effect=RuntimeError("fail"))
        with pytest.raises(RuntimeError, match="fail"):
            retry_call(func, max_retries=2, base_delay=1.0, retryable_exceptions=(RuntimeError,))
