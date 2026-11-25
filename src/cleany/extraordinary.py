"""Extraordinary (non-routine, deep-cleaning) tasks: which, how many times, and how far apart.

Every chat message mentioning one of the task types is a *mention*. A mention is a
household request, a cleaner "done" report ("Ho pulito i caloriferi"), a cleaner deferral
("mi è rimasto ... per la settimana prossima") or another remark. Mentions of the same type
that are close in time are grouped into one *episode*, i.e. one occurrence of the job.
Intervals are measured between episodes.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import Config
from .parser import Message
from .textutil import norm

_V = r"(?:pul\w*|lav\w*|spolver\w*|fatt[oie]|fare|fai|fatto|aspir\w*|bonific\w*)"


@dataclass(frozen=True)
class TaskType:
    key: str
    label: str
    pattern: str

    @property
    def regex(self) -> re.Pattern:
        return re.compile(self.pattern, re.I)


DEFAULT_EXTRAORDINARY: tuple[TaskType, ...] = (
    TaskType("mosquito_screens", "Mosquito screens", r"zanzarier"),
    TaskType("windows", "Windows / glass / shutters", r"\bvetri\b|" + _V + r"[^.]{0,30}tapparell"),
    TaskType("window_sills", "Window sills", r"davanzal"),
    TaskType("radiators", "Radiators", _V + r"[^.]{0,40}(?:calorifer|termosifon)|(?:calorifer|termosifon)\w*[^.]{0,20}" + _V),
    TaskType("dishwasher_filter", "Dishwasher filter / deep clean", r"filtro[^.]{0,25}lavastovigli|lavastovigli[^.]{0,30}filtro"),
    TaskType("washing_machine_filter", "Washing machine filter", r"filtr\w*[^.]{0,25}lavatric|lavatric\w*[^.]{0,30}filtr"),
    TaskType("doors", "Doors / top of doors", r"sopra (?:le )?porte|" + _V + r"[^.]{0,15}(?:tutte )?le porte"),
    TaskType("wardrobes_cupboards", "Wardrobes & cupboards (top / inside)",
             r"(?:sopra|dentro|negli|nei|nel|gli|i)\s+(?:gli |i |le )?(?:armad\w*|mobil[ei])\b(?! nella stanz)|"
             r"polvere negli armadi|sopra (?:la )?cucina|lavare questo mobile|scaffali dopo averli puliti|"
             r"mensole nel armadio"),
    TaskType("skirting_boards", "Skirting boards cleaning", r"battiscopa"),
    TaskType("sofas", "Sofas (washing covers / underneath)", r"divan"),
    TaskType("rugs", "Rugs", r"tappet"),
    TaskType("balcony", "Balcony", r"balconcin|" + _V + r"[^.]{0,15}(?:sul |il )?balcon"),
    TaskType("bathroom_deep", "Bathroom deep clean (tiles, drawers)", r"piastrell|bagno in modo approfondito|cassetti del bagno"),
    TaskType("fridge", "Fridge clean-out", r"cassett\w* (?:del )?frig|(?:pulir\w*|pulisci|lavar\w*|lava) (?:il |dentro (?:il )?)frigo"),
    TaskType("light_fittings", "Light fittings", r"lampadar"),
    TaskType("slicer", "Meat slicer", r"affettatric"),
    TaskType("crevices", "Crevices / under furniture (toothpick job)", r"stuzzicadent|buchi (?:nel|vicino)|sotto il mobile"),
    TaskType("spills", "Spill / accident clean-up", r"bonific|ho versato|raccoglilo"),
    TaskType("stain_removal", "Stain removal (tablecloths, rags)", r"smacchi"),
    TaskType("hood_filters", "Hood grease filters", r"cappa"),
    TaskType("oven", "Oven (inside)", r"(?:pulir\w*|pulisci|lavar\w*)[^.]{0,15}(?:il )?forno|forno[^.]{0,15}pulit"),
    TaskType("pantry", "Pantry clean-out", r"dispensa[^.]{0,30}(?:pulir|svuot|riordin)|(?:pulir|svuot|riordin)\w*[^.]{0,20}dispensa"),
    TaskType("bins", "Bins & recycling containers", r"(?:lavar|pulir|lava|pulisci)\w*[^.]{0,20}(?:pattumier|secchi della|bidon)"),
    TaskType("dishwasher_descale", "Dishwasher descaling cycle & seals",
             r"lavastovigli\w*[^.]{0,30}(?:anticalcare|a vuoto|guarnizion)"),
    TaskType("washer_cycle", "Washing machine empty hot cycle, door seal, drawer",
             r"lavatric\w*[^.]{0,30}(?:a vuoto|guarnizion|oblò|cassetto)"),
    TaskType("dryer", "Dryer condenser", r"asciugatric\w*[^.]{0,30}(?:condensator|scambiator|filtr)"),
    TaskType("taps_descale", "Taps, aerators & shower head descaling",
             r"rompigett|soffion|(?:anticalcare|calcare)[^.]{0,20}rubinett"),
    TaskType("drains", "Drains & traps", r"\bsifon|scaric\w*[^.]{0,20}(?:lavandin|vasca|doccia)"),
    TaskType("grout", "Grout & silicone", r"\bfughe\b|silicon"),
    TaskType("mattresses", "Mattresses (vacuum & turn)", r"(?:aspir|gir)\w*[^.]{0,20}materass"),
    TaskType("pillows_duvets", "Pillows & duvets (wash)", r"lav\w*[^.]{0,20}(?:piumon|cuscini del letto)"),
    TaskType("seasonal_wardrobe", "Seasonal wardrobe change", r"cambio (?:di )?stagion|cambio armadi"),
    TaskType("curtains", "Curtains (wash)", r"\btende\b"),
    TaskType("cobwebs", "Cobweb removal: ceiling and floor corners",
             r"ragnatel|\bsoffitti?\b|angol\w*[^.]{0,20}(?:soffitt|paviment)"),
    TaskType("touch_points", "Switches, handles & remotes", r"interruttor|maniglie|telecomand"),
    TaskType("vacuum", "Vacuum cleaner filters", r"aspirapolvere[^.]{0,30}(?:filtr|svuot)|(?:filtr|svuot)\w*[^.]{0,20}aspirapolvere"),
    TaskType("toys", "Child's toys (wash & sanitise)", r"(?:lav|igienizz|disinfett)\w*[^.]{0,20}giochi"),
    TaskType("child_gear", "High chair, stroller & car seat", r"seggiolon|passeggin|seggiolin"),
    TaskType("cellar", "Cellar tidy & dust", r"(?:pulir|riordin|polvere|spolver)\w*[^.]{0,20}cantin"),
    TaskType("ac_filters", "Air-conditioner filters", r"condizionator|climatizzator"),
    TaskType("cushion_covers", "Cushion covers (sofa/decorative)", r"copricuscin|(?:rivestiment|fodere)\w*[^.]{0,20}cuscin"),
    TaskType("towels_hot", "Towels hot wash at 60°", r"asciugaman\w*[^.]{0,30}60"),
)

_DONE = re.compile(r"\b(?:ho|abbiamo)\s+(?:già\s+|quasi\s+)?(?:finito di\s+)?(?:pulito|lavato|fatto|spolverato|finito|smacchiato)|"
                   r"^oggi ho pulito|già fatto")
_DEFER = re.compile(r"rimast[oie]|\bfarò\b|settimana prossima|\bprossima volta\b|li porterò|\bdevo finire\b|quando riuscirò|poi lunedì")


@dataclass
class Mention:
    type_key: str
    date: date                 # visit date the mention refers to
    message: Message
    author: str
    role: str                  # household | cleaner
    kind: str                  # request | done | partial/deferred | remark
    text: str


@dataclass
class Episode:
    type_key: str
    label: str
    date: date                 # date the job was done (done report) or last requested
    status: str                # done (reported) | partially done | requested, no confirmation
    mentions: list[Mention] = field(default_factory=list)
    days_since_previous: int | None = None


def _cleaner_date(m: Message, visit_dates: list[date]) -> date:
    d = m.date
    if re.search(r"\bieri\b", norm(m.text)):
        d = d - timedelta(days=1)
    if d in visit_dates:
        return d
    prev = [v for v in visit_dates if v <= d]
    return prev[-1] if prev and (d - prev[-1]).days <= 4 else d


def find_mentions(messages: list[Message], visits, cleaner: str, config: Config,
                  types: tuple[TaskType, ...] = DEFAULT_EXTRAORDINARY) -> list[Mention]:
    from .tasks import _target_visit
    visit_dates = [v.date for v in visits]
    out: list[Mention] = []
    for m in messages:
        if m.system or not m.has_text:
            continue
        t = norm(m.text)
        hits = [ty for ty in types if ty.regex.search(t)]
        if not hits:
            continue
        if m.author == cleaner:
            d = _cleaner_date(m, visit_dates)
            # walk the clauses: "Ho fatto i vetri, zanzariere ... Più quando riuscirò farò i battiscopa, sotto il mobile"
            state, kinds = "remark", {}
            for clause in re.split(r"[,;.\n]| e poi | poi ", t):
                if _DEFER.search(clause):
                    state = "partial/deferred"
                elif _DONE.search(clause):
                    state = "done"
                for ty in hits:
                    if ty.key not in kinds and ty.regex.search(clause):
                        kinds[ty.key] = state
            for ty in hits:
                k = kinds.get(ty.key) or ("done" if _DONE.search(t) else "partial/deferred" if _DEFER.search(t) else "remark")
                out.append(Mention(ty.key, d, m, config.name(m.author), "cleaner", k, m.text))
        else:
            v = _target_visit(m, visits, visit_dates, config)
            d = v.date if v else m.date
            kind = "remark" if re.search(r"\bnon (?:avevi|mi ricordo|rimettere)\b", t) else "request"
            for ty in hits:
                out.append(Mention(ty.key, d, m, config.name(m.author), "household", kind, m.text))
    out.sort(key=lambda x: (x.message.timestamp, x.type_key))
    return out


def build_episodes(mentions: list[Mention], types: tuple[TaskType, ...] = DEFAULT_EXTRAORDINARY,
                   gap_days: int = 14) -> list[Episode]:
    """Group a type's mentions into episodes. A new episode starts when a mention comes more than
    ``gap_days`` after the previous one, or after an episode that was already reported done."""
    labels = {t.key: t.label for t in types}
    episodes: list[Episode] = []
    for key in labels:
        ms = sorted((m for m in mentions if m.type_key == key), key=lambda m: m.message.timestamp)
        cur: list[Mention] = []

        def close():
            if not cur:
                return
            done = [m for m in cur if m.kind == "done"]
            partial = [m for m in cur if m.kind == "partial/deferred"]
            if done:
                status, d = "done (reported)", done[-1].date
            elif partial:
                status, d = "partially done / postponed", partial[-1].date
            else:
                status, d = "requested, no confirmation in chat", max(m.date for m in cur)
            episodes.append(Episode(key, labels[key], d, status, list(cur)))

        for m in ms:
            if cur:
                last = cur[-1]
                already_done = any(x.kind == "done" for x in cur) and m.role == "household" and m.kind == "request"
                if (m.date - last.date).days > gap_days or already_done:
                    close()
                    cur = []
            cur.append(m)
        close()

    episodes.sort(key=lambda e: (e.type_key, e.date))
    prev: dict[str, date] = {}
    for e in episodes:
        if e.type_key in prev:
            e.days_since_previous = (e.date - prev[e.type_key]).days
        prev[e.type_key] = e.date
    episodes.sort(key=lambda e: (e.date, e.type_key))
    return episodes


@dataclass
class TypeSummary:
    key: str
    label: str
    episodes: int
    done: int
    requested_only: int
    partial: int
    first: date | None
    last: date | None
    intervals: list[int]
    days_since_last: int | None
    next_due: date | None

    @property
    def mean_interval(self):
        return round(statistics.mean(self.intervals), 1) if self.intervals else None

    @property
    def median_interval(self):
        return statistics.median(self.intervals) if self.intervals else None


def summarize(episodes: list[Episode], end: date, types: tuple[TaskType, ...] = DEFAULT_EXTRAORDINARY) -> list[TypeSummary]:
    out = []
    for ty in types:
        es = sorted((e for e in episodes if e.type_key == ty.key), key=lambda e: e.date)
        if not es:
            continue
        ivs = [e.days_since_previous for e in es if e.days_since_previous is not None]
        last = es[-1].date
        med = statistics.median(ivs) if ivs else None
        out.append(TypeSummary(
            ty.key, ty.label, len(es),
            sum(e.status.startswith("done") for e in es),
            sum(e.status.startswith("requested") for e in es),
            sum(e.status.startswith("partially") for e in es),
            es[0].date, last, ivs, (end - last).days,
            last + timedelta(days=round(med)) if med else None))
    out.sort(key=lambda s: (-s.episodes, s.label))
    return out
