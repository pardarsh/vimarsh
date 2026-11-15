"""content/bills/<year>/<bill-id>.md: one self-contained, attributed record per bill.

The YAML frontmatter holds the bill's metadata, where its text came from
(with hashes), the analysis, and who or what produced it. The Markdown body
is the same analysis for people reading the repository directly.
"""

from __future__ import annotations

from pathlib import Path

import yaml

DISCLAIMER = (
    "This analysis was generated automatically by a language model from the official "
    "bill text. It may contain errors. Read the official text before relying on it."
)


def render_markdown(record: dict) -> str:
    front = yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=100)
    a = record["analysis"]
    p = record["provenance"]
    s = record["source"]
    lines = [f"# {record['title']}", "", f"> {DISCLAIMER}", ""]
    if record.get("partial_analysis"):
        lines += [
            "> **Partial analysis:** the bill was too long, so only an excerpt was analysed.",
            "",
        ]
    lines += [a["summary_short"], "", "## Summary", ""]
    lines += [f"- {item}" for item in a["summary_detailed"]]
    lines += ["", "## Key provisions", ""]
    lines += [f"- {item}" for item in a["key_provisions"]]
    lines += ["", "## Fiscal or legal impact", "", a["fiscal_or_legal_impact"], ""]
    lines += ["## Affected sectors", "", ", ".join(a["affected_sectors"]) or "None stated", ""]
    lines += [
        "## Provenance",
        "",
        f"- Official text: <{s['document_url']}> ({s['document_stage']})",
        f"- Document SHA-256: `{s['document_sha256']}`",
        f"- Analysed by: {p['provider']} / `{p['model_id']}` on {p['analyzed_at']}",
        f"- Prompt version {p['prompt_version']}, schema version {p['schema_version']}",
    ]
    if p.get("response_id"):
        lines.append(
            f"- Response ID: `{p['response_id']}` (served model `{p.get('model_version')}`)"
        )
    if p.get("usage"):
        usage = ", ".join(
            f"{k.replace('_', ' ')} {v}" for k, v in p["usage"].items() if v is not None
        )
        lines.append(f"- Tokens: {usage}")
    if (p.get("run") or {}).get("workflow_run_url"):
        lines.append(f"- Run: <{p['run']['workflow_run_url']}>")
    lines.append("")
    if p.get("thought_summary"):
        lines += ["## Model's summary of its reasoning", "", p["thought_summary"], ""]
    return f"---\n{front}---\n\n" + "\n".join(lines)


def output_path(content_dir: Path, year: int, bill_id: str) -> Path:
    return content_dir / str(year) / f"{bill_id}.md"


def write_record(content_dir: Path, record: dict) -> Path:
    path = output_path(content_dir, record["year"], record["bill_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(record), encoding="utf-8", newline="\n")
    return path


def read_record(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    _, front, _ = text.split("---\n", 2)
    return yaml.safe_load(front)


def read_all(content_dir: Path) -> list[dict]:
    records = [read_record(p) for p in sorted(content_dir.glob("*/*.md"))]
    return sorted(records, key=lambda r: (r["introduced_date"], r["bill_id"]), reverse=True)
