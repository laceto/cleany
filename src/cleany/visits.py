"""Detect cleaner visits and reconstruct hours / payments per visit."""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .config import Config
from .ledger import BalanceReport, CashLeft, RateChange, collect_money_messages, parse_report
from .parser import Message
from .textutil import norm, weekday_targets

_ARRIVAL = re.compile(
    r"tra poco arriv|sto arrivando|^arrivo\b|arriverò (?:alle|verso|per le)|"
    r"(?:più|piu) meno (?:alle )?\d{1,2}[.:/]\d{2}|^prima (?:di|delle) \d{1,2}|^alle \d{1,2}[.:]\d{2}"
)
_SCHEDULE_NEG = re.compile(r"\bnon\b|medico|malat|ferie|non ci sar|\bdevo\b|dimenticat|liber")
_WD = r"(?:lunedì|lunedi|martedì|martedi|mercoledì|mercoledi|giovedì|giovedi|venerdì|venerdi|sabato|domani)"


def is_arrival(text: str) -> bool:
    t = norm(text)
    if re.search(r"\b" + _WD + r"\b", t) and "oggi" not in t:
        return False
    return bool(_ARRIVAL.search(t))


def planned_dates(text: str, ref: date) -> list[date]:
    """Dates announced in schedule messages such as 'Ciao, vengo martedì, giovedì e venerdì'."""
    t = norm(text)
    if "dimenticat" in t or not (re.search(r"\bvengo\b", t) or re.match(r"^(?:ciao\s*,?\s*)?" + _WD + r"\b", t)):
        return []
    out: list[date] = []
    for seg in re.split(r"[,.;]| ma ", t):
        if _SCHEDULE_NEG.search(seg) and not re.search(r"\bvengo\b", seg):
            continue
        # drop negated part inside a segment ("vengo giovedì non domani")
        seg = re.sub(r"\b(?:non|invece\s+di)\s+\w+", "", seg)
        out += weekday_targets(seg, ref)
    return sorted(set(out))


@dataclass
class Visit:
    date: date
    arrival: datetime | None = None
    first_msg: datetime | None = None
    last_msg: datetime | None = None
    evidence: list[str] = field(default_factory=list)
    reports: list[BalanceReport] = field(default_factory=list)
    planned: bool = False
    labor_eur: float | None = None
    rate: float | None = None
    hours: float | None = None
    hours_method: str = "unknown"
    reported_hours: float | None = None
    shopping_eur: float = 0.0
    paid_eur: float = 0.0
    balance_after: float | None = None
    photos: int = 0
    notes: list[str] = field(default_factory=list)
    tasks: list = field(default_factory=list)          # filled by tasks.assign_tasks
    stores: set[str] = field(default_factory=set)

    @property
    def start(self) -> datetime:
        return self.arrival or self.first_msg or datetime.combine(self.date, time(13, 0))

    def end(self, default_hours: float) -> datetime:
        est = self.start + timedelta(hours=self.hours or default_hours)
        return max(est, self.last_msg) if self.last_msg else est


@dataclass
class LedgerEntry:
    timestamp: datetime
    visit_date: date | None
    kind: str                 # opening_balance | report | correction | expense_only | cash_left | rate_change
    paid_eur: float | None = None
    shopping_eur: float | None = None
    balance_after: float | None = None
    labor_eur: float | None = None
    hours: float | None = None
    rate: float | None = None
    visits_covered: int | None = None
    text: str = ""
    notes: str = ""


def detect_cleaner(messages: list[Message], config: Config) -> str:
    if config.cleaner:
        return config.cleaner
    score: Counter = Counter()
    for m in messages:
        if m.system or not m.has_text:
            continue
        if parse_report(m.text, config.stores) and re.search(r"rimane|\bsono \d", norm(m.text)):
            score[m.author] += 2
        if is_arrival(m.text):
            score[m.author] += 1
    if not score:
        raise ValueError("Could not detect the cleaner; pass Config(cleaner=...)")
    return score.most_common(1)[0][0]


def _rate_for(d: date, schedule: list[tuple[date, float]]) -> float | None:
    rate = None
    for eff, r in schedule:
        if d >= eff:
            rate = r
    return rate


