"""Shopping lists: grocery items the household asked the cleaner to buy, per visit."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .config import Config
from .parser import Message
from .textutil import norm
from .visits import Visit

_QTY_WORDS = {"un": 1, "uno": 1, "una": 1, "un'": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6,
              "mezzo": 0.5, "mezza": 0.5, "qualche": None}
_QTY = re.compile(r"(\d+|un'|un|uno|una|due|tre|quattro|cinque|sei|mezzo|mezza|qualche)\s+"
                  r"(?:(mazz[oi]|pacch[oi]|confezion[ei]|bust[ae]|vasett[oi]|litr[oi]|kg|chili|cesp[oi]|sacchett[oi])\s+"
                  r"(?:di\s+|del\s+|della\s+|dei\s+|delle\s+)?)?(?:\w+\s+)?$")


@dataclass
class ShoppingItem:
    visit_date: date | None
    timestamp: datetime
    store: str
    item: str
    quantity: float | None
    unit: str
    requested_by: str
    source: str            # household request | cleaner purchase note | photo
    text: str
    trip_total_eur: float | None


def extract_items(text: str, config: Config) -> list[tuple[str, float | None, str]]:
    t = norm(text)
    taken: list[tuple[int, int]] = []
    out = []
    for name, pat in config.groceries:
        for m in re.finditer(r"\b" + pat, t):
            if any(a < m.end() and m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            prefix = t[max(0, m.start() - 30):m.start()]
            q = _QTY.search(prefix)
            qty, unit = None, ""
            if q:
                w = q.group(1)
                qty = float(w) if w.isdigit() else _QTY_WORDS.get(w)
                unit = q.group(2) or ""
            out.append((name, qty, unit))
    # one row per item per message: keep the mention that carries a quantity
    best: dict[str, tuple[str, float | None, str]] = {}
    for name, qty, unit in out:
        if name not in best or (best[name][1] is None and qty is not None):
            best[name] = (name, qty, unit)
    return list(best.values())


def build_shopping(messages: list[Message], visits: list[Visit], tasks, cleaner: str, config: Config) -> list[ShoppingItem]:
    by_date = {v.date: v for v in visits}
    store_re = re.compile(r"\b(" + config.stores + r")\b")
    items: list[ShoppingItem] = []
    seen: set[int] = set()

    # windows when the cleaner is at the shop
    windows: list[tuple[datetime, datetime, Visit]] = []
    for m in messages:
        if m.author == cleaner and m.has_text and store_re.search(norm(m.text)) and \
                re.search(r"arriv|sono al|sto andando|vado|devo andare", norm(m.text)):
            v = by_date.get(m.date)
            if v:
                windows.append((m.timestamp - timedelta(minutes=5), m.timestamp + timedelta(minutes=45), v))

    def store_of(v: Visit | None) -> str:
        return ", ".join(sorted(v.stores)) if v and v.stores else ""

    def add(m: Message, v: Visit | None, source: str, found):
        for name, qty, unit in found:
            items.append(ShoppingItem(v.date if v else None, m.timestamp, store_of(v), name, qty, unit,
                                      config.name(m.author), source, m.text, v.shopping_eur if v else None))
        seen.add(m.index)

    for t in tasks:
        if t.kind == "request" and "shopping" in t.categories:
            v = by_date.get(t.visit_date) if t.visit_date else None
            add(t.message, v, "household request", extract_items(t.text, config))

    for m in messages:
        if m.index in seen or m.author == cleaner or m.system:
            continue
        for a, b, v in windows:
            if a <= m.timestamp <= b:
                found = extract_items(m.text, config) if m.has_text else []
                if not found and m.media == "image":
                    q = re.match(r"^\s*(\d+)", m.text or "")
                    found = [("(item shown in photo)", float(q.group(1)) if q else None, "")]
                    add(m, v, "photo", found)
                else:
                    add(m, v, "household request (at the shop)", found)
                break

    # things the cleaner says she bought on her own initiative ("ho preso anche i guanti")
    for v in visits:
        for rep in v.reports:
            t = norm(rep.message.text)
            if re.search(r"\bho pres+o\b|\bho comprato\b", t):
                add(rep.message, v, "cleaner purchase note", extract_items(t, config))

    # trips with an amount but no listed items
    listed = {i.visit_date for i in items}
    for v in visits:
        if v.shopping_eur and v.date not in listed:
            rep = next((r for r in v.reports if r.shopping), None)
            ts = rep.message.timestamp if rep else datetime.combine(v.date, datetime.min.time())
            items.append(ShoppingItem(v.date, ts, store_of(v), "(items not listed in chat)", None, "",
                                      config.name(cleaner), "expense only", rep.message.text if rep else "", v.shopping_eur))
    items.sort(key=lambda i: i.timestamp)
    return items
