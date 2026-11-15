"""Fallback chain, throttling, retries and token guardrails."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import Settings
from .base import (
    ANALYSIS_SCHEMA,
    AnalysisResult,
    LLMProvider,
    ProviderError,
    TransientProviderError,
    estimate_tokens,
    truncate,
)
from .gemini_adapter import GeminiProvider
from .groq_adapter import GroqProvider

log = logging.getLogger(__name__)


class AllProvidersFailed(Exception):
    pass


@dataclass
class RoutedResult:
    result: AnalysisResult
    provider: str
    model_id: str
    partial: bool
    input_tokens_estimate: int
    call: dict = field(default_factory=dict)
    latency_seconds: float = 0.0
    attempts: int = 1
    # Errors from providers tried before this one, if the chain fell back.
    fallback_errors: list[str] = field(default_factory=list)


class Router:
    def __init__(
        self,
        providers: list[LLMProvider],
        request_delay_seconds: float = 12.0,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.providers = providers
        self.delay = request_delay_seconds
        self.max_retries = max_retries
        self.sleep = sleep
        self.clock = clock
        self._last_call: float | None = None

    def _throttle(self) -> None:
        if self._last_call is not None:
            wait = self.delay - (self.clock() - self._last_call)
            if wait > 0:
                self.sleep(wait)
        self._last_call = self.clock()

    def _call(self, provider: LLMProvider, text: str) -> AnalysisResult:
        self._throttle()
        self._attempts += 1
        started = self.clock()
        try:
            return provider.analyze_bill(text, ANALYSIS_SCHEMA)
        finally:
            self._latency = self.clock() - started
            log.info("%s call took %.1fs", provider.name, self._latency)

    def analyze(self, text: str) -> RoutedResult:
        errors: list[str] = []
        for provider in self.providers:
            fitted, partial = truncate(text, provider.max_input_tokens)
            self._attempts, self._latency = 0, 0.0
            retrying = Retrying(
                stop=stop_after_attempt(self.max_retries + 1),
                wait=wait_exponential(multiplier=5, min=5, max=60),
                retry=retry_if_exception_type(TransientProviderError),
                sleep=self.sleep,
                reraise=True,
            )
            try:
                result = retrying(self._call, provider, fitted)
            except ProviderError as exc:
                log.warning("%s failed: %s", provider.name, exc)
                errors.append(f"{provider.name}: {exc}")
                continue
            return RoutedResult(
                result=result,
                provider=provider.name,
                model_id=provider.model_id,
                partial=partial,
                input_tokens_estimate=estimate_tokens(fitted),
                call=dict(getattr(provider, "last_call", None) or {}),
                latency_seconds=round(self._latency, 2),
                attempts=self._attempts,
                fallback_errors=errors,
            )
        raise AllProvidersFailed("; ".join(errors) or "no providers configured")


def build_providers(settings: Settings) -> list[LLMProvider]:
    """Providers in priority order; ones without an API key are skipped."""
    thinking = "" if settings.gemini_thinking_level == "none" else settings.gemini_thinking_level
    factories: dict[str, Callable[[], LLMProvider]] = {
        "gemini": lambda: GeminiProvider(
            settings.gemini_api_key,
            settings.gemini_model,
            settings.gemini_max_input_tokens,
            thinking_level=thinking,
            timeout_seconds=settings.request_timeout_seconds,
        ),
        "groq": lambda: GroqProvider(
            settings.groq_api_key,
            settings.groq_model,
            settings.groq_max_input_tokens,
            timeout_seconds=settings.request_timeout_seconds,
        ),
    }
    providers: list[LLMProvider] = []
    for name in dict.fromkeys([settings.primary_provider, settings.fallback_provider]):
        if not name or name == "none":
            continue
        if name not in factories:
            log.warning("Unknown provider %r; known: %s", name, ", ".join(factories))
            continue
        try:
            providers.append(factories[name]())
        except ProviderError as exc:
            log.warning("Provider %s unavailable: %s", name, exc)
    return providers
