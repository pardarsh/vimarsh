import json
import xml.etree.ElementTree as ET

import pytest

from vimarsh import build_site, cli, pipeline
from vimarsh.providers.router import RoutedResult
from vimarsh.publish import read_all, read_record, render_markdown, write_record

from .conftest import sample_result

BILL = {
    "bill_id": "ls-2026-153",
    "title": "THE <TRIBUNALS> REFORMS BILL, 2026",
    "house": "Lok Sabha",
    "number": "153",
    "year": 2026,
    "introduced_date": "2026-08-10",
    "status": "Passed",
    "bill_type": "Government",
    "category": "Financial Bill",
    "ministry": "Law And Justice",
    "document_url": "https://sansad.in/getFile/x.pdf?source=legislation",
    "document_stage": "passed_both_houses",
    "listing_url": "https://sansad.in/ls/legislation/bills",
}


def make_record(settings, partial=False):
    call = {
        "response_id": "resp-1",
        "model_version": "gemini-3.8-flash-001",
        "finish_reason": "STOP",
        "parameters": {"temperature": 0.2, "thinking_level": "low"},
        "usage": {"prompt_tokens": 900, "output_tokens": 300, "total_tokens": 1200},
        "thought_summary": "Checked <clause 2> first.",
    }
    routed = RoutedResult(
        sample_result(), "gemini", "gemini-3.8-flash", partial, 1234, call, 4.2, 2, ["groq: 503"]
    )
    return pipeline.build_record(
        BILL, b"%PDF", "text", routed, "2026-11-15T08:00:00+00:00", settings
    )


@pytest.fixture
def content(settings):
    write_record(settings.content_dir, make_record(settings, partial=True))
    return settings.content_dir


def test_markdown_round_trip(settings):
    record = make_record(settings)
    path = write_record(settings.content_dir, record)
    assert path.name == "ls-2026-153.md" and path.parent.name == "2026"
    assert read_record(path) == record
    body = render_markdown(record)
    assert "## Provenance" in body and "gemini-3.8-flash" in body
    assert "Response ID: `resp-1`" in body
    assert "## Model's summary of its reasoning" in body
    assert read_all(settings.content_dir)[0]["bill_id"] == "ls-2026-153"


def test_build_site(content, tmp_path):
    out = tmp_path / "public"
    assert build_site.build(content, out, "https://example.org/vimarsh") == 1
    index = (out / "index.html").read_text(encoding="utf-8")
    page = (out / "bills" / "ls-2026-153.html").read_text(encoding="utf-8")
    assert "THE &lt;TRIBUNALS&gt; REFORMS BILL" in index
    assert "<TRIBUNALS>" not in page
    assert "law &lt;&amp;&gt;" in page
    assert "gemini-3.8-flash" in page
    assert "Partial analysis" in page
    assert "In Parliament: Passed" in page and "In Parliament: Passed" in index
    assert 'href="../about.html#status"' in page
    assert "assent is not yet recorded" in page
    assert "resp-1" in page and "gemini-3.8-flash-001" in page
    assert "Checked &lt;clause 2&gt; first." in page
    assert "fell back after: groq: 503" in page
    assert "thinking_level = <code>low</code>" in page
    about = (out / "about.html").read_text(encoding="utf-8")
    assert "You analyse bills of the Parliament of India" in about
    assert 'id="status"' in about and "became an Act" in about
    assert 'href="../style.css"' in page
    assert (out / "style.css").exists() and (out / "favicon.png").exists()
    assert (out / "about.html").exists() and (out / ".nojekyll").exists()

    data = json.loads((out / "bills.json").read_text(encoding="utf-8"))
    assert data["bills"][0]["provenance"]["provider"] == "gemini"


def test_feed(content, tmp_path):
    out = tmp_path / "public"
    build_site.build(content, out, "https://example.org/vimarsh/")
    channel = ET.fromstring((out / "feed.xml").read_bytes()).find("channel")
    item = channel.find("item")
    assert item.findtext("link") == "https://example.org/vimarsh/bills/ls-2026-153.html"
    assert item.findtext("description") == "The bill amends the Example Act."
    assert [c.text for c in item.findall("category")] == ["governance", "law <&>"]


def test_build_with_no_bills(settings, tmp_path):
    out = tmp_path / "public"
    out.mkdir()
    (out / "stale.html").write_text("old")
    assert build_site.build(settings.content_dir, out, "https://example.org/") == 0
    assert not (out / "stale.html").exists()
    assert "No bills have been analysed yet" in (out / "index.html").read_text(encoding="utf-8")


def test_cli_build(content, settings, capsys):
    assert cli.main(["--root", str(settings.root), "build", "--out", "site"]) == 0
    assert "1 bills" in capsys.readouterr().out
    assert (settings.root / "site" / "index.html").exists()


def test_run_context(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert pipeline.run_context() == {"environment": "local"}
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "pardarsh/vimarsh")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setenv("GITHUB_SHA", "abc1234def")
    ctx = pipeline.run_context()
    assert ctx["workflow_run_url"] == "https://github.com/pardarsh/vimarsh/actions/runs/42"
    assert ctx["commit"] == "abc1234def"


def test_github_run_shown_on_page(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "pardarsh/vimarsh")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setenv("GITHUB_SHA", "abc1234def")
    write_record(settings.content_dir, make_record(settings))
    build_site.build(settings.content_dir, tmp_path / "out", "https://example.org/")
    page = (tmp_path / "out" / "bills" / "ls-2026-153.html").read_text(encoding="utf-8")
    assert "actions/runs/42" in page and "abc1234" in page


def test_cli_run(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run(settings, bill_ids=None, force=False):
        calls.append((bill_ids, force))
        return pipeline.RunReport(discovered=2, processed=["ls-2026-1"])

    monkeypatch.setattr(pipeline, "run", fake_run)
    assert cli.main(["--root", str(tmp_path), "run"]) == 0
    assert "discovered 2" in capsys.readouterr().out
    assert cli.main(["--root", str(tmp_path), "run", "--bill", "ls-2026-1", "--force"]) == 0
    assert calls[-1] == (["ls-2026-1"], True)
    assert cli.main(["--root", str(tmp_path), "run", "--bill", "ls-2026-9"]) == 1
