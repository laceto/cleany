"""House manual: recurring, procedural instructions given to the cleaner, de-duplicated."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher

from .config import Config
from .parser import Message
from .textutil import categorize, norm

PROCEDURAL = re.compile(
    r"\d+\s*(?:gradi|°|minuti|min\b|giri|cm\b|h\b|ore\b)|programma|cucchiai|\bsempre\b|\bmai\b|"
    r"non (?:mettere|usare|lavare|buttare|tagliare|far)|attent|ricordat|la prossima volta|quando vai via|"
    r"solo quando|senza tagliare|per ammorbidente|in modo|prima di (?:avviare|uscire|mettere|arrivare)|"
    r"acqua|bollir|sbollent|lascia(?:re)? .*apert|piegal|mettil[ei]|si fa|va lavat|vanno"
)


@dataclass
class ManualEntry:
    category: str
    instruction: str
    times_given: int
    first_date: date
    last_date: date
    given_by: set[str] = field(default_factory=set)
    variants: list[str] = field(default_factory=list)
    kind: str = "instruction"     # instruction | Q&A


_GREETING = re.compile(r"^(?:ciao|buongiorno|buonasera)?\s*(?:valeria)?[,!.]?\s*(?:per favore|cortesemente)?\s*"
                       r"(?:oggi|domani)?\s*(?:ci sarebbero da fare|ci sarebbe)?\s*:?\s*", re.I)


def split_instructions(text: str) -> list[str]:
    """Split a multi-part message ("Ciao, per favore domani: - X - Y. Z") into single instructions."""
    parts = re.split(r"\n+|\s+-\s+|\s*\u2060?-\s+(?=\w)|(?<=[.!?])\s+(?=[A-ZÀ-Ú])", text.replace("\u2060", ""))
    out = []
    for p in parts:
        p = _GREETING.sub("", p.strip(" -•\t")).strip()
        p = re.sub(r"\s*grazie( mille)?[.!]*$", "", p, flags=re.I).strip()
        if len(p) >= 8:
            out.append(p[0].upper() + p[1:])
    return out


def _key(s: str) -> str:
    return re.sub(r"[^a-zàèéìòù0-9 ]", "", norm(s))


def build_manual(messages: list[Message], cleaner: str, config: Config, threshold: float = 0.55) -> list[ManualEntry]:
    labels = {c.key: c.label for c in config.categories}
    candidates: list[tuple[str, str, Message, str]] = []   # (category, text, msg, kind)

    for i, m in enumerate(messages):
        if m.system or not m.has_text:
            continue
        t = norm(m.text)
        cats = categorize(m.text, config.categories)
        if m.author != cleaner and cats:
            for seg in split_instructions(m.text):
                scats = [c for c in categorize(seg, config.categories) if c not in ("shopping", "supplies")]
                if scats and PROCEDURAL.search(norm(seg)):
                    candidates.append((scats[0], seg, m, "instruction"))
        # cleaner procedural question answered by the household
        if m.author == cleaner and "?" in m.text and cats and PROCEDURAL.search(t) and cats[0] != "shopping":
            for x in messages[i + 1:i + 6]:
                if x.author != cleaner and x.has_text and x.timestamp - m.timestamp < timedelta(minutes=90):
                    candidates.append((cats[0], f"Q: {m.text.strip()} — A: {x.text.strip()}", x, "Q&A"))
                    break

    entries: list[tuple[ManualEntry, str]] = []
    for cat, text, m, kind in candidates:
        k = _key(text)
        for e, ek in entries:
            if e.category == labels[cat] and e.kind == kind and SequenceMatcher(None, ek, k).ratio() >= threshold:
                e.times_given += 1
                e.last_date = max(e.last_date, m.date)
                e.given_by.add(config.name(m.author))
                if text not in e.variants and len(e.variants) < 4:
                    e.variants.append(text)
                if len(text) > len(e.instruction):   # keep the most detailed wording
                    e.instruction = text
                break
        else:
            entries.append((ManualEntry(labels[cat], text, 1, m.date, m.date, {config.name(m.author)}, [text], kind), k))
    out = [e for e, _ in entries]
    order = {c.label: i for i, c in enumerate(config.categories)}
    out.sort(key=lambda e: (order.get(e.category, 99), -e.times_given, e.first_date))
    return out
