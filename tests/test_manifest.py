from vimarsh.manifest import Manifest


def bill(bill_id="ls-2026-1", url="https://sansad.in/a.pdf", date="2026-08-01"):
    return {"bill_id": bill_id, "document_url": url, "introduced_date": date}


def test_new_bill_is_pending(tmp_path):
    m = Manifest(tmp_path / "m.json")
    assert m.observe(bill()) is True
    assert [e.bill_id for e in m.pending()] == ["ls-2026-1"]


def test_processed_bill_is_not_requeued(tmp_path):
    m = Manifest(tmp_path / "m.json")
    m.observe(bill())
    m.update("ls-2026-1", status="processed", version_hash="h")
    assert m.observe(bill()) is False
    assert m.pending() == []


def test_new_document_requeues(tmp_path):
    m = Manifest(tmp_path / "m.json")
    m.observe(bill())
    m.update("ls-2026-1", status="processed", attempts=2, last_error="x")
    assert m.observe(bill(url="https://sansad.in/passed.pdf")) is True
    entry = m.entries["ls-2026-1"]
    assert (entry.status, entry.attempts, entry.last_error) == ("pending", 0, None)


def test_bills_without_text_are_not_queued(tmp_path):
    m = Manifest(tmp_path / "m.json")
    m.observe(bill(url=None))
    assert m.pending() == []


def test_pending_is_newest_first(tmp_path):
    m = Manifest(tmp_path / "m.json")
    m.observe(bill("a", date="2026-01-01"))
    m.observe(bill("b", date="2026-05-01"))
    assert [e.bill_id for e in m.pending()] == ["b", "a"]


def test_round_trip(tmp_path):
    path = tmp_path / "data" / "manifest.json"
    m = Manifest.load(path)
    m.observe(bill())
    m.save()
    loaded = Manifest.load(path)
    assert loaded.entries["ls-2026-1"].source_url == "https://sansad.in/a.pdf"
    assert path.read_text(encoding="utf-8").endswith("}\n")
