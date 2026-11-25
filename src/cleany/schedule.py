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
    weight: float = 1.0              # share of a visit's extraordinary capacity (1 = long job, 0.25 = a setting)


CADENCE_POLICY: dict[str, Policy] = {
    # --- tasks seen in the chat ---
    "wardrobes_cupboards": Policy(days=28, reason="observed median 27 d → monthly, rotating rooms"),
    "dishwasher_filter": Policy(weight=0.5, reason="observed median 60 d"),
    "mosquito_screens": Policy(days=63, season=(4, 5, 6, 7, 8, 9),
                               reason="observed 63 d between in-season cleanings; only April–September"),
    "windows": Policy(days=120, reason="done once (with screens/sills); ~3 times a year assumed"),
    "sofas": Policy(days=182, reason="observed intervals belong to one washing project; twice a year assumed"),
    "balcony": Policy(days=182, reason="asked ~yearly; spring and autumn assumed"),
    "fridge": Policy(days=90, reason="single request; quarterly assumed"),
    "light_fittings": Policy(days=365, reason="single mention; yearly assumed"),
    "slicer": Policy(days=90, weight=0.5, reason="single request; quarterly assumed"),
    "crevices": Policy(on_demand=True, reason="one-off job (corridor holes / under furniture)"),
    "spills": Policy(on_demand=True, reason="accident clean-ups happen when needed"),
    "stain_removal": Policy(days=30, weight=0.5, reason="requests every ~33 d (median); monthly, tablecloths + rags"),
    # --- suggested additions (not in the chat history) ---
    "washing_machine_filter": Policy(days=90, weight=0.5, reason="suggested: drain-pump filter every 3 months"),
    "hood_filters": Policy(days=60, weight=0.5, reason="suggested: frequent cooking"),
    "oven": Policy(days=60, reason="suggested: oven used for vegetables"),
    "pantry": Policy(days=90, reason="suggested: complements the fridge clean-out"),
    "bins": Policy(days=30, weight=0.5, reason="suggested: hygiene and smells"),
    "dishwasher_descale": Policy(days=60, weight=0.25, reason="suggested: hard water; run with the filter"),
    "washer_cycle": Policy(days=30, weight=0.25, reason="suggested: hard water, washes mostly at 30–40°"),
    "dryer": Policy(days=30, weight=0.25, reason="suggested: dryer in regular use"),
    "taps_descale": Policy(days=30, weight=0.5, reason="suggested: limescale (frequent Viakal requests)"),
    "drains": Policy(days=60, weight=0.5, reason="suggested: prevent clogs"),
    "grout": Policy(days=90, reason="suggested: mould and limescale"),
    "mattresses": Policy(days=90, reason="suggested: dust mites"),
    "pillows_duvets": Policy(days=182, season=(4, 10), reason="suggested: at the change of season (Apr, Oct)"),
    "seasonal_wardrobe": Policy(days=182, season=(4, 10), reason="suggested: change of season (Apr, Oct)"),
    "curtains": Policy(days=182, reason="suggested: twice a year (if present)"),
    "cobwebs": Policy(days=90, weight=0.5, reason="requested: check and remove cobwebs in ceiling and floor corners"),
    "touch_points": Policy(days=30, weight=0.5, reason="suggested: small child at home"),
    "vacuum": Policy(days=30, weight=0.25, reason="suggested: the vacuum stopped working at times"),
    "toys": Policy(days=30, weight=0.5, reason="suggested: child hygiene"),
    "child_gear": Policy(days=60, weight=0.5, reason="suggested: child hygiene"),
    "cellar": Policy(days=182, reason="suggested: the cellar is used a lot"),
    "ac_filters": Policy(days=182, season=(5, 10), weight=0.5, reason="suggested: before and after summer (if present)"),
    "cushion_covers": Policy(days=90, weight=0.5, reason="suggested: every 3 months, twice a year with the sofa covers"),
    "towels_hot": Policy(days=30, weight=0.25, reason="suggested: monthly 60° hygienic wash (weekly 40° stays routine)"),
}

