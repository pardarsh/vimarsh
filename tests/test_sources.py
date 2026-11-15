import responses

from vimarsh import sources


def test_parse_record_uses_latest_document(listing):
    bill = sources.parse_record(listing["records"][0])
    assert bill.bill_id == "ls-2026-153"
    assert bill.title == "THE TRIBUNALS REFORMS BILL, 2026"
    assert bill.introduced_date == "2026-08-10"
    assert bill.document_stage == "passed_both_houses"
    assert bill.ministry == "Law And Justice"
    assert bill.listing_url == sources.LISTING_PAGES["Lok Sabha"]


def test_parse_record_rejects_incomplete():
    assert sources.parse_record({"billName": "x"}) is None


def test_bill_id_for_roman_numerals():
    assert sources.make_bill_id("Rajya Sabha", 2026, "LXXII ") == "rs-2026-lxxii"
    assert sources.make_bill_id("Lok Sabha", 2026, "  ") == "ls-2026-unknown"


def test_latest_document_order():
    assert sources.latest_document({}) == (None, None)
    assert sources.latest_document({"billIntroducedFile": "a"}) == ("a", "introduced")
    record = {
        "billIntroducedFile": "a",
        "billPassedInLSFile": "ls",
        "billPassedInLSDate": "2026-08-12",
        "billPassedInRSFile": "rs",
        "billPassedInRSDate": "2026-08-10",
    }
    assert sources.latest_document(record) == ("ls", "passed_ls")
    record["billPassedInBothHousesFile"] = "both"
    assert sources.latest_document(record) == ("both", "passed_both_houses")


def test_merge_keeps_latest_row(listing):
    bills = [sources.parse_record(r) for r in listing["records"]]
    merged = sources.merge_bills(bills)
    ids = [b.bill_id for b in merged]
    assert len(ids) == len(set(ids))
    assert next(b for b in merged if b.bill_id == "ls-2026-154").status == "Assented"
    assert ids == sorted(
        ids, key=lambda i: next(b.introduced_date for b in merged if b.bill_id == i), reverse=True
    )


@responses.activate
def test_fetch_bills_skips_failing_listing_and_old_bills(listing):
    responses.get(sources.LISTINGS["rs"], json=listing)
    responses.get(sources.LISTINGS["ls"], status=404)
    bills = sources.fetch_bills("2026-08-01", max_pages=3, page_size=50)
    assert {b.bill_id for b in bills} == {"ls-2026-153", "ls-2026-154", "ls-2026-155"}
    # Paging stops once a page reaches bills older than since_date.
    assert len([c for c in responses.calls if "api_rs" in c.request.url]) == 1
    assert responses.calls[0].request.headers["User-Agent"] == sources.USER_AGENT


@responses.activate
def test_fetch_listing_pages_until_empty(listing):
    responses.get(sources.LISTINGS["rs"], json=listing)
    responses.get(sources.LISTINGS["rs"], json={"records": []})
    bills = sources.fetch_listing(
        sources.LISTINGS["rs"], "2000-01-01", 5, 50, sources.new_session()
    )
    assert len(bills) == len(listing["records"])
    assert len(responses.calls) == 2


@responses.activate
def test_download():
    responses.get("https://sansad.in/x.pdf", body=b"%PDF-", content_type="application/pdf")
    assert sources.download("https://sansad.in/x.pdf") == (b"%PDF-", "application/pdf")
