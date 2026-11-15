"""Settings, read once from environment variables.

API keys are read here and nowhere else; they come from GitHub Actions secrets
in CI and are never written to disk or logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _str(name: str, default: str) -> str:
    """An unset or empty variable means the default (Actions passes unset vars as "")."""
    return os.environ.get(name, "").strip() or default


def _int(name: str, default: int) -> int:
    return int(_str(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(_str(name, str(default)))


@dataclass(frozen=True)
class Settings:
    root: Path = Path(".")
    primary_provider: str = "gemini"
    fallback_provider: str = "groq"
    gemini_model: str = "gemini-3.8-flash"
    groq_model: str = "llama-3.3-70b-versatile"
    # "low" keeps calls fast; set GEMINI_THINKING_LEVEL to "none" to omit it
    # (for models without thinking levels).
    gemini_thinking_level: str = "low"
    # Sent to Gemini as the server-side deadline too; long bills on a busy
    # model can need several minutes.
    request_timeout_seconds: float = 300.0
    # Stop the run after this many bills in a row fail on every provider
    # (an outage), leaving the rest pending instead of burning the job's time.
    max_consecutive_failures: int = 2
    gemini_api_key: str = field(default="", repr=False)
    groq_api_key: str = field(default="", repr=False)
    request_delay_seconds: float = 12.0
    max_bills_per_run: int = 15
    max_retries: int = 3
    # Bills introduced before this date are ignored, so the first run does not
    # queue decades of history.
    since_date: str = "2026-01-01"
    # How many pages of the Sansad listing (newest first) to read per run.
    max_pages: int = 5
    page_size: int = 50
    # Input token budgets per provider; larger texts are truncated and the
    # analysis is flagged partial.
    gemini_max_input_tokens: int = 120_000
    groq_max_input_tokens: int = 8_000
    # Texts above this are not sent at all (status skipped_oversized).
    oversize_tokens: int = 1_000_000
    site_url: str = "https://vimarsh.pardarsh.9th.fun/"

    @property
    def manifest_path(self) -> Path:
        return self.root / "data" / "manifest.json"

    @property
    def content_dir(self) -> Path:
        return self.root / "content" / "bills"

    @classmethod
    def from_env(cls, root: Path | str = ".") -> Settings:
        return cls(
            root=Path(root),
            primary_provider=_str("PRIMARY_PROVIDER", "gemini").lower(),
            fallback_provider=_str("FALLBACK_PROVIDER", "groq").lower(),
            gemini_model=_str("GEMINI_MODEL", "gemini-3.8-flash"),
            groq_model=_str("GROQ_MODEL", "llama-3.3-70b-versatile"),
            gemini_thinking_level=_str("GEMINI_THINKING_LEVEL", "low").lower(),
            request_timeout_seconds=_float("REQUEST_TIMEOUT_SECONDS", 300.0),
            max_consecutive_failures=_int("MAX_CONSECUTIVE_FAILURES", 2),
            gemini_api_key=_str("GEMINI_API_KEY", ""),
            groq_api_key=_str("GROQ_API_KEY", ""),
            request_delay_seconds=_float("REQUEST_DELAY_SECONDS", 12.0),
            max_bills_per_run=_int("MAX_BILLS_PER_RUN", 15),
            max_retries=_int("MAX_RETRIES", 3),
            since_date=_str("SINCE_DATE", "2026-01-01"),
            max_pages=_int("MAX_PAGES", 5),
            page_size=_int("PAGE_SIZE", 50),
            gemini_max_input_tokens=_int("GEMINI_MAX_INPUT_TOKENS", 120_000),
            groq_max_input_tokens=_int("GROQ_MAX_INPUT_TOKENS", 8_000),
            oversize_tokens=_int("OVERSIZE_TOKENS", 1_000_000),
            site_url=_str("SITE_URL", "https://vimarsh.pardarsh.9th.fun/"),
        )
