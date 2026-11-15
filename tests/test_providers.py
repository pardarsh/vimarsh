import json
from types import SimpleNamespace

import groq
import httpx
import pytest
from google.genai import errors, types

from vimarsh.config import Settings
from vimarsh.providers import ANALYSIS_SCHEMA, AllProvidersFailed, Router, build_providers
from vimarsh.providers.base import (
    TRUNCATION_MARKER,
    InputTooLargeError,
    ProviderError,
    TransientProviderError,
    build_prompt,
    estimate_tokens,
    parse_result,
    truncate,
)
from vimarsh.providers.gemini_adapter import GeminiProvider
from vimarsh.providers.groq_adapter import GroqProvider

from .conftest import FakeProvider, sample_result

RESULT_JSON = sample_result().model_dump_json()


def no_sleep(_seconds):
    pass


# --- base -------------------------------------------------------------------


def test_schema_has_required_fields():
    assert set(ANALYSIS_SCHEMA["required"]) == {
        "summary_short",
        "summary_detailed",
        "key_provisions",
        "affected_sectors",
        "fiscal_or_legal_impact",
    }


def test_truncate_keeps_short_text():
    assert truncate("abc", 10) == ("abc", False)


def test_truncate_keeps_head_and_tail():
    text = "HEAD" + "x" * 10_000 + "TAIL"
    cut, partial = truncate(text, 500)
    assert partial
    assert cut.startswith("HEAD") and cut.endswith("TAIL")
    assert TRUNCATION_MARKER in cut
    assert estimate_tokens(cut) <= 500


def test_prompt_notes_partial_text():
    assert "excerpt" not in build_prompt("full text", {})
    assert "excerpt" in build_prompt("a" + TRUNCATION_MARKER + "b", {})


def test_parse_result_rejects_bad_json():
    with pytest.raises(ProviderError, match="schema"):
        parse_result('{"summary_short": "x"}')


# --- router -----------------------------------------------------------------


def test_router_uses_primary():
    primary, fallback = FakeProvider("a"), FakeProvider("b")
    routed = Router([primary, fallback], 0, sleep=no_sleep).analyze("text")
    assert (routed.provider, routed.model_id, routed.partial) == ("a", "a-model-1", False)
    assert fallback.calls == []


def test_router_retries_then_falls_back():
    primary = FakeProvider("a", [TransientProviderError("429")] * 4)
    fallback = FakeProvider("b")
    routed = Router([primary, fallback], 0, max_retries=3, sleep=no_sleep).analyze("text")
    assert routed.fallback_errors == ["a: 429"]
    assert routed.attempts == 1
    assert routed.call == {"response_id": "b-response"}
    assert len(primary.calls) == 4  # one try plus three retries
    assert routed.provider == "b"


def test_router_recovers_after_transient_error():
    primary = FakeProvider("a", [TransientProviderError("503")])
    routed = Router([primary], 0, sleep=no_sleep).analyze("text")
    assert routed.provider == "a" and len(primary.calls) == 2
    assert routed.attempts == 2 and routed.fallback_errors == []


def test_router_does_not_retry_too_large():
    primary = FakeProvider("a", [InputTooLargeError("413")])
    fallback = FakeProvider("b")
    assert Router([primary, fallback], 0, sleep=no_sleep).analyze("text").provider == "b"
    assert len(primary.calls) == 1


def test_router_truncates_per_provider():
    small = FakeProvider("a", max_input_tokens=100)
    routed = Router([small], 0, sleep=no_sleep).analyze("x" * 10_000)
    assert routed.partial
    assert TRUNCATION_MARKER in small.calls[0]


def test_router_all_fail():
    providers = [
        FakeProvider("a", [ProviderError("bad")]),
        FakeProvider("b", [ProviderError("down")]),
    ]
    with pytest.raises(AllProvidersFailed, match="a: bad; b: down"):
        Router(providers, 0, sleep=no_sleep).analyze("text")
    with pytest.raises(AllProvidersFailed, match="no providers"):
        Router([], 0).analyze("text")


def test_router_throttles_between_calls():
    slept = []
    clock = iter([0.0, 0.0, 0.0, 2.0, 2.0, 2.0, 2.0]).__next__
    router = Router([FakeProvider("a")], 12, sleep=slept.append, clock=clock)
    router.analyze("one")
    router.analyze("two")
    assert slept == [10.0]


def test_build_providers_skips_missing_keys():
    providers = build_providers(Settings(gemini_api_key="g", groq_api_key=""))
    assert [p.name for p in providers] == ["gemini"]
    assert providers[0].model_id == "gemini-3.8-flash"


def test_build_providers_order_and_unknown():
    s = Settings(primary_provider="groq", fallback_provider="nope", groq_api_key="k")
    assert [p.name for p in build_providers(s)] == ["groq"]
    s = Settings(primary_provider="groq", fallback_provider="none", groq_api_key="k")
    assert [p.name for p in build_providers(s)] == ["groq"]


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("PRIMARY_PROVIDER", "GROQ")
    monkeypatch.setenv("MAX_BILLS_PER_RUN", "3")
    monkeypatch.setenv("REQUEST_DELAY_SECONDS", "1.5")
    s = Settings.from_env("/repo")
    assert (s.primary_provider, s.max_bills_per_run, s.request_delay_seconds) == ("groq", 3, 1.5)
    assert "key" not in repr(s).lower()


# --- gemini -----------------------------------------------------------------


class FakeGeminiModels:
    def __init__(self, outcome):
        self.outcome = outcome
        self.kwargs = None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return gemini_response(self.outcome)


