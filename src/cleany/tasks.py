"""Turn chat messages into tasks and attach them to the visit they belong to."""

from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import Config
from .ledger import parse_rate_change, parse_report
from .parser import Message
from .textutil import categorize, is_ack, norm, weekday_targets
from .visits import Visit, is_arrival, planned_dates

_DONE = re.compile(r"\b(?:ho|abbiamo)\s+(?:già\s+)?(?:pulito|lavato|fatto|messo|cambiato|buttato|steso|piegato|sceso|"
                   r"portato|preso|presso|comprato|cucinato|bollito|stirato|sistemato|tolto|smacchiato|avviato|trovato)|"
                   r"\bgià fatto\b|^trovato\b|^fatto\b")
_DEFER = re.compile(r"\bfarò\b|\bli farò\b|\blo farò\b|\bprenderò\b|\bdomani\b|settimana prossima|mi sono dimenticata")


@dataclass
class Task:
    visit_date: date | None
    message: Message
    author: str
    role: str                 # household | cleaner
    kind: str                 # request | cleaner_done | cleaner_question | cleaner_deferred | cleaner_note
    categories: list[str]
    status: str
    text: str
    replies: list[str] = field(default_factory=list)


def _target_visit(msg: Message, visits: list[Visit], dates: list[date], config: Config) -> Visit | None:
    t = msg.timestamp
    # Only a day named at the start of the message sets its target ("Domani per favore...", "Giovedì cambia...");
    # later mentions are usually side remarks ("...domani portiamo su un ddt").
    explicit = [d for d in weekday_targets(msg.text[:60], t.date()) if d >= t.date()]
    if explicit:
        d = explicit[0]
        i = bisect_left(dates, d)
        if i < len(visits) and (visits[i].date - d).days <= 3:
            return visits[i]
    for v in visits[bisect_left(dates, t.date()):]:
        if v.end(config.default_visit_hours) >= t:
            return v if (v.date - t.date()).days <= config.max_days_to_next_visit else None
    return None


def _is_admin(text: str, config: Config) -> bool:
    """Cleaner messages that are about logistics/money rather than work content."""
    return bool(is_arrival(text) or parse_report(text, config.stores) or parse_rate_change(text)
                or planned_dates(text, date.today()) or is_ack(text))


def assign_tasks(messages: list[Message], visits: list[Visit], cleaner: str, config: Config) -> list[Task]:
    dates = [v.date for v in visits]
    by_date = {v.date: v for v in visits}
    tasks: list[Task] = []
    following: dict[int, list[Message]] = {}
    for i, m in enumerate(messages):
        following[m.index] = messages[i + 1:i + 8]

    for m in messages:
        if m.system or m.deleted or not m.has_text:
            continue
        cats = categorize(m.text, config.categories)
        if m.author != cleaner:
            if not cats:
                continue
            v = _target_visit(m, visits, dates, config)
            replies = [x for x in following[m.index]
                       if x.author == cleaner and x.has_text and x.timestamp - m.timestamp < timedelta(hours=12)]
            status = "requested"
            if replies:
                first = replies[0]
                if is_ack(first.text) or _DONE.search(norm(first.text)):
                    status = "acknowledged"
                if _DEFER.search(norm(first.text)) and "?" not in first.text:
                    status = "deferred by cleaner"
            t = Task(v.date if v else None, m, config.name(m.author), "household", "request", cats, status, m.text,
                     [x.text for x in replies[:2]])
            if v:
                v.tasks.append(t)
            tasks.append(t)
        else:
            v = by_date.get(m.date)
            if v is None or _is_admin(m.text, config):
                continue
            if not (v.start - timedelta(minutes=30) <= m.timestamp <= v.end(config.default_visit_hours) + timedelta(hours=3)):
                continue
            t_norm = norm(m.text)
            if not cats and (len(t_norm) < 12 or t_norm in {"?", "basta ?", "basta?"}):
                continue
            if "?" in m.text:
                kind, status = "cleaner_question", "asked"
            elif _DONE.search(t_norm):
                kind, status = "cleaner_done", "done (reported)"
            elif _DEFER.search(t_norm):
                kind, status = "cleaner_deferred", "postponed"
            else:
                kind, status = "cleaner_note", "noted"
            replies = [x.text for x in following[m.index] if x.author != cleaner and x.has_text
                       and x.timestamp - m.timestamp < timedelta(hours=3)][:2]
            t = Task(v.date, m, config.name(m.author), "cleaner", kind, cats or ["other"], status, m.text, replies)
            v.tasks.append(t)
            tasks.append(t)

    # Mark requests as done when the cleaner later reports doing something of the same category in that visit.
    for v in visits:
        done_cats = {c for t in v.tasks if t.kind == "cleaner_done" for c in t.categories}
        for t in v.tasks:
            if t.kind == "request" and set(t.categories) & done_cats and t.status != "deferred by cleaner":
                t.status = "done (reported)"
    return tasks
