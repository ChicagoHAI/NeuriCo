from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import (
    Any,
    Awaitable,
    Callable,
    ClassVar,
    Generic,
    Literal,
    Protocol,
    TypedDict,
    TypeVar,
    Unpack,
    overload,
)

import httpx
from google.genai import Client
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.prompt_values import PromptValue
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.runnables.config import get_config_list
from langchain_core.runnables.utils import gather_with_concurrency
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from tenacity import (
    RetryCallState,
    RetryError,
    after_log,
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)
from tenacity.asyncio.retry import RetryBaseT as AsyncRetryBaseT
from tenacity.asyncio.retry import retry_all as async_retry_all
from tenacity.retry import RetryBaseT
from tenacity.stop import StopBaseT
from tenacity.wait import WaitBaseT

from ai2i.chain.computation import ChainComputation, ModelRunnable
from ai2i.chain.gemini.async_genai import AsyncChatGoogleGenAI
from ai2i.chain.models import (
    DEFAULT_BATCH_MAX_CONCURRENCY,
    LLMModel,
    LLMModelParams,
    anthropic_model_params,
    google_model_params,
    openai_model_params,
)

default_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MaboolTimeout:
    httpx_timeout: httpx.Timeout

    def total_seconds(self) -> float | None:
        total = 0.0
        if self.httpx_timeout.connect is not None:
            total += self.httpx_timeout.connect
        if self.httpx_timeout.read is not None:
            total += self.httpx_timeout.read
        if self.httpx_timeout.write is not None:
            total += self.httpx_timeout.write
        if self.httpx_timeout.pool is not None:
            total += self.httpx_timeout.pool

        if total == 0.0:
            return None
        return total


class Timeouts:
    tiny: ClassVar[MaboolTimeout] = MaboolTimeout(httpx.Timeout(10.0, read=5.0, write=3.0, connect=3.0))
    short: ClassVar[MaboolTimeout] = MaboolTimeout(httpx.Timeout(15.0, read=10.0, write=5.0, connect=15.0))
    medium: ClassVar[MaboolTimeout] = MaboolTimeout(httpx.Timeout(35.0, read=30.0, write=5.0, connect=15.0))
    long: ClassVar[MaboolTimeout] = MaboolTimeout(httpx.Timeout(60.0, read=30.0, write=45.0, connect=15.0))
    extra_long: ClassVar[MaboolTimeout] = MaboolTimeout(httpx.Timeout(120.0, read=60.0, write=90.0, connect=30.0))


class TenacityRetrySettings(TypedDict, total=False):
    sleep: Callable[[int | float], Awaitable[None] | None]
    stop: StopBaseT
    wait: WaitBaseT
    retry: RetryBaseT | AsyncRetryBaseT
    before: Callable[[RetryCallState], Awaitable[None] | None]
    after: Callable[[RetryCallState], Awaitable[None] | None]
    before_sleep: Callable[[RetryCallState], Awaitable[None] | None] | None
    reraise: bool
    retry_error_cls: type[RetryError]
    retry_error_callback: Callable[[RetryCallState], Awaitable[Any] | Any] | None


def default_retry_settings(logger: logging.Logger | None = None) -> TenacityRetrySettings:
    return {
        # mabool defaults
        "wait": wait_random_exponential(multiplier=0.5, max=10),
        "stop": stop_after_attempt(5),
        "after": after_log(logger if logger is not None else default_logger, logging.DEBUG),
    }


class BatchExecutionContextBase(TypedDict, total=False):
    max_concurrency: int


# We separate return_exceptions because this property influances the return type from a batch call
# so it will need to be treated differently from the other props in function signatures
class BatchExecutionContext(BatchExecutionContextBase, total=False):
    return_exceptions: bool


def _default_batch_execution_context() -> BatchExecutionContext:
    return {
        "max_concurrency": DEFAULT_BATCH_MAX_CONCURRENCY,
        "return_exceptions": False,
    }


