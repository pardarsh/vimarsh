"""The provider-agnostic interface, the output schema and the prompt.

Every provider implements LLMProvider.analyze_bill(text, schema) and returns a
validated AnalysisResult. Bump PROMPT_VERSION or SCHEMA_VERSION whenever the
prompt or schema changes; both are recorded with every analysis.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field, ValidationError

PROMPT_VERSION = "2026-11-15.1"
SCHEMA_VERSION = "1"


class AnalysisResult(BaseModel):
    summary_short: str = Field(description="Two to three plain sentences for feeds and cards.")
    summary_detailed: list[str] = Field(description="Bulleted breakdown of what the bill does.")
    key_provisions: list[str] = Field(description="Each concrete change the bill makes.")
    affected_sectors: list[str] = Field(description="Short lowercase sector tags.")
    fiscal_or_legal_impact: str = Field(
        description="Objective assessment of fiscal and legal effects, as stated in the text."
    )


ANALYSIS_SCHEMA: dict = AnalysisResult.model_json_schema()

SYSTEM_PROMPT = """\
You analyse bills of the Parliament of India for the public. Work only from the
bill text you are given. Be neutral and factual: describe what the bill does,
not whether it is good or bad, and do not speculate about motives or politics.
If the text does not state something, say so instead of guessing. Use plain
English a non-lawyer can follow, and cite clause numbers where useful.
The Financial Memorandum and Statement of Objects and Reasons, when present,
are the bill's own account of its purpose and cost; attribute them as such.
Respond with a single JSON object that matches the given JSON Schema."""

# Fingerprint of everything fixed that the model is given besides the bill text.
PROMPT_SHA256 = hashlib.sha256(
    (SYSTEM_PROMPT + json.dumps(ANALYSIS_SCHEMA, sort_keys=True)).encode("utf-8")
).hexdigest()


TRUNCATION_MARKER = "\n\n[... middle of the bill omitted for length ...]\n\n"


def build_prompt(text: str, schema: dict) -> str:
    note = (
        "\nNOTE: The text below is an excerpt (the beginning and end of a very long "
        "bill). Say in summary_detailed that the analysis covers an excerpt.\n"
        if TRUNCATION_MARKER in text
        else ""
    )
    return f"JSON Schema:\n{json.dumps(schema)}\n{note}\nBill text:\n{text}"


class ProviderError(Exception):
    """A provider call failed in a way that will not fix itself by retrying."""


class TransientProviderError(ProviderError):
    """Rate limited (429) or overloaded (503): worth retrying with backoff."""


class InputTooLargeError(ProviderError):
    """The request exceeded the provider's token limits (413)."""


def estimate_tokens(text: str) -> int:
    """Rough local estimate (about four characters per token)."""
    return len(text) // 4 + 1


def truncate(text: str, max_tokens: int) -> tuple[str, bool]:
    """Fit text into max_tokens, keeping the start and the end.

    The start holds the title, arrangement of clauses and operative sections;
    the end holds the Statement of Objects and Reasons and the Financial
    Memorandum. Returns (text, was_truncated).
    """
    if estimate_tokens(text) <= max_tokens:
        return text, False
    budget = max(max_tokens * 4 - 200, 400)
    head = budget * 3 // 4
    tail = budget - head
    return text[:head] + TRUNCATION_MARKER + text[-tail:], True


def parse_result(raw: str) -> AnalysisResult:
    try:
        return AnalysisResult.model_validate_json(raw)
    except ValidationError as exc:
        raise ProviderError(f"response did not match the schema: {exc}") from exc


class LLMProvider(ABC):
    """One model behind one API."""

    name: str
    model_id: str
    max_input_tokens: int
    # Details of the most recent successful call, recorded as provenance:
    # response_id, model_version, finish_reason, parameters, usage and
    # thought_summary (the provider's summary of its reasoning, if any).
    last_call: dict

    @abstractmethod
    def analyze_bill(self, text: str, schema: dict) -> AnalysisResult:
        """Analyse bill text and return a result matching schema.

        Raises TransientProviderError, InputTooLargeError or ProviderError.
        """
