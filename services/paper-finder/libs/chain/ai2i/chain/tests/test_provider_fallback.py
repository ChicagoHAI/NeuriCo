import logging
import time
from typing import Any, TypedDict

import httpx
import openai
import pytest
from langchain_core.messages import BaseMessage
from langchain_core.prompt_values import PromptValue
from langchain_core.runnables import Runnable, RunnableConfig
from pydantic import BaseModel, SecretStr
from tenacity import RetryError, stop_after_attempt, wait_none

from ai2i.chain import endpoints
from ai2i.chain.builders import define_prompt_llm_call
from ai2i.chain.endpoints import (
    OPENAI,
    OPENROUTER,
    OPENROUTER_BASE_URL,
    LLMProvidersUnavailableError,
    define_llm_endpoint,
)
from ai2i.chain.models import LLMModel

OPENROUTER_SECRET = "sk-or-v1-test-openrouter-secret"
OPENAI_SECRET = "sk-proj-test-openai-secret"
MAX_ATTEMPTS = 3


class SomeInput(TypedDict):
    input: str


class SomeResponse(BaseModel):
    value: str


def _status_error(cls: type[openai.APIStatusError], status: int, message: str, **body: Any) -> openai.APIStatusError:
    response = httpx.Response(status, request=httpx.Request("POST", "https://llm.test/v1/chat/completions"))
    return cls(f"Error code: {status} - {message}", response=response, body={"message": message, **body})


def key_limit_error() -> openai.APIStatusError:
    return _status_error(
        openai.PermissionDeniedError,
        403,
        f"Key limit exceeded (daily limit). Manage it using https://openrouter.ai/keys/{OPENROUTER_SECRET}",
    )


def invalid_key_error() -> openai.APIStatusError:
    return _status_error(openai.AuthenticationError, 401, f"Incorrect API key provided: {OPENAI_SECRET}.")


def no_credits_error() -> openai.APIStatusError:
    return _status_error(openai.APIStatusError, 402, "Insufficient credits")


def rate_limit_error() -> openai.APIStatusError:
    return _status_error(openai.RateLimitError, 429, "Rate limit reached")


def bad_request_error() -> openai.APIStatusError:
    return _status_error(openai.BadRequestError, 400, "This model's maximum context length is 1047576 tokens")


class FakeProviders:
    """Stands in for ChatOpenAI: records how each provider was built and called, and fails on demand."""

    def __init__(self) -> None:
        self.errors: dict[str, list[Exception]] = {OPENROUTER: [], OPENAI: []}
        self.always: dict[str, Exception] = {}
        self.calls: list[str] = []
        self.models: dict[str, str] = {}
        self.keys: dict[str, SecretStr | None] = {}

    def build(self, *, api_key: SecretStr | None, model: str, base_url: str | None = None, **_: Any) -> Runnable:
        name = OPENROUTER if base_url == OPENROUTER_BASE_URL else OPENAI
        self.models[name] = model
        self.keys[name] = api_key
        return _FakeChatModel(name, self)

    def count(self, name: str) -> int:
        return self.calls.count(name)


class _FakeChatModel(Runnable[PromptValue, BaseMessage]):
    def __init__(self, name: str, providers: FakeProviders) -> None:
        self.name = name
        self.providers = providers

    async def ainvoke(self, input: PromptValue, config: RunnableConfig | None = None, **kwargs: Any) -> BaseMessage:
        self.providers.calls.append(self.name)
        if self.name in self.providers.always:
            raise self.providers.always[self.name]
        if self.providers.errors[self.name]:
            raise self.providers.errors[self.name].pop(0)
        return BaseMessage(content=SomeResponse(value=self.name).model_dump_json(), type="test")

    def invoke(self, input: PromptValue, config: RunnableConfig | None = None, **kwargs: Any) -> BaseMessage:
        raise NotImplementedError


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch) -> FakeProviders:
    fake = FakeProviders()
    monkeypatch.setattr(endpoints, "ChatOpenAI", fake.build)
    monkeypatch.setattr(endpoints, "_providers_down", {})
    for name in ("OPENROUTER_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return fake


@pytest.fixture
def both_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_KEY", OPENROUTER_SECRET)
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_SECRET)