IN = TypeVar("IN", contravariant=True)
OUT = TypeVar("OUT", covariant=True)


class LangChainModelFactory(Protocol):
    def __call__(self, model: LLMModel, timeout: MaboolTimeout, api_key: SecretStr | None = None) -> BaseChatModel: ...


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER = "OpenRouter"
OPENAI = "OpenAI"


def _openrouter_key_from_env() -> str | None:
    return os.environ.get("OPENROUTER_KEY") or os.environ.get("OPENROUTER_API_KEY") or None


def _openrouter_model_name(name: str) -> str:
    # OpenRouter model IDs are provider-prefixed and generally undated,
    # e.g. "gpt-4.1-2025-04-14" becomes "openai/gpt-4.1".
    if "/" in name:
        return name
    return f"openai/{re.sub(r'-\d{4}-\d{2}-\d{2}$', '', name)}"


def _openai_model_name(name: str) -> str:
    # The reverse mapping: direct OpenAI takes the bare ID ("openai/gpt-4.1" becomes "gpt-4.1").
    return name.removeprefix("openai/")


def _openai_chat_providers(
    model: LLMModel, timeout: MaboolTimeout, api_key: SecretStr | None = None
) -> list[tuple[str, BaseChatModel]]:
    # "openai" family models go through OpenRouter first when its key is
    # configured, then through direct OpenAI when that key is configured.
    params = openai_model_params(model.params)
    providers: list[tuple[str, BaseChatModel]] = []

    openrouter_key = _openrouter_key_from_env()
    if openrouter_key is not None:
        providers.append(
            (
                OPENROUTER,
                ChatOpenAI(
                    api_key=SecretStr(openrouter_key),
                    base_url=OPENROUTER_BASE_URL,
                    model=_openrouter_model_name(model.name),
                    model_kwargs={"response_format": {"type": "json_object"}},
                    timeout=timeout.httpx_timeout,
                    **params,
                ),
            )
        )

    if api_key is not None or os.environ.get("OPENAI_API_KEY") or not providers:
        providers.append(
            (
                OPENAI,
                ChatOpenAI(
                    api_key=api_key,
                    model=_openai_model_name(model.name),
                    model_kwargs={"response_format": {"type": "json_object"}},
                    timeout=timeout.httpx_timeout,
                    **params,
                ),
            )
        )

    return providers


def _openai_chat_factory(model: LLMModel, timeout: MaboolTimeout, api_key: SecretStr | None = None) -> BaseChatModel:
    return _openai_chat_providers(model, timeout, api_key)[0][1]


# How long a provider is skipped after it failed with a key-level error.
PROVIDER_COOLDOWN_SECONDS = 600.0

_KEY_ERROR_REASONS = {
    401: "invalid API key",
    402: "insufficient credits",
    403: "key limit exceeded or permission denied",
}

# provider name -> (monotonic time until which it is skipped, why it was marked down)
_providers_down: dict[str, tuple[float, str]] = {}


class LLMProvidersUnavailableError(RuntimeError):
    """Every configured LLM provider failed for credential, budget or quota reasons."""


def _provider_error(error: BaseException) -> BaseException:
    # The per-provider retries wrap the last error in a RetryError once they are used up.
    if isinstance(error, RetryError):
        return error.last_attempt.exception() or error
    return error


def _is_key_error(error: BaseException) -> bool:
    # Errors about the key itself; retrying the same provider cannot fix them.
    status = getattr(error, "status_code", None)
    return status in _KEY_ERROR_REASONS or (status == 429 and getattr(error, "code", None) == "insufficient_quota")


def _should_fall_back(error: BaseException) -> bool:
    return _is_key_error(error) or getattr(error, "status_code", None) == 429


