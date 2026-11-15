"""Google Gemini through the official google-genai SDK."""

from __future__ import annotations

from google import genai
from google.genai import errors, types

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


def map_status(code: int | None, message: str) -> ProviderError:
    if code in (429, 500, 503, 504):
        return TransientProviderError(f"gemini {code}: {message}")
    if code == 413 or (code == 400 and "token" in message.lower()):
        return InputTooLargeError(f"gemini {code}: {message}")
    return ProviderError(f"gemini {code}: {message}")


TEMPERATURE = 0.2


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model_id: str,
        max_input_tokens: int,
        thinking_level: str = "low",
        timeout_seconds: float = 300,
        client=None,
    ):
        if not api_key and client is None:
            raise ProviderError("GEMINI_API_KEY is not set")
        self.model_id = model_id
        self.max_input_tokens = max_input_tokens
        self.thinking_level = thinking_level
        # Without a timeout an overloaded model can hold a request for minutes;
        # a timeout counts as transient, so it is retried or falls back.
        self.client = client or genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000))
        )

    def analyze_bill(self, text: str, schema: dict) -> AnalysisResult:
        self.last_call = {}
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=TEMPERATURE,
            response_mime_type="application/json",
            response_json_schema=schema,
            # Summarising a bill needs little reasoning; deep thinking mostly adds latency.
            thinking_config=(
                # include_thoughts returns a summary of the model's reasoning,
                # which is published with the analysis.
                types.ThinkingConfig(thinking_level=self.thinking_level, include_thoughts=True)
                if self.thinking_level
                else None
            ),
            # No tools are used, so skip the SDK's automatic function calling loop.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            response = self.client.models.generate_content(
                model=self.model_id, contents=build_prompt(text, schema), config=config
            )
        except errors.APIError as exc:
            raise map_status(exc.code, str(exc.message or exc)) from exc
        except Exception as exc:  # network errors from the HTTP client
            raise TransientProviderError(f"gemini request failed: {exc}") from exc
        if not response.text:
            raise ProviderError("gemini returned an empty response")
        result = parse_result(response.text)
        self.last_call = call_details(response, self.thinking_level)
        return result


def call_details(response, thinking_level: str) -> dict:
    candidate = response.candidates[0] if response.candidates else None
    parts = (candidate.content.parts if candidate and candidate.content else None) or []
    thoughts = [p.text.strip() for p in parts if p.thought and p.text]
    usage = response.usage_metadata
    reason = candidate.finish_reason if candidate else None
    return {
        "response_id": response.response_id,
        "model_version": response.model_version,
        "finish_reason": getattr(reason, "value", reason),
        "parameters": {
            "temperature": TEMPERATURE,
            "thinking_level": thinking_level or None,
            "response_format": "json_schema",
        },
        "usage": {
            "prompt_tokens": usage.prompt_token_count if usage else None,
            "output_tokens": usage.candidates_token_count if usage else None,
            "thinking_tokens": usage.thoughts_token_count if usage else None,
            "total_tokens": usage.total_token_count if usage else None,
        },
        "thought_summary": "\n\n".join(thoughts) or None,
    }
