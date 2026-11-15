"""Groq through its official (OpenAI-compatible) SDK."""

from __future__ import annotations

import groq

from .base import (
    SYSTEM_PROMPT,
    AnalysisResult,
    InputTooLargeError,
    LLMProvider,
    ProviderError,
    TransientProviderError,
    build_prompt,
    parse_result,
)

TEMPERATURE = 0.2


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(
        self,
        api_key: str,
        model_id: str,
        max_input_tokens: int,
        timeout_seconds: float = 120,
        client=None,
    ):
        if not api_key and client is None:
            raise ProviderError("GROQ_API_KEY is not set")
        self.model_id = model_id
        self.max_input_tokens = max_input_tokens
        # Retries are handled by the router, so they are counted in one place.
        self.client = client or groq.Groq(api_key=api_key, max_retries=0, timeout=timeout_seconds)

    def analyze_bill(self, text: str, schema: dict) -> AnalysisResult:
        self.last_call = {}
        try:
            response = self.client.chat.completions.create(
                model=self.model_id,
                temperature=TEMPERATURE,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": build_prompt(text, schema)},
                ],
            )
        except groq.APIStatusError as exc:
            code = exc.status_code
            if code in (429, 500, 503, 504):
                raise TransientProviderError(f"groq {code}: {exc.message}") from exc
            if code == 413:
                raise InputTooLargeError(f"groq {code}: {exc.message}") from exc
            raise ProviderError(f"groq {code}: {exc.message}") from exc
        except groq.APIConnectionError as exc:  # includes timeouts
            raise TransientProviderError(f"groq request failed: {exc}") from exc
        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise ProviderError("groq returned an empty response")
        result = parse_result(content)
        usage = response.usage
        self.last_call = {
            "response_id": response.id,
            "model_version": response.model,
            "system_fingerprint": response.system_fingerprint,
            "finish_reason": response.choices[0].finish_reason,
            "parameters": {"temperature": TEMPERATURE, "response_format": "json_object"},
            "usage": {
                "prompt_tokens": usage.prompt_tokens if usage else None,
                "output_tokens": usage.completion_tokens if usage else None,
                "total_tokens": usage.total_tokens if usage else None,
            },
            "thought_summary": None,
        }
        return result