def build_visits(messages: list[Message], cleaner: str, config: Config):
    """Return (visits sorted by date, ledger entries, planned dates set)."""
    cmsgs = [m for m in messages if m.author == cleaner and not m.system]
    by_day: dict[date, list[Message]] = {}
    for m in cmsgs:
        by_day.setdefault(m.date, []).append(m)

    visits: dict[date, Visit] = {}

    def visit(d: date) -> Visit:
        if d not in visits:
            v = Visit(d)
            day = by_day.get(d, [])
            if day:
                v.first_msg = min(x.timestamp for x in day if x.timestamp.hour >= 9) if any(
                    x.timestamp.hour >= 9 for x in day) else None
                v.last_msg = max(x.timestamp for x in day)
            visits[d] = v
        return visits[d]

    # 1) arrivals
    for m in cmsgs:
        if m.has_text and is_arrival(m.text):
            if m.timestamp.hour >= 19:      # evening ETA ("arriverò alle 12.30") is for tomorrow
                v = visit(m.date + timedelta(days=1))
                if "arrival message" not in v.evidence:
                    v.evidence.append("arrival message")
                continue
            v = visit(m.date)
            if v.arrival is None or m.timestamp < v.arrival:
                v.arrival = m.timestamp
            if "arrival message" not in v.evidence:
                v.evidence.append("arrival message")

    # 2) money messages, attributed to a visit
    reports, rates, cash = collect_money_messages(messages, cleaner, config)
    arrival_days = sorted(visits)

    def previous_visit_day(d: date) -> date | None:
        prev = [x for x in arrival_days if x < d and (d - x).days <= 7]
        return prev[-1] if prev else None

    for rep in reports:
        m = rep.message
        target = m.date
        arr = visits[m.date].arrival if m.date in visits else None
        late_note = "dimenticat" in norm(m.text) and rep.balance is None
        if rep.refers_to_yesterday or late_note or (arr and m.timestamp < arr) or (not arr and m.timestamp.hour < 10):
            mentioned = weekday_targets(m.text, m.date - timedelta(days=7)) if late_note else []
            mentioned = [x for x in mentioned if x < m.date and x in visits]
            target = mentioned[-1] if mentioned else (previous_visit_day(m.date) or m.date)
            if target != m.date:
                rep.notes.append(f"posted on {m.date.isoformat()}, refers to visit of {target.isoformat()}")
        v = visit(target)
        v.reports.append(rep)
        if "balance report" not in v.evidence and rep.is_balance:
            v.evidence.append("balance report")
        if rep.store:
            v.stores.add(rep.store)

    # 3) planned schedule
    # A newer announcement replaces older ones for the days it covers (the following week).
    planned: set[date] = set()
    for m in cmsgs:
        if m.has_text and "?" not in m.text:
            new = planned_dates(m.text, m.date)
            if new:
                horizon = max(new)
                cancelled = set(weekday_targets(re.sub(r"\b(?:non|invece\s+di)\b", "", norm(m.text)), m.date))
                planned = {d for d in planned if not (m.date <= d <= horizon) and d not in cancelled} | set(new)
    last_day = max(x.date for x in messages)
    planned = {d for d in planned if d <= last_day}
    for v in visits.values():
        v.planned = v.date in planned
        v.photos = sum(1 for x in by_day.get(v.date, []) if x.media in ("image", "video"))
        for x in by_day.get(v.date, []):
            if x.has_text and re.search(r"\b(" + config.stores + r")\b", norm(x.text)):
                st = re.search(r"\b(" + config.stores + r")\b", norm(x.text)).group(1).capitalize()
                v.stores.add("Unes" if st == "Ubers" else st)

    # 4) end of the working window: the same-day report, else the last real (non-ack) message before 20:00
    from .textutil import is_ack
    for v in visits.values():
        same_day = [r.message.timestamp for r in v.reports if r.message.date == v.date]
        work = [x.timestamp for x in by_day.get(v.date, [])
                if x.timestamp.hour < 20 and x.timestamp >= v.start and not (x.has_text and is_ack(x.text))]
        if same_day:
            cutoff = max(same_day)
            work = [t for t in work if t <= cutoff + timedelta(minutes=30)] + [cutoff]
        v.last_msg = max(work) if work else None

    ordered = sorted(visits.values(), key=lambda v: v.date)
    entries = _reconstruct_ledger(ordered, rates, cash, config)
    return ordered, entries, planned


