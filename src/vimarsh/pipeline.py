"""One daily run: discover bills, analyse what is new or changed, record state.

Nothing here raises on a bad bill or a provider outage. A bill that could not
be analysed stays pending (with the error recorded) and is tried again on the
next run.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version

import requests

from . import __version__, sources
from .config import Settings
from .extract import ExtractionError, extract_text
from .manifest import Manifest, now_iso
from .providers import AllProvidersFailed, Router, build_providers
from .providers.base import PROMPT_SHA256, PROMPT_VERSION, SCHEMA_VERSION, estimate_tokens
from .publish import write_record

log = logging.getLogger(__name__)


@dataclass
class RunReport:
    discovered: int = 0
    processed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    still_pending: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    oversized: list[str] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"discovered {self.discovered}, processed {len(self.processed)}, "
            f"unchanged {len(self.unchanged)}, pending {len(self.still_pending)}, "
            f"failed {len(self.failed)}, oversized {len(self.oversized)}"
            + (f", not found {', '.join(self.not_found)}" if self.not_found else "")
        )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package_versions() -> dict:
    versions: dict[str, str | None] = {}
    for name in ("vimarsh", "google-genai", "groq", "pypdf"):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:  # pragma: no cover
            versions[name] = None
    return versions


def run_context() -> dict:
    """Where the analysis ran: a public GitHub Actions run, or a local machine."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return {"environment": "local"}
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    return {
        "environment": "github-actions",
        "workflow_run_url": f"{server}/{repo}/actions/runs/{run_id}",
        "commit": os.environ.get("GITHUB_SHA"),
    }


def build_record(
    bill: dict, document: bytes, text: str, routed, retrieved_at: str, settings: Settings
) -> dict:
    call = routed.call
    return {
        "bill_id": bill["bill_id"],
        "title": bill["title"],
        "house": bill["house"],
        "bill_number": bill["number"],
        "year": bill["year"],
        "introduced_date": bill["introduced_date"],
        "status": bill["status"],
        "bill_type": bill["bill_type"],
        "category": bill["category"],
        "ministry": bill["ministry"],
        "partial_analysis": routed.partial,
        "source": {
            "publisher": "Parliament of India (sansad.in)",
            "listing_url": bill["listing_url"],
            "document_url": bill["document_url"],
            "document_stage": bill["document_stage"],
            "document_sha256": sha256(document),
            "text_sha256": sha256(text.encode("utf-8")),
            "text_chars": len(text),
            "retrieved_at": retrieved_at,
        },
        "analysis": routed.result.model_dump(),
        "provenance": {
            "provider": routed.provider,
            "model_id": routed.model_id,
            "model_version": call.get("model_version"),
            "response_id": call.get("response_id"),
            "finish_reason": call.get("finish_reason"),
            "parameters": call.get("parameters"),
            "usage": call.get("usage"),
            "thought_summary": call.get("thought_summary"),
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "prompt_sha256": PROMPT_SHA256,
            "input_tokens_estimate": routed.input_tokens_estimate,
            "latency_seconds": routed.latency_seconds,
            "attempts": routed.attempts,
            "fallback_errors": routed.fallback_errors,
            "analyzed_at": now_iso(),
            "generator": f"vimarsh {__version__}",
            "software": package_versions(),
            "run": run_context(),
        },
    }


def run(
    settings: Settings,
    router: Router | None = None,
    session: requests.Session | None = None,
    bill_ids: list[str] | None = None,
    force: bool = False,
) -> RunReport:
    """Analyse pending bills, or only bill_ids when given.

    force re-analyses the given bills even if their text has not changed.
    """
    report = RunReport()
    session = session or sources.new_session()
    manifest = Manifest.load(settings.manifest_path)

    bills = sources.fetch_bills(
        settings.since_date, settings.max_pages, settings.page_size, session=session
    )
    report.discovered = len(bills)
    for bill in bills:
        manifest.observe(bill.to_dict())
    manifest.save()

    if bill_ids:
        queue = []
        for bill_id in bill_ids:
            entry = manifest.entries.get(bill_id)
            if entry is None or not entry.source_url:
                log.error("Bill %s not found in the listing (or has no text yet)", bill_id)
                report.not_found.append(bill_id)
                continue
            if force:
                manifest.update(bill_id, status="pending", attempts=0, last_error=None)
            if entry.status == "pending":
                queue.append(entry)
            else:
                log.info("%s is already %s; use force to re-analyse", bill_id, entry.status)
                report.unchanged.append(bill_id)
        manifest.save()
    else:
        queue = manifest.pending()[: settings.max_bills_per_run]
    if queue and router is None:
        providers = build_providers(settings)
        if not providers:
            log.error("No LLM provider is configured; %d bills stay pending", len(queue))
            report.still_pending = [e.bill_id for e in manifest.pending()]
            return report
        router = Router(providers, settings.request_delay_seconds, settings.max_retries)

    consecutive_failures = 0
    for entry in queue:
        if consecutive_failures >= settings.max_consecutive_failures:
            log.error(
                "Stopping after %d bills in a row failed on every provider; the rest stay pending",
                consecutive_failures,
            )
            break
        bill = entry.bill
        try:
            document, content_type = sources.download(entry.source_url, session=session)
            retrieved_at = now_iso()
        except requests.RequestException as exc:
            manifest.update(
                entry.bill_id, attempts=entry.attempts + 1, last_error=f"download: {exc}"
            )
            manifest.save()
            continue

        version = sha256(document)
        if not force and version == entry.version_hash and entry.output_path:
            # Same bytes under a new URL: nothing to re-analyse.
            manifest.update(entry.bill_id, status="processed", last_error=None)
            manifest.save()
            report.unchanged.append(entry.bill_id)
            continue

        try:
            text = extract_text(document, content_type)
        except ExtractionError as exc:
            manifest.update(
                entry.bill_id, status="failed", version_hash=version, last_error=str(exc)
            )
            manifest.save()
            report.failed.append(entry.bill_id)
            continue

        if estimate_tokens(text) > settings.oversize_tokens:
            manifest.update(entry.bill_id, status="skipped_oversized", version_hash=version)
            manifest.save()
            report.oversized.append(entry.bill_id)
            continue

        try:
            routed = router.analyze(text)
        except AllProvidersFailed as exc:
            manifest.update(entry.bill_id, attempts=entry.attempts + 1, last_error=str(exc)[:500])
            manifest.save()
            consecutive_failures += 1
            continue
        consecutive_failures = 0

        record = build_record(bill, document, text, routed, retrieved_at, settings)
        path = write_record(settings.content_dir, record)
        manifest.update(
            entry.bill_id,
            status="processed",
            version_hash=version,
            attempts=entry.attempts + 1,
            last_error=None,
            output_path=path.relative_to(settings.root).as_posix(),
        )
        manifest.save()
        report.processed.append(entry.bill_id)
        log.info("Analysed %s with %s/%s", entry.bill_id, routed.provider, routed.model_id)

    report.still_pending = [e.bill_id for e in manifest.pending()]
    return report
