from __future__ import annotations

import json
from pathlib import Path

import pytest

from vimarsh.config import Settings
from vimarsh.providers.base import AnalysisResult, LLMProvider, ProviderError

FIXTURES = Path(__file__).parent / "fixtures"

BILL_TEXT = (
    "THE EXAMPLE (AMENDMENT) BILL, 2026. A BILL further to amend the Example Act. "
    "1. Short title and commencement. 2. Amendment of section 3. "
) * 10


def make_pdf(text: str) -> bytes:
    """A minimal one-page PDF whose text pypdf can extract."""
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 10 Tf 20 800 Td ({safe}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def sample_result() -> AnalysisResult:
    return AnalysisResult(
        summary_short="The bill amends the Example Act.",
        summary_detailed=["Amends section 3.", "Adds a short title."],
        key_provisions=["Section 3 is substituted."],
        affected_sectors=["governance", "law <&>"],
        fiscal_or_legal_impact="No expenditure is stated in the bill.",
    )


class FakeProvider(LLMProvider):
    def __init__(self, name="fake", outcomes=None, max_input_tokens=100_000):
        self.name = name
        self.model_id = f"{name}-model-1"
        self.max_input_tokens = max_input_tokens
        self.outcomes = list(outcomes or [])
        self.calls: list[str] = []

    def analyze_bill(self, text, schema):
        self.calls.append(text)
        self.last_call = {}
        outcome = self.outcomes.pop(0) if self.outcomes else sample_result()
        if isinstance(outcome, ProviderError):
            raise outcome
        self.last_call = {"response_id": f"{self.name}-response"}
        return outcome


@pytest.fixture
def listing() -> dict:
    return json.loads((FIXTURES / "rs_listing.json").read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        root=tmp_path,
        request_delay_seconds=0,
        since_date="2026-01-01",
        max_pages=2,
        page_size=50,
        site_url="https://example.org/vimarsh/",
    )