def _describe_provider_error(error: BaseException) -> str:
    # Short and free of key material: a fixed reason plus the first clause of the provider's message.
    status = getattr(error, "status_code", None)
    reason = _KEY_ERROR_REASONS.get(status, "rate limit or quota exhausted")
    body = getattr(error, "body", None)
    message = body.get("message") if isinstance(body, dict) else None
    detail = re.split(r"[.:]\s|[.:]$|https?://|sk-", message)[0].strip()[:80] if isinstance(message, str) else ""
    return f"{reason} ({status} {type(error).__name__}{': ' + detail if detail else ''})"


def _without_key_error_retries(retry_settings: TenacityRetrySettings) -> TenacityRetrySettings:
    retry_on = retry_settings.get("retry", retry_if_exception_type())
    return {**retry_settings, "retry": async_retry_all(retry_on, retry_if_exception(lambda e: not _is_key_error(e)))}


class ProviderFallback(Runnable[PromptValue, BaseMessage]):
    """Try each provider in order, moving on when one fails for a reason its own retries cannot fix."""

    _providers: list[tuple[str, ModelRunnable]]
    _logger: logging.Logger

    def __init__(self, providers: list[tuple[str, ModelRunnable]], logger: logging.Logger | None = None) -> None:
        self._providers = providers
        self._logger = logger if logger is not None else default_logger
        super().__init__()

    async def ainvoke(self, input: PromptValue, config: RunnableConfig | None = None, **kwargs: Any) -> BaseMessage:
        failures: list[str] = []
        for i, (name, model) in enumerate(self._providers):
            down_until, down_reason = _providers_down.get(name, (0.0, ""))
            if time.monotonic() < down_until:
                failures.append(f"{name}: {down_reason} (not retried, marked down)")
                continue

            try:
                result = await model.ainvoke(input, config, **kwargs)
            except Exception as e:
                error = _provider_error(e)
                if not _should_fall_back(error):
                    raise
                description = _describe_provider_error(error)
                failures.append(f"{name}: {description}")
                fallback = f", falling back to {self._providers[i + 1][0]}" if i + 1 < len(self._providers) else ""
                if not _is_key_error(error):
                    self._logger.warning(f"LLM provider {name} failed with {type(error).__name__}{fallback}")
                else:
                    # calls already in flight fail too; only the first one logs
                    if _providers_down.get(name, (0.0, ""))[0] <= time.monotonic():
                        self._logger.warning(
                            f"LLM provider {name} failed with {type(error).__name__},"
                            f" marked down for {PROVIDER_COOLDOWN_SECONDS:.0f}s{fallback}"
                        )
                    _providers_down[name] = (time.monotonic() + PROVIDER_COOLDOWN_SECONDS, description)
                continue

            _providers_down.pop(name, None)
            return result

        raise LLMProvidersUnavailableError(
            "All LLM providers failed; this is a credentials or budget problem, not a bug. " + "; ".join(failures)
        )

    def invoke(self, input: PromptValue, config: RunnableConfig | None = None, **kwargs: Any) -> BaseMessage:
        raise NotImplementedError(f"No support for blocking calls in {self.__class__.__name__}")


def _anthropic_chat_factory(model: LLMModel, timeout: MaboolTimeout, api_key: SecretStr | None = None) -> BaseChatModel:
    secret_api_key = SecretStr("") if api_key is None else api_key
    params = anthropic_model_params(model.params)

    return ChatAnthropic(api_key=secret_api_key, model_name=model.name, timeout=timeout.total_seconds(), **params)


def _google_chat_factory_with_async(
    model: LLMModel, timeout: MaboolTimeout, api_key: SecretStr | None = None
) -> BaseChatModel:
    params = google_model_params(model.params)

    from google.genai.types import HttpOptions

    timeout_seconds = timeout.total_seconds()
    secret_api_key = str(api_key.get_secret_value()) if api_key else None
    return AsyncChatGoogleGenAI(
        model_name=model.name,
        client=Client(
            api_key=secret_api_key,
            http_options=HttpOptions(timeout=int(1000 * timeout_seconds) if timeout_seconds is not None else None),
        ),
        model_kwargs={
            "generation_config": {
                "response_mime_type": "application/json",
            },
            **params,
        },
    )


