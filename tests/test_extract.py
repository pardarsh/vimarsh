import pytest

from vimarsh.extract import ExtractionError, clean_text, extract_text

from .conftest import BILL_TEXT, make_pdf


def test_pdf_text():
    text = extract_text(make_pdf(BILL_TEXT), "application/pdf")
    assert "THE EXAMPLE (AMENDMENT) BILL" in text


def test_pdf_detected_by_magic_bytes():
    assert "Short title" in extract_text(make_pdf(BILL_TEXT), "")


def test_html_text_drops_scripts():
    html = f"<html><script>evil()</script><body><p>{BILL_TEXT}</p></body></html>".encode()
    text = extract_text(html, "text/html")
    assert "Amendment of section 3" in text
    assert "evil" not in text


def test_scanned_pdf_is_an_error():
    with pytest.raises(ExtractionError, match="no extractable text"):
        extract_text(make_pdf(""), "application/pdf")


def test_broken_pdf_is_an_error():
    with pytest.raises(ExtractionError, match="could not read"):
        extract_text(b"%PDF-1.4 garbage", "application/pdf")


def test_clean_text():
    assert clean_text("a �  b\n\n\n\n c  ") == "a b\n\nc"
