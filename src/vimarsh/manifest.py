"""data/manifest.json: the pipeline's state, kept in git.

One entry per bill. A bill is analysed again only when its document changes
(new URL whose bytes hash differently), so reruns never repeat work.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Status = Literal["pending", "processed", "failed", "skipped_oversized"]


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class Entry(BaseModel):
    bill_id: str
    status: Status = "pending"
    version_hash: str | None = None
    source_url: str | None = None
    last_updated: str
    attempts: int = 0
    last_error: str | None = None
    output_path: str | None = None
    bill: dict


class Manifest:
    def __init__(self, path: Path, entries: dict[str, Entry] | None = None):
        self.path = path
        self.entries = entries or {}

    @classmethod
    def load(cls, path: Path) -> Manifest:
        if not path.exists():
            return cls(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = {e["bill_id"]: Entry.model_validate(e) for e in raw.get("bills", [])}
        return cls(path, entries)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        bills = [e.model_dump() for e in sorted(self.entries.values(), key=lambda e: e.bill_id)]
        body = json.dumps({"bills": bills}, indent=2, ensure_ascii=False) + "\n"
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(body, encoding="utf-8", newline="\n")
        os.replace(tmp, self.path)

    def observe(self, bill: dict) -> bool:
        """Record a bill seen in a listing. Returns True if it now needs analysis."""
        entry = self.entries.get(bill["bill_id"])
        url = bill.get("document_url")
        if entry is None:
            self.entries[bill["bill_id"]] = Entry(
                bill_id=bill["bill_id"], source_url=url, last_updated=now_iso(), bill=bill
            )
            return True
        entry.bill = bill
        if url != entry.source_url:
            # A new stage of the bill was published (for example the passed text).
            entry.source_url = url
            entry.status = "pending"
            entry.attempts = 0
            entry.last_error = None
            entry.last_updated = now_iso()
        return entry.status == "pending"

    def pending(self) -> list[Entry]:
        items = [e for e in self.entries.values() if e.status == "pending" and e.source_url]
        return sorted(
            items, key=lambda e: (e.bill.get("introduced_date", ""), e.bill_id), reverse=True
        )

    def update(self, bill_id: str, **fields: object) -> None:
        entry = self.entries[bill_id]
        for key, value in fields.items():
            setattr(entry, key, value)
        entry.last_updated = now_iso()