def gemini_response(text):
    parts = [types.Part(text="Reading clause 2.", thought=True), types.Part(text=text)]
    return types.GenerateContentResponse(
        response_id="resp-1",
        model_version="gemini-3.8-flash-001",
        candidates=[types.Candidate(content=types.Content(parts=parts), finish_reason="STOP")],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=900,
            candidates_token_count=300,
            thoughts_token_count=120,
            total_token_count=1320,
        ),
    )


def gemini(outcome):
    models = FakeGeminiModels(outcome)
    return GeminiProvider("", "gemini-test", 1000, client=SimpleNamespace(models=models)), models


def test_gemini_success_requests_json_schema():
    provider, models = gemini(RESULT_JSON)
    assert provider.analyze_bill("bill", ANALYSIS_SCHEMA) == sample_result()
    assert models.kwargs["model"] == "gemini-test"
    assert models.kwargs["config"].response_json_schema == ANALYSIS_SCHEMA
    assert models.kwargs["config"].response_mime_type == "application/json"
    assert models.kwargs["config"].thinking_config.thinking_level.value.lower() == "low"
    assert models.kwargs["config"].automatic_function_calling.disable is True
    assert models.kwargs["config"].thinking_config.include_thoughts is True
    call = provider.last_call
    assert call["response_id"] == "resp-1"
    assert call["model_version"] == "gemini-3.8-flash-001"
    assert call["finish_reason"] == "STOP"
    assert call["thought_summary"] == "Reading clause 2."
    assert call["usage"] == {
        "prompt_tokens": 900,
        "output_tokens": 300,
        "thinking_tokens": 120,
        "total_tokens": 1320,
    }
    assert call["parameters"]["thinking_level"] == "low"


def test_gemini_without_thinking_level():
    models = FakeGeminiModels(RESULT_JSON)
    client = SimpleNamespace(models=models)
    GeminiProvider("", "m", 1000, thinking_level="", client=client).analyze_bill("b", {})
    assert models.kwargs["config"].thinking_config is None


def test_gemini_thinking_none_setting():
    s = Settings(gemini_api_key="g", gemini_thinking_level="none", request_timeout_seconds=5)
    assert build_providers(s)[0].thinking_level == ""


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (errors.APIError(429, {"error": {"message": "quota"}}), TransientProviderError),
        (errors.APIError(503, {"error": {"message": "overloaded"}}), TransientProviderError),
        (errors.APIError(400, {"error": {"message": "too many tokens"}}), InputTooLargeError),
        (errors.APIError(403, {"error": {"message": "denied"}}), ProviderError),
        (ConnectionError("reset"), TransientProviderError),
    ],
)
def test_gemini_error_mapping(error, expected):
    provider, _ = gemini(error)
    with pytest.raises(expected) as info:
        provider.analyze_bill("bill", ANALYSIS_SCHEMA)
    assert type(info.value) is expected


def test_gemini_empty_response():
    provider, _ = gemini("")
    with pytest.raises(ProviderError, match="empty"):
        provider.analyze_bill("bill", ANALYSIS_SCHEMA)


def test_gemini_needs_key():
    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        GeminiProvider("", "m", 1)


# --- groq -------------------------------------------------------------------


class FakeGroqCompletions:
    def __init__(self, outcome):
        self.outcome = outcome
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        message = SimpleNamespace(content=self.outcome)
        choice = SimpleNamespace(message=message, finish_reason="stop")
        return SimpleNamespace(
            id="chatcmpl-1",
            model="llama-test",
            system_fingerprint="fp_1",
            usage=SimpleNamespace(prompt_tokens=900, completion_tokens=300, total_tokens=1200),
            choices=[choice] if self.outcome else [],
        )


def groq_provider(outcome):
    completions = FakeGroqCompletions(outcome)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return GroqProvider("", "llama-test", 1000, client=client), completions


def status_error(code):
    response = httpx.Response(code, request=httpx.Request("POST", "https://api.groq.com/x"))
    return groq.APIStatusError(f"status {code}", response=response, body=None)


def test_groq_success_requests_json():
    provider, completions = groq_provider(RESULT_JSON)
    assert provider.analyze_bill("bill", ANALYSIS_SCHEMA) == sample_result()
    assert completions.kwargs["response_format"] == {"type": "json_object"}
    assert provider.last_call["response_id"] == "chatcmpl-1"
    assert provider.last_call["usage"]["total_tokens"] == 1200
    assert provider.last_call["finish_reason"] == "stop"
    assert json.dumps(ANALYSIS_SCHEMA) in completions.kwargs["messages"][1]["content"]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (status_error(429), TransientProviderError),
        (status_error(503), TransientProviderError),
        (status_error(413), InputTooLargeError),
        (status_error(401), ProviderError),
        (
            groq.APIConnectionError(request=httpx.Request("POST", "https://x")),
            TransientProviderError,
        ),
    ],
)
def test_groq_error_mapping(error, expected):
    provider, _ = groq_provider(error)
    with pytest.raises(expected) as info:
        provider.analyze_bill("bill", ANALYSIS_SCHEMA)
    assert type(info.value) is expected


def test_groq_empty_response():
    provider, _ = groq_provider(None)
    with pytest.raises(ProviderError, match="empty"):
        provider.analyze_bill("bill", ANALYSIS_SCHEMA)


def test_groq_needs_key():
    with pytest.raises(ProviderError, match="GROQ_API_KEY"):
        GroqProvider("", "m", 1)
