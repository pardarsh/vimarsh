"""Static site, RSS feed and JSON index for GitHub Pages, built from content/."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from feedgen.feed import FeedGenerator
from jinja2 import Environment, PackageLoader, select_autoescape

from . import __version__
from .providers.base import (
    ANALYSIS_SCHEMA,
    PROMPT_SHA256,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    SYSTEM_PROMPT,
)
from .publish import DISCLAIMER, read_all

STATIC = Path(__file__).parent / "static"

# Statuses as sansad.in reports them, explained for readers.
STATUS_HELP = {
    "Pending": "Introduced and still before Parliament: not yet passed, withdrawn or lapsed.",
    "Passed": "Passed by Parliament; the President's assent is not yet recorded.",
    "Assented": "Received the President's assent and became an Act.",
    "Negatived": "Rejected by a vote in the house.",
    "Withdrawn": "Withdrawn by the member or minister who introduced it.",
    "Lapsed": "Lapsed, for example when the Lok Sabha was dissolved before it passed.",
    "Removed": "Removed from the register of pending bills.",
    "Not stated": "sansad.in lists no status for this bill.",
}
DEFAULT_STATUS_HELP = "Status of the bill in Parliament, as reported by sansad.in."


def _env() -> Environment:
    env = Environment(
        loader=PackageLoader("vimarsh", "templates"),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.globals["status_help"] = STATUS_HELP
    env.globals["default_status_help"] = DEFAULT_STATUS_HELP
    return env


def build_feed(records: list[dict], site_url: str, limit: int = 50) -> bytes:
    fg = FeedGenerator()
    fg.title("Vimarsh: analysis of Indian parliamentary bills")
    fg.link(href=site_url, rel="alternate")
    fg.link(href=site_url + "feed.xml", rel="self")
    fg.description(
        "Neutral, attributed AI analysis of bills introduced in the Parliament of India. "
        + DISCLAIMER
    )
    fg.language("en")
    fg.generator(f"vimarsh {__version__}")
    latest = sorted(records, key=lambda r: r["provenance"]["analyzed_at"], reverse=True)[:limit]
    # feedgen prepends entries, so add oldest first to keep the newest on top.
    for r in reversed(latest):
        url = f"{site_url}bills/{r['bill_id']}.html"
        entry = fg.add_entry()
        entry.id(url)
        entry.title(r["title"])
        entry.link(href=url)
        entry.description(r["analysis"]["summary_short"])
        entry.pubDate(datetime.fromisoformat(r["provenance"]["analyzed_at"]))
        for tag in r["analysis"]["affected_sectors"]:
            entry.category(term=tag)
    return fg.rss_str(pretty=True)


def build(content_dir: Path, out_dir: Path, site_url: str) -> int:
    """Write the site to out_dir. Returns the number of bills published."""
    if not site_url.endswith("/"):
        site_url += "/"
    records = read_all(content_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "bills").mkdir(parents=True)
    env = _env()
    common = {"disclaimer": DISCLAIMER, "version": __version__, "site_url": site_url}

    def write(name: str, template: str, **ctx: object) -> None:
        html = env.get_template(template).render(**common, **ctx)
        (out_dir / name).write_text(html, encoding="utf-8", newline="\n")

    write("index.html", "index.html", records=records, root="")
    write(
        "about.html",
        "about.html",
        root="",
        system_prompt=SYSTEM_PROMPT,
        schema=json.dumps(ANALYSIS_SCHEMA, indent=2),
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        prompt_sha256=PROMPT_SHA256,
    )
    for r in records:
        write(f"bills/{r['bill_id']}.html", "bill.html", bill=r, root="../")

    (out_dir / "feed.xml").write_bytes(build_feed(records, site_url))
    (out_dir / "bills.json").write_text(
        json.dumps(
            {"generator": f"vimarsh {__version__}", "bills": records},
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    for asset in STATIC.iterdir():
        shutil.copy(asset, out_dir / asset.name)
    (out_dir / ".nojekyll").write_text("")
    return len(records)
