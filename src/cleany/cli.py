"""Command line: ``cleany path/to/export.zip -o output/``."""

from __future__ import annotations

import argparse
from datetime import date

from .config import Config
from .export import write_all
from .pipeline import extract


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cleany", description=__doc__)
    p.add_argument("export", help="WhatsApp export (.zip or .txt)")
    p.add_argument("-o", "--outdir", default="output")
    p.add_argument("--cleaner", help="display name of the cleaner (auto-detected otherwise)")
    p.add_argument("--alias", action="append", default=[], metavar="NAME=ALIAS",
                   help="rename a participant in the outputs (repeatable)")
    p.add_argument("--initial-rate", type=float, help="€/h before any rate change found in the chat")
    p.add_argument("--rate", action="append", default=[], metavar="YYYY-MM-DD=EUR",
                   help="extra rate change (repeatable)")
    p.add_argument("--monthfirst", action="store_true", help="dates in the export are mm/dd/yy")
    a = p.parse_args(argv)

    cfg = Config(cleaner=a.cleaner, initial_rate=a.initial_rate, dayfirst=not a.monthfirst,
                 aliases=dict(x.split("=", 1) for x in a.alias),
                 rate_changes=[(date.fromisoformat(k), float(v)) for k, v in (x.split("=", 1) for x in a.rate)])
    ex = extract(a.export, cfg)
    paths = write_all(ex, a.outdir)
    hours = sum(v.hours for v in ex.visits if v.hours and v.hours > 0)
    print(f"Cleaner: {cfg.name(ex.cleaner)} | household: {', '.join(cfg.name(h) for h in ex.household)}")
    print(f"{len(ex.visits)} visits, {hours:g} h, {len(ex.tasks)} task messages, "
          f"{len(ex.shopping)} shopping rows, {len(ex.manual)} manual entries")
    for k, pth in paths.items():
        print(f"  {k:14s} {pth}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
