import dataclasses
import re

import pytest
import responses

from vimarsh import pipeline, sources
from vimarsh.manifest import Manifest
from vimarsh.providers import Router
from vimarsh.providers.base import ProviderError
from vimarsh.publish import read_record

from .conftest import BILL_TEXT, FakeProvider, make_pdf

PDF = make_pdf(BILL_TEXT)
DOCS = re.compile(r"https://sansad\.in/getFile/.*")


@pytest.fixture
def mocked(listing):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.get(sources.LISTINGS["rs"], json=listing)
        rsps.get(sources.LISTINGS["ls"], status=404)
        rsps.get(DOCS, body=PDF, content_type="application/pdf")
        yield rsps


def router(provider):
    return Router([provider], 0, sleep=lambda _s: None)


def test_run_analyses_and_records_provenance(mocked, settings):
    provider = FakeProvider("gemini")
    report = pipeline.run(settings, router=router(provider))
    assert report.discovered == 4
    assert sorted(report.processed) == [
        "ls-2026-153",
        "ls-2026-154",
        "ls-2026-155",
        "rs-2026-xxxiii",
    ]
    assert len(provider.calls) == 4

    record = read_record(settings.content_dir / "2026" / "ls-2026-153.md")
    assert record["source"]["document_url"].startswith("https://sansad.in/getFile/")
    assert record["source"]["document_sha256"] == pipeline.sha256(PDF)
    assert record["provenance"]["provider"] == "gemini"
    assert record["provenance"]["model_id"] == "gemini-model-1"
    assert record["provenance"]["prompt_version"]
    assert record["partial_analysis"] is False

    entry = Manifest.load(settings.manifest_path).entries["ls-2026-153"]
    assert entry.status == "processed"
    assert entry.version_hash == pipeline.sha256(PDF)
    assert entry.output_path == "content/bills/2026/ls-2026-153.md"


def test_rerun_is_idempotent(mocked, settings):
    pipeline.run(settings, router=router(FakeProvider()))
    provider = FakeProvider()
    report = pipeline.run(settings, router=router(provider))
    assert provider.calls == []
    assert report.processed == [] and report.still_pending == []


def test_batch_cap_leaves_rest_pending(mocked, settings):
    settings = dataclasses.replace(settings, max_bills_per_run=2)
    report = pipeline.run(settings, router=router(FakeProvider()))
    assert len(report.processed) == 2
    assert len(report.still_pending) == 2


def test_provider_failure_stays_pending(mocked, settings):
    provider = FakeProvider(outcomes=[ProviderError("quota")] * 4)
    report = pipeline.run(settings, router=router(provider))
    assert report.processed == []
    entry = Manifest.load(settings.manifest_path).entries["ls-2026-155"]
    assert (entry.status, entry.attempts) == ("pending", 1)
    assert "quota" in entry.last_error


def test_download_failure_stays_pending(listing, settings):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.get(sources.LISTINGS["rs"], json=listing)
        rsps.get(sources.LISTINGS["ls"], status=404)
        rsps.get(DOCS, status=500)
        report = pipeline.run(settings, router=router(FakeProvider()))
    assert len(report.still_pending) == 4
    assert "download" in Manifest.load(settings.manifest_path).entries["ls-2026-153"].last_error


def test_unreadable_document_fails(listing, settings):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.get(sources.LISTINGS["rs"], json=listing)
        rsps.get(sources.LISTINGS["ls"], status=404)
        rsps.get(DOCS, body=make_pdf(""), content_type="application/pdf")
        report = pipeline.run(settings, router=router(FakeProvider()))
    assert len(report.failed) == 4
    assert Manifest.load(settings.manifest_path).entries["ls-2026-153"].status == "failed"


def test_oversized_is_skipped(mocked, settings):
    settings = dataclasses.replace(settings, oversize_tokens=10)
    report = pipeline.run(settings, router=router(FakeProvider()))
    assert len(report.oversized) == 4


def test_new_url_with_same_bytes_is_not_reanalysed(mocked, settings, listing):
    pipeline.run(settings, router=router(FakeProvider()))
    m = Manifest.load(settings.manifest_path)
    m.entries["ls-2026-153"].source_url = "https://sansad.in/getFile/old.pdf"
    m.save()
    provider = FakeProvider()
    report = pipeline.run(settings, router=router(provider))
    assert report.unchanged == ["ls-2026-153"]
    assert provider.calls == []


def test_no_providers_leaves_bills_pending(mocked, settings):
    report = pipeline.run(settings)  # no API keys in settings
    assert len(report.still_pending) == 4
    assert report.processed == []
    assert "pending" in report.summary()


def test_single_bill(mocked, settings):
    provider = FakeProvider()
    report = pipeline.run(settings, router=router(provider), bill_ids=["ls-2026-155"])
    assert report.processed == ["ls-2026-155"]
    assert len(provider.calls) == 1
    others = Manifest.load(settings.manifest_path).entries["ls-2026-153"]
    assert others.status == "pending"


def test_single_bill_already_done_and_force(mocked, settings):
    pipeline.run(settings, router=router(FakeProvider()), bill_ids=["ls-2026-155"])
    provider = FakeProvider()
    report = pipeline.run(settings, router=router(provider), bill_ids=["ls-2026-155"])
    assert report.unchanged == ["ls-2026-155"] and provider.calls == []
    # Same bytes, but force re-analyses anyway.
    report = pipeline.run(settings, router=router(provider), bill_ids=["ls-2026-155"], force=True)
    assert report.processed == ["ls-2026-155"] and len(provider.calls) == 1


def test_single_bill_not_found(mocked, settings):
    report = pipeline.run(settings, router=router(FakeProvider()), bill_ids=["rs-1990-x"])
    assert report.not_found == ["rs-1990-x"]
    assert "not found rs-1990-x" in report.summary()


def test_outage_stops_run_early(mocked, settings):
    provider = FakeProvider(outcomes=[ProviderError("down")] * 10)
    report = pipeline.run(settings, router=router(provider))
    # Two bills fail in a row, then the run stops; the other two are never tried.
    assert len(provider.calls) == 2
    assert len(report.still_pending) == 4