LABELS_IT: dict[str, str] = {
    "wardrobes_cupboards": "Armadi e mobili (sopra e dentro)", "rugs": "Tappeti",
    "dishwasher_filter": "Filtro lavastoviglie", "mosquito_screens": "Zanzariere", "doors": "Porte / sopra le porte",
    "bathroom_deep": "Bagno a fondo (piastrelle, cassetti)", "fridge": "Pulizia frigorifero", "slicer": "Affettatrice",
    "windows": "Vetri, finestre, tapparelle", "window_sills": "Davanzali", "skirting_boards": "Battiscopa",
    "radiators": "Caloriferi", "sofas": "Divani (fodere e sotto)", "balcony": "Balcone", "light_fittings": "Lampadari",
    "crevices": "Fessure e sotto i mobili", "spills": "Pulizie dopo incidenti",
    "stain_removal": "Smacchiare e igienizzare tovaglie e strofinacci",
    "washing_machine_filter": "Filtro lavatrice", "hood_filters": "Filtri antigrasso cappa", "oven": "Forno (interno)",
    "pantry": "Dispensa (svuotare, ripiani, scadenze)", "bins": "Pattumiere e secchi differenziata",
    "dishwasher_descale": "Lavastoviglie: ciclo anticalcare e guarnizioni",
    "washer_cycle": "Lavatrice: ciclo a vuoto 90°, guarnizione oblò, cassetto",
    "dryer": "Asciugatrice: condensatore", "taps_descale": "Anticalcare rubinetti, rompigetto, soffione",
    "drains": "Scarichi e sifoni", "grout": "Fughe e silicone", "mattresses": "Materassi (aspirare e girare)",
    "pillows_duvets": "Cuscini e piumoni (lavaggio)", "seasonal_wardrobe": "Cambio stagione armadi",
    "curtains": "Tende (lavaggio)", "cobwebs": "Rimozione eventuali ragnatele da angoli soffitto e pavimenti",
    "touch_points": "Interruttori, maniglie, telecomandi", "vacuum": "Aspirapolvere: svuotare e lavare filtri",
    "toys": "Giochi di Niccolò (lavare e igienizzare)", "child_gear": "Seggiolone, passeggino, seggiolino auto",
    "cellar": "Cantina (riordino e polvere)", "ac_filters": "Filtri condizionatore",
    "cushion_covers": "Rivestimenti cuscini (divano/decorativi)", "towels_hot": "Asciugamani a 60° (igienizzante)",
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
    weight: float = 1.0


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
        out.append(Cadence(s.key, labels.get(s.key, s.label), days, source, p.season, False, s.last, reason, p.weight))
    # jobs with a fixed cadence in the policy but never mentioned in the chat: start from the schedule start
    seen = {c.key for c in out}
    for key, p in policy.items():
        if key not in seen and p.days and not p.on_demand:
            out.append(Cadence(key, labels.get(key, key), p.days, "policy (no history)", p.season, False, None,
                               p.reason, p.weight))
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
                   max_per_visit: float = 2) -> list[DueItem]:
    """``max_per_visit`` is a capacity in weight units (a long job weighs 1)."""
    load: Counter = Counter()
    items: list[DueItem] = []

    def slot(d: date, w: float) -> date:
        while d.weekday() not in weekdays or _in_absence(d, absences) or load[d] + w > max_per_visit + 1e-9:
            d += timedelta(days=1)
        return d

    def in_season(d: date, season) -> date:
        if not season:
            return d
        while d.month not in season:
            d = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        return d

    # Jobs with no history would all start on day one: stagger each group of equal cadence across its first cycle.
    fresh: dict[int, list[Cadence]] = {}
    for c in cads:
        if not c.on_demand and c.last_done is None:
            fresh.setdefault(c.days, []).append(c)
    first_target: dict[str, date] = {}
    for days, group in fresh.items():
        for j, c in enumerate(sorted(group, key=lambda c: c.key)):
            first_target[c.key] = start + timedelta(days=round(j * days / len(group)))

    # most frequent jobs first, so they get the earliest slots
    for c in sorted((c for c in cads if not c.on_demand), key=lambda c: c.days):
        target = (c.last_done + timedelta(days=c.days)) if c.last_done else first_target[c.key]
        overdue = target < start and (not c.season or start.month in c.season)
        target = max(target, start)
        n = 0
        while True:
            target = in_season(target, c.season)
            d = slot(target, c.weight)
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
            load[d] += c.weight
            nxt = d + timedelta(days=c.days)
            if c.season and nxt.year > d.year and d.month in c.season:
                nxt = max(nxt, date(d.year + 1, c.season[0], 1))
            target = nxt
    items.sort(key=lambda i: (i.date, i.label))
    return items


def plan(ex, start: date, end: date, max_per_visit: float = 2, policy: dict[str, Policy] | None = None):
    """Convenience wrapper: (cadences, due items, weekdays, absence windows) for an Extraction."""
    vd = [v.date for v in ex.visits]
    cads = cadences(ex.extra_summary, policy)
    wds = working_weekdays(vd)
    abs_ = absence_windows(vd)
    return cads, build_schedule(cads, start, end, wds, abs_, max_per_visit), wds, abs_