async def search(api_key: SecretStr | None = None) -> str:
    call = define_prompt_llm_call("{input}", input_type=SomeInput, output_type=SomeResponse).map(lambda s: s.value)
    endpoint = define_llm_endpoint(
        default_model=LLMModel.from_name("openai:gpt-4.1-2025-04-14"),
        api_key=api_key,
        wait=wait_none(),
        stop=stop_after_attempt(MAX_ATTEMPTS),
    )
    return await endpoint.execute(call).once({"input": "q"})


def assert_no_secrets(text: str) -> None:
    assert OPENROUTER_SECRET not in text and OPENAI_SECRET not in text and "sk-" not in text


async def test_primary_succeeds(providers: FakeProviders, both_keys: None) -> None:
    assert await search() == OPENROUTER
    assert providers.calls == [OPENROUTER]


@pytest.mark.parametrize("make_error", [key_limit_error, invalid_key_error, no_credits_error])
async def test_key_error_on_primary_falls_back_without_retries(
    providers: FakeProviders, both_keys: None, caplog: pytest.LogCaptureFixture, make_error: Any
) -> None:
    providers.always[OPENROUTER] = make_error()

    with caplog.at_level(logging.WARNING, logger=endpoints.__name__):
        assert await search() == OPENAI

    assert providers.calls == [OPENROUTER, OPENAI]
    error_name = type(providers.always[OPENROUTER]).__name__
    messages = [r.getMessage() for r in caplog.records if r.name == endpoints.__name__]
    assert messages == [
        f"LLM provider OpenRouter failed with {error_name}, marked down for 600s, falling back to OpenAI"
    ]
    assert_no_secrets(caplog.text)


async def test_rate_limit_falls_back_after_retries_and_does_not_mark_down(
    providers: FakeProviders, both_keys: None
) -> None:
    providers.always[OPENROUTER] = rate_limit_error()

    assert await search() == OPENAI
    assert providers.count(OPENROUTER) == MAX_ATTEMPTS
    assert endpoints._providers_down == {}

    assert await search() == OPENAI
    assert providers.count(OPENROUTER) == 2 * MAX_ATTEMPTS


async def test_transient_rate_limit_is_retried_on_primary(providers: FakeProviders, both_keys: None) -> None:
    providers.errors[OPENROUTER] = [rate_limit_error()]

    assert await search() == OPENROUTER
    assert providers.calls == [OPENROUTER, OPENROUTER]


async def test_bad_request_propagates_without_fallback(providers: FakeProviders, both_keys: None) -> None:
    providers.always[OPENROUTER] = bad_request_error()

    with pytest.raises(RetryError) as raised:
        await search()

    assert isinstance(raised.value.last_attempt.exception(), openai.BadRequestError)
    assert providers.count(OPENAI) == 0
    assert endpoints._providers_down == {}


async def test_bad_request_on_secondary_is_not_masked(providers: FakeProviders, both_keys: None) -> None:
    providers.always[OPENROUTER] = key_limit_error()
    providers.always[OPENAI] = bad_request_error()

    with pytest.raises(RetryError) as raised:
        await search()

    assert isinstance(raised.value.last_attempt.exception(), openai.BadRequestError)


async def test_both_fail_raises_combined_error(providers: FakeProviders, both_keys: None) -> None:
    providers.always[OPENROUTER] = key_limit_error()
    providers.always[OPENAI] = invalid_key_error()

    with pytest.raises(LLMProvidersUnavailableError) as raised:
        await search()

    message = str(raised.value)
    assert "credentials or budget problem" in message
    assert (
        "OpenRouter: key limit exceeded or permission denied (403 PermissionDeniedError: Key limit exceeded" in message
    )
    assert "OpenAI: invalid API key (401 AuthenticationError: Incorrect API key provided)" in message
    assert_no_secrets(message)
    assert providers.calls == [OPENROUTER, OPENAI]

    # both are now marked down: the next call fails the same way without any request
    with pytest.raises(LLMProvidersUnavailableError, match="OpenRouter: .*marked down.*OpenAI: .*marked down"):
        await search()
    assert providers.calls == [OPENROUTER, OPENAI]