class JsonChatGoogleGenerativeAI(ChatGoogleGenerativeAI):
    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        return await super().ainvoke(
            *args,
            generation_config={
                "response_mime_type": "application/json",
            },
            **kwargs,
        )


def _google_chat_factory(model: LLMModel, timeout: MaboolTimeout, api_key: SecretStr | None = None) -> BaseChatModel:
    secret_api_key = None if api_key is None else api_key
    params = google_model_params(model.params)

    return JsonChatGoogleGenerativeAI(
        api_key=secret_api_key, model=model.name, timeout=timeout.total_seconds(), **params
    )


TrueLiteral = Literal[True]
FalseLiteral = Literal[False]


@dataclass(frozen=True)
class Execution(Generic[IN, OUT]):
    runnable: Runnable[IN, OUT]

    async def once(self, input: IN) -> OUT:
        return await self.runnable.ainvoke(input)

    # The following overload changes the return type based on the 'return_exception' parameter. If it's set to 'True'
    # The resulting list will contain elements of 'OUT | Exception', if it's False it will only contain 'OUT' elements
    @overload
    async def many(
        self, inputs: list[IN], *, return_exceptions: TrueLiteral, **batch_ec: Unpack[BatchExecutionContextBase]
    ) -> list[OUT | Exception]:
        pass

    @overload
    async def many(
        self,
        inputs: list[IN],
        *,
        return_exceptions: FalseLiteral = False,
        **batch_ec: Unpack[BatchExecutionContextBase],
    ) -> list[OUT]:
        pass

    async def many(
        self, inputs: list[IN], return_exceptions: bool = False, **batch_ec: Unpack[BatchExecutionContextBase]
    ) -> list[OUT | Exception] | list[OUT]:
        resolved_batch_ec: BatchExecutionContext = {
            **_default_batch_execution_context(),
            **batch_ec,
            "return_exceptions": return_exceptions,
        }
        return await self.runnable.abatch(
            inputs,
            config={"max_concurrency": resolved_batch_ec.get("max_concurrency")},
            return_exceptions=resolved_batch_ec["return_exceptions"],
        )


class RetryWithTenacity(Runnable[IN, OUT]):
    _decorated: Runnable[IN, OUT]
    _retry_settings: TenacityRetrySettings

    def __init__(self, decorated: Runnable[IN, OUT], retry_settings: TenacityRetrySettings) -> None:
        self._decorated = decorated
        self._retry_settings = retry_settings
        super().__init__()

    async def ainvoke(self, input: IN, config: RunnableConfig | None = None, **kwargs: Any) -> OUT:
        @retry(**self._retry_settings)
        async def invoke_with_retry() -> OUT:
            return await self._decorated.ainvoke(input, config, **kwargs)

        return await invoke_with_retry()

    def invoke(self, input: IN, config: RunnableConfig | None = None, **kwargs: Any) -> OUT:
        raise NotImplementedError(f"No support for blocking calls in {self.__class__.__name__}")

    async def abatch(
        self,
        inputs: list[IN],
        config: RunnableConfig | list[RunnableConfig] | None = None,
        *,
        return_exceptions: bool = False,
        **kwargs: Any | None,
    ) -> list[OUT]:
        # NOTE:this is the implementation from Runnable, in case of a batch we want
        #      retries to be on individual calls and not on the bach itself
        if not inputs:
            return []

        configs = get_config_list(config, len(inputs))

        async def ainvoke(input: IN, config: RunnableConfig) -> OUT | Exception:
            if return_exceptions:
                try:
                    return await self.ainvoke(input, config, **kwargs)
                except Exception as e:
                    return e
            else:
                return await self.ainvoke(input, config, **kwargs)

        coros = map(ainvoke, inputs, configs)
        return await gather_with_concurrency(configs[0].get("max_concurrency"), *coros)

    def batch(
        self,
        inputs: list[IN],
        config: RunnableConfig | list[RunnableConfig] | None = None,
        *,
        return_exceptions: bool = False,
        **kwargs: Any | None,
    ) -> list[OUT]:
        raise NotImplementedError(f"No support for blocking calls in {self.__class__.__name__}")


