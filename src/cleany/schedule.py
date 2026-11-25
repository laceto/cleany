"""Forward schedule of extraordinary cleaning tasks.

Each task's cadence is its median observed interval (``extraordinary.summarize``), unless
``CADENCE_POLICY`` overrides it: too little data, a project that distorts the median,
seasonal or on-demand jobs. Due dates are moved onto the cleaner's usual working weekdays,
skip the absence periods seen in the chat (repeated every year) and are capped at
``max_per_visit`` extraordinary jobs per visit, so overdue work is spread out.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from .extraordinary import DEFAULT_EXTRAORDINARY, TypeSummary


@dataclass(frozen=True)
class Policy:
    days: int | None = None          # fixed cadence (overrides the observed median)
    min_days: int = 14               # clamp for the observed median
    max_days: int = 365
    season: tuple[int, ...] | None = None   # months in which the job may be scheduled
    on_demand: bool = False          # don't schedule; do when needed
    reason: str = ""


CADENCE_POLICY: dict[str, Policy] = {
    "wardrobes_cupboards": Policy(days=28, reason="observed median 27 d → monthly, rotating rooms"),
    "mosquito_screens": Policy(days=63, season=(4, 5, 6, 7, 8, 9),
                               reason="observed 63 d between in-season cleanings; only April–September"),
    "windows": Policy(days=120, reason="done once (with screens/sills); ~3 times a year assumed"),
    "sofas": Policy(days=182, reason="observed intervals belong to one washing project; twice a year assumed"),
    "balcony": Policy(days=182, reason="asked ~yearly; spring and autumn assumed"),
    "fridge": Policy(days=90, reason="single request; quarterly assumed"),
    "light_fittings": Policy(days=365, reason="single mention; yearly assumed"),
    "slicer": Policy(days=90, reason="single request; quarterly assumed"),
    "crevices": Policy(on_demand=True, reason="one-off job (corridor holes / under furniture)"),
    "spills": Policy(on_demand=True, reason="accident clean-ups happen when needed"),
    "stain_removal": Policy(on_demand=True, reason="done with laundry when stains appear; no requests since Mar 2026"),
}


@dataclass
class Cadence:
    key: str
    label: str
    days: int | None
    source: str
    season: tuple[int, ...] | None
    on_demand: bool
    last_done: date | None
    reason: str


@dataclass
class DueItem:
    date: date
    key: str
    label: str
    occurrence: int
    cadence_days: int
    target_date: date
    overdue_at_start: bool = False
    notes: list[str] = field(default_factory=list)


def cadences(summary: list[TypeSummary], policy: dict[str, Policy] | None = None) -> list[Cadence]:
    policy = CADENCE_POLICY if policy is None else policy
    labels = {t.key: t.label for t in DEFAULT_EXTRAORDINARY}
    out = []
    for s in summary:
        p = policy.get(s.key, Policy())
        if p.on_demand:
            out.append(Cadence(s.key, labels.get(s.key, s.label), None, "on demand", None, True, s.last, p.reason))
            continue
        if p.days:
            days, source = p.days, "policy"
        elif s.intervals:
            days = int(round(min(max(statistics.median(s.intervals), p.min_days), p.max_days)))
            source = f"median of {len(s.intervals)} observed interval(s)"
        else:
            days, source = 180, "default (no history)"
        reason = p.reason or f"observed intervals {', '.join(map(str, s.intervals))} d"
        out.append(Cadence(s.key, labels.get(s.key, s.label), days, source, p.season, False, s.last, reason))
    return out


def working_weekdays(visit_dates: list[date], n: int = 3) -> list[int]:
    """The cleaner's usual weekdays (most frequent ``n``)."""
    return sorted(w for w, _ in Counter(d.weekday() for d in visit_dates).most_common(n))


def absence_windows(visit_dates: list[date], min_gap_days: int = 12, max_gap_days: int = 35) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Gaps in the visit history (holidays), as (month, day) ranges to repeat every year."""
    ds = sorted(visit_dates)
    out = []
    for a, b in zip(ds, ds[1:]):
        if min_gap_days <= (b - a).days <= max_gap_days:
            s, e = a + timedelta(days=1), b - timedelta(days=1)
            out.append(((s.month, s.day), (e.month, e.day)))
    return out


def _in_absence(d: date, windows) -> bool:
    md = (d.month, d.day)
    for s, e in windows:
        if (s <= e and s <= md <= e) or (s > e and (md >= s or md <= e)):   # handles Dec→Jan
            return True
    return False


def build_schedule(cads: list[Cadence], start: date, end: date, weekdays: list[int], absences,
                   max_per_visit: int = 2) -> list[DueItem]:
    load: Counter = Counter()
    items: list[DueItem] = []

    def slot(d: date) -> date:
        while d.weekday() not in weekdays or _in_absence(d, absences) or load[d] >= max_per_visit:
            d += timedelta(days=1)
        return d

    def in_season(d: date, season) -> date:
        if not season:
            return d
        while d.month not in season:
            d = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        return d

    # most frequent jobs first, so they get the earliest slots
    for c in sorted((c for c in cads if not c.on_demand), key=lambda c: c.days):
        target = (c.last_done + timedelta(days=c.days)) if c.last_done else start
        overdue = target < start and (not c.season or start.month in c.season)
        target = max(target, start)
        n = 0
        while True:
            target = in_season(target, c.season)
            d = slot(target)
            if d > end:
                break
            n += 1
            it = DueItem(d, c.key, c.label, n, c.days, target, overdue and n == 1)
            if it.overdue_at_start:
                it.notes.append(f"overdue: last {c.last_done.isoformat()}, was due "
                                f"{(c.last_done + timedelta(days=c.days)).isoformat()}")
            if d != target:
                it.notes.append(f"moved from {target.isoformat()} to a working day / free slot")
            items.append(it)
            load[d] += 1
            nxt = d + timedelta(days=c.days)
            if c.season and nxt.year > d.year and d.month in c.season:
                nxt = max(nxt, date(d.year + 1, c.season[0], 1))
            target = nxt
    items.sort(key=lambda i: (i.date, i.label))
    return items


def plan(ex, start: date, end: date, max_per_visit: int = 2, policy: dict[str, Policy] | None = None):
    """Convenience wrapper: (cadences, due items, weekdays, absence windows) for an Extraction."""
    vd = [v.date for v in ex.visits]
    cads = cadences(ex.extra_summary, policy)
    wds = working_weekdays(vd)
    abs_ = absence_windows(vd)
    return cads, build_schedule(cads, start, end, wds, abs_, max_per_visit), wds, abs_