async def test_circuit_breaker_skips_down_provider_then_retries_after_window(
    providers: FakeProviders, both_keys: None, caplog: pytest.LogCaptureFixture
) -> None:
    providers.always[OPENROUTER] = key_limit_error()
    assert await search() == OPENAI
    assert providers.count(OPENROUTER) == 1

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=endpoints.__name__):
        for _ in range(3):
            assert await search() == OPENAI
    assert providers.count(OPENROUTER) == 1
    assert caplog.records == []

    down_until, reason = endpoints._providers_down[OPENROUTER]
    assert 0 < down_until - time.monotonic() <= endpoints.PROVIDER_COOLDOWN_SECONDS

    # window over, still failing: one more request, then marked down again
    endpoints._providers_down[OPENROUTER] = (time.monotonic() - 1, reason)
    assert await search() == OPENAI
    assert providers.count(OPENROUTER) == 2
    assert endpoints._providers_down[OPENROUTER][0] > time.monotonic()

    # window over, provider recovered: back on the primary and no longer marked down
    endpoints._providers_down[OPENROUTER] = (time.monotonic() - 1, reason)
    del providers.always[OPENROUTER]
    assert await search() == OPENROUTER
    assert OPENROUTER not in endpoints._providers_down


async def test_only_openrouter_key_has_no_fallback(providers: FakeProviders, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", OPENROUTER_SECRET)
    providers.always[OPENROUTER] = key_limit_error()

    with pytest.raises(RetryError):
        await search()

    assert providers.count(OPENAI) == 0
    assert OPENAI not in providers.models
    assert providers.count(OPENROUTER) == MAX_ATTEMPTS  # unchanged single-provider behaviour
    assert endpoints._providers_down == {}


async def test_only_openai_key_has_no_fallback(providers: FakeProviders) -> None:
    providers.always[OPENAI] = invalid_key_error()

    with pytest.raises(RetryError):
        await search(api_key=SecretStr(OPENAI_SECRET))

    assert OPENROUTER not in providers.models
    assert providers.count(OPENAI) == MAX_ATTEMPTS


async def test_openai_key_from_config_enables_fallback(
    providers: FakeProviders, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_KEY", OPENROUTER_SECRET)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    providers.always[OPENROUTER] = key_limit_error()

    assert await search(api_key=SecretStr(OPENAI_SECRET)) == OPENAI


async def test_model_id_and_key_per_provider(providers: FakeProviders, both_keys: None) -> None:
    providers.always[OPENROUTER] = key_limit_error()
    await search(api_key=SecretStr(OPENAI_SECRET))

    assert providers.models == {OPENROUTER: "openai/gpt-4.1", OPENAI: "gpt-4.1-2025-04-14"}
    key = providers.keys[OPENROUTER]
    assert key is not None and key.get_secret_value() == OPENROUTER_SECRET
    key = providers.keys[OPENAI]
    assert key is not None and key.get_secret_value() == OPENAI_SECRET


def test_model_name_mapping() -> None:
    assert endpoints._openrouter_model_name("gpt-4.1-2025-04-14") == "openai/gpt-4.1"
    assert endpoints._openrouter_model_name("gpt-4o") == "openai/gpt-4o"
    assert endpoints._openrouter_model_name("openai/gpt-4.1") == "openai/gpt-4.1"
    assert endpoints._openai_model_name("openai/gpt-4.1") == "gpt-4.1"
    assert endpoints._openai_model_name("gpt-4.1-2025-04-14") == "gpt-4.1-2025-04-14"
