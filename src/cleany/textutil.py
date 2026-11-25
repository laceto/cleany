"""Small Italian text helpers shared by the extractors."""

from __future__ import annotations

import re
from datetime import date, timedelta

from .config import Category

WEEKDAYS = {
    "lunedì": 0, "lunedi": 0, "martedì": 1, "martedi": 1, "mercoledì": 2, "mercoledi": 2,
    "giovedì": 3, "giovedi": 3, "venerdì": 4, "venerdi": 4, "sabato": 5, "domenica": 6,
}
WEEKDAY_NAMES_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
WEEKDAY_NAMES_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_WD_RE = re.compile(r"\b(non\s+)?(" + "|".join(WEEKDAYS) + r")\b(?:\s+(\d{1,2})\b)?")

_ACK = re.compile(r"^(ok+|okay|va bene|s[iì]+|s[iì] s[iì]|certo|perfetto|d'accordo|benissimo|grazie|ok,? grazie|"
                  r"va bene,? grazie|ok ?👍|👍|yes)[\s.!,]*$", re.I)


def norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("`", "'")
    return re.sub(r"\s+", " ", s).strip()


def is_ack(text: str) -> bool:
    return bool(_ACK.match(norm(text)))


def categorize(text: str, categories: tuple[Category, ...]) -> list[str]:
    t = norm(text)
    return [c.key for c in categories if c.regex.search(t)]


def weekday_targets(text: str, ref: date) -> list[date]:
    """Dates referenced by weekday names / 'oggi' / 'domani' relative to ``ref``.
    Weekday names resolve to the next occurrence (today counts only via 'oggi').
    'martedì 31' resolves to day 31 when it matches. Negated mentions ('non domani') are skipped."""
    t = norm(text)
    out: list[date] = []
    for m in re.finditer(r"\b(non\s+)?(oggi|domani|dopodomani)\b", t):
        if m.group(1):
            continue
        out.append(ref + timedelta(days={"oggi": 0, "domani": 1, "dopodomani": 2}[m.group(2)]))
    for m in _WD_RE.finditer(t):
        if m.group(1):
            continue
        wd = WEEKDAYS[m.group(2)]
        delta = (wd - ref.weekday()) % 7 or 7
        d = ref + timedelta(days=delta)
        if m.group(3):  # explicit day of month
            dom = int(m.group(3))
            for k in range(0, 60):
                cand = ref + timedelta(days=k)
                if cand.day == dom and cand.weekday() == wd:
                    d = cand
                    break
        out.append(d)
    return sorted(set(out))


def parse_amount(s: str) -> float:
    return float(s.replace(",", "."))


def shorten(s: str, n: int = 140) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"
