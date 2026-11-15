"""Command line: `vimarsh run` (fetch and analyse) and `vimarsh build` (site)."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from . import __version__, build_site, pipeline
from .config import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vimarsh", description=__doc__)
    parser.add_argument("--version", action="version", version=f"vimarsh {__version__}")
    parser.add_argument("--root", default=".", help="repository root (default: .)")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="discover bills and analyse new or changed ones")
    run.add_argument(
        "--bill",
        action="append",
        dest="bills",
        metavar="BILL_ID",
        help="analyse only this bill, e.g. ls-2026-153 (repeatable)",
    )
    run.add_argument(
        "--force", action="store_true", help="re-analyse --bill bills even if unchanged"
    )
    build = sub.add_parser("build", help="build the static site and feed")
    build.add_argument("--out", default="public", help="output directory (default: public)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env(args.root)

    if args.command == "run":
        report = pipeline.run(settings, bill_ids=args.bills, force=args.force)
        print(report.summary())
        if args.bills:
            # A manual run for named bills fails visibly if any was not analysed.
            done = set(report.processed) | set(report.unchanged)
            return 0 if done >= set(args.bills) else 1
    else:
        count = build_site.build(
            settings.content_dir, Path(args.root) / args.out, settings.site_url
        )
        print(f"built site with {count} bills")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
