"""Write an :class:`Extraction` to CSV / Markdown / HTML / ICS files."""

from __future__ import annotations

import csv
from pathlib import Path

from .calendar import render_html, render_ics
from .pipeline import Extraction
from .textutil import WEEKDAY_NAMES_EN, shorten


def _fmt(x, nd=2):
    if x is None:
        return ""
    if isinstance(x, float):
        return f"{round(x, nd):g}"
    return x


def _write(path: Path, header: list[str], rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow([_fmt(x) for x in r])


def category_summary(tasks, labels) -> str:
    counts: dict[str, int] = {}
    for t in tasks:
        for c in t.categories:
            counts[c] = counts.get(c, 0) + 1
    return "; ".join(f"{labels.get(k, k)} ({n})" for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))


def write_visits(ex: Extraction, path: Path) -> None:
    labels = {c.key: c.label for c in ex.config.categories} | {"other": "Other"}
    rows = []
    for v in ex.visits:
        rows.append([
            v.date.isoformat(), WEEKDAY_NAMES_EN[v.date.weekday()],
            v.arrival.strftime("%H:%M") if v.arrival else "",
            v.last_msg.strftime("%H:%M") if v.last_msg and v.last_msg.date() == v.date else "",
            v.hours, v.hours_method, v.rate, v.labor_eur, v.shopping_eur or None, ", ".join(sorted(v.stores)),
            v.paid_eur or None, v.balance_after, "yes" if v.planned else "no", "; ".join(v.evidence),
            sum(1 for t in v.tasks if t.role == "household"), sum(1 for t in v.tasks if t.role == "cleaner"), v.photos,
            category_summary(v.tasks, labels),
            " | ".join(shorten(t.text, 90) for t in v.tasks)[:1500],
            "; ".join(dict.fromkeys(v.notes)),
        ])
    _write(path, ["date", "weekday", "arrival_msg_time", "last_msg_time", "hours", "hours_method", "rate_eur_h",
                  "labour_eur", "shopping_eur", "stores", "paid_eur", "balance_after_eur", "announced_in_advance",
                  "evidence", "n_requests", "n_cleaner_updates", "n_photos_by_cleaner", "task_categories",
                  "tasks_summary", "notes"], rows)


def write_tasks(ex: Extraction, path: Path) -> None:
    labels = {c.key: c.label for c in ex.config.categories} | {"other": "Other"}
    _write(path, ["visit_date", "message_datetime", "author", "role", "kind", "categories", "status", "text", "replies"],
           ([t.visit_date.isoformat() if t.visit_date else "", t.message.timestamp.isoformat(sep=" "), t.author,
             t.role, t.kind, "; ".join(labels.get(c, c) for c in t.categories), t.status,
             " ".join(t.text.split()), " / ".join(" ".join(r.split()) for r in t.replies)] for t in ex.tasks))


def write_ledger(ex: Extraction, path: Path) -> None:
    _write(path, ["datetime", "visit_date", "event", "paid_eur", "shopping_eur", "labour_eur", "rate_eur_h", "hours",
                  "visits_covered", "balance_after_eur", "balance_meaning", "text", "notes"],
           ([e.timestamp.isoformat(sep=" "), e.visit_date.isoformat() if e.visit_date else "", e.kind, e.paid_eur,
             e.shopping_eur, e.labor_eur, e.rate, e.hours, e.visits_covered, e.balance_after,
             "" if e.balance_after is None else ("credit (prepaid)" if e.balance_after > 0 else
                                                 "owed to cleaner" if e.balance_after < 0 else "settled"),
             " ".join(e.text.split()), e.notes] for e in ex.ledger))


def write_shopping(ex: Extraction, path: Path) -> None:
    _write(path, ["visit_date", "message_datetime", "store", "item", "quantity", "unit", "requested_by", "source",
                  "trip_total_eur", "text"],
           ([i.visit_date.isoformat() if i.visit_date else "", i.timestamp.isoformat(sep=" "), i.store, i.item,
             i.quantity, i.unit, i.requested_by, i.source, i.trip_total_eur or None, " ".join(i.text.split())]
            for i in ex.shopping))


def write_manual(ex: Extraction, csv_path: Path, md_path: Path | None = None) -> None:
    _write(csv_path, ["category", "kind", "instruction", "times_given", "first_date", "last_date", "given_by",
                      "other_wordings"],
           ([e.category, e.kind, " ".join(e.instruction.split()), e.times_given, e.first_date.isoformat(),
             e.last_date.isoformat(), ", ".join(sorted(e.given_by)),
             " || ".join(" ".join(v.split()) for v in e.variants if v != e.instruction)] for e in ex.manual))
    if md_path:
        lines = [f"# House manual — {ex.chat.title or 'household'}", "",
                 "Recurring instructions given to the cleaner, grouped by area. "
                 "`×N` = how many times it was said in the chat.", ""]
        cur = None
        for e in ex.manual:
            if e.category != cur:
                cur = e.category
                lines += ["", f"## {cur}", ""]
            txt = " ".join(e.instruction.split())
            lines.append(f"- {'**Q&A** ' if e.kind == 'Q&A' else ''}{txt}  _(×{e.times_given}, "
                         f"{e.first_date.isoformat()} → {e.last_date.isoformat()})_")
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_all(ex: Extraction, outdir: str | Path) -> dict[str, Path]:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "visits": out / "visits.csv", "tasks": out / "tasks.csv", "ledger": out / "ledger.csv",
        "shopping": out / "shopping.csv", "manual": out / "house_manual.csv", "manual_md": out / "house_manual.md",
        "calendar_html": out / "calendar.html", "calendar_ics": out / "calendar.ics",
    }
    write_visits(ex, paths["visits"])
    write_tasks(ex, paths["tasks"])
    write_ledger(ex, paths["ledger"])
    write_shopping(ex, paths["shopping"])
    write_manual(ex, paths["manual"], paths["manual_md"])
    paths["calendar_html"].write_text(render_html(ex), encoding="utf-8")
    paths["calendar_ics"].write_text(render_ics(ex), encoding="utf-8")
    return paths