@dataclass(frozen=True)
class LLMEndpoint:
    default_retry_settings: TenacityRetrySettings
    default_timeout: MaboolTimeout
    default_model: LLMModel
    model_factory: LangChainModelFactory
    api_key: SecretStr | None = None

    def timeout(self, timeout: MaboolTimeout) -> LLMEndpoint:
        return LLMEndpoint(self.default_retry_settings, timeout, self.default_model, self.model_factory, self.api_key)

    def model(self, model: LLMModel) -> LLMEndpoint:
        return LLMEndpoint(self.default_retry_settings, self.default_timeout, model, self.model_factory, self.api_key)

    def model_params(self, **params: Unpack[LLMModelParams]) -> LLMEndpoint:
        return LLMEndpoint(
            self.default_retry_settings,
            self.default_timeout,
            self.default_model.override(**params),
            self.model_factory,
            self.api_key,
        )

    def retry_settings(self, **kwargs: Unpack[TenacityRetrySettings]) -> LLMEndpoint:
        return LLMEndpoint(
            {**self.default_retry_settings, **kwargs},
            self.default_timeout,
            self.default_model,
            self.model_factory,
            self.api_key,
        )

    def with_api_key(self, api_key: SecretStr) -> LLMEndpoint:
        return LLMEndpoint(
            self.default_retry_settings, self.default_timeout, self.default_model, self.model_factory, api_key
        )

    def execute(self, computation: ChainComputation[IN, OUT]) -> Execution[IN, OUT]:
        def model_factory() -> ModelRunnable:
            if self.model_factory is _openai_chat_factory:
                providers = _openai_chat_providers(self.default_model, self.default_timeout, self.api_key)
                if len(providers) > 1:
                    # retries stay per provider; key-level errors skip them and fall back right away
                    retry_settings = _without_key_error_retries(self.default_retry_settings)
                    return ProviderFallback(
                        [(name, RetryWithTenacity(model, retry_settings)) for name, model in providers]
                    )

            model = self.model_factory(self.default_model, self.default_timeout, self.api_key)
            # decorate with retries
            return RetryWithTenacity(model, self.default_retry_settings)

        runnable = computation.build_runnable(model_factory)
        return Execution(runnable)


def define_llm_endpoint(
    *,
    default_timeout: MaboolTimeout | None = None,
    default_model: LLMModel | None = None,
    logger: logging.Logger | None = None,
    api_key: SecretStr | None = None,
    **retry_settings: Unpack[TenacityRetrySettings],
) -> LLMEndpoint:
    def default_endpoint_from_model(model: LLMModel) -> LLMEndpoint:
        match model.family:
            case "openai":
                factory = _openai_chat_factory
            case "anthropic":
                factory = _anthropic_chat_factory
            case "google":
                factory = _google_chat_factory_with_async
            case family:
                raise ValueError(
                    f"Invalid family name: {family}, supported families are `openai`, `anthropic`, and `google`."
                )

        return LLMEndpoint(
            {**default_retry_settings(logger), **retry_settings},
            default_timeout if default_timeout is not None else Timeouts.short,
            model,
            factory,
            api_key,
        )

    if default_model is None:
        return LLMEndpoint(
            {**default_retry_settings(logger), **retry_settings},
            default_timeout if default_timeout is not None else Timeouts.short,
            LLMModel.gpt4o(),
            _openai_chat_factory,
            api_key,
        )

    return default_endpoint_from_model(default_model)
