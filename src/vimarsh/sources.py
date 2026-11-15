"""Official, first-party bill listings from Sansad (Parliament of India).

Only sansad.in endpoints are used. The Rajya Sabha listing covers bills
introduced in both houses; the Lok Sabha listing is read too when it responds,
and any failure there is logged and skipped.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass

import requests

log = logging.getLogger(__name__)

USER_AGENT = "vimarsh/0.1 (+https://github.com/pardarsh/vimarsh)"
TIMEOUT = 60

LISTINGS = {
    "rs": "https://sansad.in/api_rs/legislation/getBills",
    "ls": "https://sansad.in/api_ls/legislation/getBills",
}
LISTING_PAGES = {
    "Lok Sabha": "https://sansad.in/ls/legislation/bills",
    "Rajya Sabha": "https://sansad.in/rs/legislation/bills",
}

# Later stages carry the most recent text of a bill.
_STATUS_RANK = {"Assented": 4, "Passed": 3, "Pending": 2}


@dataclass
class Bill:
    bill_id: str
    title: str
    house: str
    number: str
    year: int
    introduced_date: str
    status: str
    bill_type: str
    category: str
    ministry: str
    document_url: str | None
    document_stage: str | None
    listing_url: str

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def make_bill_id(house: str, year: int, number: str) -> str:
    prefix = "ls" if house.lower().startswith("lok") else "rs"
    slug = re.sub(r"[^a-z0-9]+", "-", number.lower()).strip("-") or "unknown"
    return f"{prefix}-{year}-{slug}"


def latest_document(record: dict) -> tuple[str | None, str | None]:
    """Return (url, stage) of the most recent text of a bill."""
    if record.get("billPassedInBothHousesFile"):
        return record["billPassedInBothHousesFile"], "passed_both_houses"
    passed = [
        (record.get("billPassedInLSDate") or "", record.get("billPassedInLSFile"), "passed_ls"),
        (record.get("billPassedInRSDate") or "", record.get("billPassedInRSFile"), "passed_rs"),
    ]
    passed = [p for p in passed if p[1]]
    if passed:
        _, url, stage = max(passed, key=lambda p: p[0])
        return url, stage
    if record.get("billIntroducedFile"):
        return record["billIntroducedFile"], "introduced"
    return None, None


def parse_record(record: dict) -> Bill | None:
    house = _clean(record.get("billIntroducedInHouse"))
    number = _clean(record.get("billNumber"))
    year = record.get("billYear")
    if not (house and number and year):
        return None
    url, stage = latest_document(record)
    return Bill(
        bill_id=make_bill_id(house, int(year), number),
        title=_clean(record.get("billName")),
        house=house,
        number=number,
        year=int(year),
        introduced_date=_clean(record.get("billIntroducedDate"))[:10],
        status=_clean(record.get("status")),
        bill_type=_clean(record.get("billType")),
        category=_clean(record.get("billCategory")),
        ministry=_clean(record.get("ministryName")).title(),
        document_url=url,
        document_stage=stage,
        listing_url=LISTING_PAGES.get(house, LISTING_PAGES["Rajya Sabha"]),
    )


def _rank(bill: Bill) -> tuple[int, int]:
    stages = ["introduced", "passed_ls", "passed_rs", "passed_both_houses"]
    stage = stages.index(bill.document_stage) if bill.document_stage in stages else -1
    return _STATUS_RANK.get(bill.status, 1), stage


def merge_bills(bills: list[Bill]) -> list[Bill]:
    """The listing repeats a bill once per status; keep its latest row."""
    merged: dict[str, Bill] = {}
    for bill in bills:
        current = merged.get(bill.bill_id)
        if current is None or _rank(bill) > _rank(current):
            merged[bill.bill_id] = bill
    return sorted(merged.values(), key=lambda b: (b.introduced_date, b.bill_id), reverse=True)


def fetch_listing(
    url: str,
    since_date: str,
    max_pages: int,
    page_size: int,
    session: requests.Session,
) -> list[Bill]:
    bills: list[Bill] = []
    for page in range(1, max_pages + 1):
        params = {
            "page": page,
            "size": page_size,
            "sortOn": "billIntroducedDate",
            "sortBy": "desc",
        }
        resp = session.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        records = resp.json().get("records") or []
        parsed = [b for b in (parse_record(r) for r in records) if b]
        bills.extend(b for b in parsed if b.introduced_date >= since_date)
        if not records or any(b.introduced_date < since_date for b in parsed):
            break
    return bills


def fetch_bills(
    since_date: str,
    max_pages: int,
    page_size: int,
    session: requests.Session | None = None,
) -> list[Bill]:
    """All bills introduced on or after since_date, newest first."""
    session = session or new_session()
    bills: list[Bill] = []
    for name, url in LISTINGS.items():
        try:
            bills.extend(fetch_listing(url, since_date, max_pages, page_size, session))
        except (requests.RequestException, ValueError) as exc:
            log.warning("Skipping %s listing: %s", name, exc)
    return merge_bills(bills)


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def download(url: str, session: requests.Session | None = None) -> tuple[bytes, str]:
    """Return the document's bytes and content type."""
    session = session or new_session()
    resp = session.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "")