def _reconstruct_ledger(visits: list[Visit], rates: list[RateChange], cash: list[CashLeft], config: Config):
    entries: list[LedgerEntry] = []
    index = {v.date: i for i, v in enumerate(visits)}
    prev_balance: float | None = None
    prev_idx = -1
    pending: list[tuple[datetime, float]] = []
    labor_parts: dict[int, list[tuple[float, int]]] = {}

    all_reports = sorted(((r.message.timestamp, index[d.date], r) for d in visits for r in d.reports), key=lambda x: x[0])
    # process in visit order, then time
    all_reports.sort(key=lambda x: (x[1], x[0]))
    for ts, i, rep in all_reports:
        v = visits[i]
        v.shopping_eur += rep.shopping
        v.paid_eur += rep.paid
        if rep.reported_hours is not None:
            v.reported_hours = rep.reported_hours
        if rep.extra_half_hour:
            v.notes.append("cleaner reported half an hour extra")
        v.notes += [n for n in rep.notes if n not in v.notes]
        e = LedgerEntry(ts, v.date, "report", rep.paid or None, rep.shopping or None, rep.balance,
                        text=rep.message.text, notes="; ".join(rep.notes))
        if rep.balance is None:
            e.kind = "expense_only"
            pending.append((ts, rep.shopping))
            e.notes = "; ".join(rep.notes + ["not yet reflected in a balance"])
            entries.append(e)
            continue
        if prev_balance is None:
            e.kind = "opening_balance"
            e.notes = "; ".join(rep.notes + ["first balance in the chat: labour before it is unknown"])
        else:
            pending_expense = sum(a for pts, a in pending if pts < ts)
            pending = [(pts, a) for pts, a in pending if pts >= ts]
            if rep.pre_payment_balance is not None:   # trust the pre-payment figure for labour
                labor = prev_balance - rep.shopping - pending_expense - rep.pre_payment_balance
            else:
                labor = prev_balance + rep.paid - rep.shopping - pending_expense - rep.balance
            if pending_expense:
                e.notes = "; ".join(filter(None, [e.notes, f"includes {pending_expense:g}€ expense reported separately"]))
            covered = list(range(prev_idx + 1, i + 1)) or [i]
            if prev_idx == i:
                e.kind = "correction" if abs(labor) < 1e-9 else "report"
            e.labor_eur = labor
            e.visits_covered = len(covered)
            for j in covered:
                labor_parts.setdefault(j, []).append((labor / len(covered), len(covered)))
        v.balance_after = rep.balance
        prev_balance, prev_idx = rep.balance, i
        entries.append(e)

    for j, parts in labor_parts.items():
        v = visits[j]
        v.labor_eur = round(sum(p for p, _ in parts), 2)
        n = max(c for _, c in parts)
        v.hours_method = "balance delta" if n == 1 else f"balance delta split across {n} visits"
        if n > 1:
            v.notes.append(f"one report covered {n} visits: labour split evenly")

    schedule = _rate_schedule(visits, rates, config)
    for v in visits:
        v.rate = _rate_for(v.date, schedule)
        if v.labor_eur is not None and v.rate:
            v.hours = round(v.labor_eur / v.rate, 2)
            if v.hours <= 0:
                v.notes.append("no labour in this balance step (likely a correction)")
            elif abs(v.hours * 2 - round(v.hours * 2)) > 0.05:
                v.notes.append("hours not a multiple of 0.5: check the balance messages")
            elif v.hours > 2 * config.default_visit_hours:
                v.notes.append("unusually long: may include an unreported visit")
        if v.reported_hours is not None:
            if v.hours is None:
                v.hours, v.hours_method = v.reported_hours, "reported by cleaner"
            elif abs(v.hours - v.reported_hours) > 0.05:
                v.notes.append(f"cleaner said {v.reported_hours:g}h, balance implies {v.hours:g}h")
        if v.balance_after is None and not v.reports and v.hours is None:
            v.notes.append("no balance report found for this visit")

    for e in entries:
        if e.labor_eur is not None and e.visit_date:
            r = _rate_for(e.visit_date, schedule)
            e.rate = r
            e.hours = round(e.labor_eur / r, 2) if r else None
    for rc in rates:
        entries.append(LedgerEntry(rc.message.timestamp, None, "rate_change", rate=rc.rate, text=rc.message.text))
    for c in cash:
        entries.append(LedgerEntry(c.message.timestamp, None, "cash_left", paid_eur=c.amount, text=c.message.text,
                                   notes=f"left by {config.name(c.message.author)} (informational)"))
    entries.sort(key=lambda e: e.timestamp)
    return entries


def _rate_schedule(visits: list[Visit], rates: list[RateChange], config: Config) -> list[tuple[date, float]]:
    changes = sorted([(rc.message.date, rc.rate) for rc in rates] + list(config.rate_changes))
    initial = config.initial_rate
    if initial is None:
        first_change = changes[0][0] if changes else date.max
        labors = [v.labor_eur for v in visits if v.labor_eur and v.labor_eur > 0 and v.date < first_change
                  and "split" not in v.hours_method]
        if not labors and changes:
            initial = changes[0][1]
        elif labors:
            target = config.default_visit_hours
            best = None
            for r10 in range(80, 301, 5):        # 8.0 .. 30.0 €/h
                r = r10 / 10
                hrs = [l / r for l in labors]
                halfs = sum(1 for h in hrs if abs(h * 2 - round(h * 2)) < 0.01)
                cost = (-halfs, abs(statistics.median(hrs) - target))
                if best is None or cost < best[0]:
                    best = (cost, r)
            initial = best[1]
    schedule = [(date.min, initial)] if initial else []
    return schedule + changes
