"""Turn PDF or HTML bill documents into plain text, locally.

Text (not the original PDF) is what goes to the model, so every provider,
including text-only ones, sees the same input.
"""

from __future__ import annotations

import io
import re

from bs4 import BeautifulSoup
from pypdf import PdfReader


class ExtractionError(Exception):
    """The document has no extractable text (for example a scanned image)."""


def clean_text(text: str) -> str:
    # Drop replacement and private-use glyphs that PDF fonts leave behind.
    text = re.sub(r"[�\x00-]", "", text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def pdf_to_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def html_to_text(data: bytes) -> str:
    soup = BeautifulSoup(data, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    return soup.get_text("\n")


def extract_text(data: bytes, content_type: str = "") -> str:
    try:
        if data.lstrip()[:5] == b"%PDF-" or "pdf" in content_type.lower():
            raw = pdf_to_text(data)
        else:
            raw = html_to_text(data)
    except Exception as exc:  # pypdf raises many exception types on bad files
        raise ExtractionError(f"could not read document: {exc}") from exc
    text = clean_text(raw)
    if len(text) < 200:
        raise ExtractionError("document has no extractable text (possibly scanned)")
    return text
