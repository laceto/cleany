"""Parse WhatsApp chat exports (iOS ``[dd/mm/yy, hh:mm:ss] Name: text`` and
Android ``dd/mm/yy, hh:mm - Name: text`` formats), from a ``.txt`` or ``.zip``."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Invisible marks WhatsApp sprinkles into exports (LRM, isolates around @mentions, BOM).
_INVISIBLE = dict.fromkeys(map(ord, "‎‏⁨⁩‪‬﻿"))

_IOS = re.compile(
    r"^\[(?P<d>\d{1,2}[/.]\d{1,2}[/.]\d{2,4}),?\s+(?P<t>\d{1,2}[:.]\d{2}(?:[:.]\d{2})?)\]\s+"
    r"(?P<a>[^:]+?):\s?(?P<x>.*)$"
)
_ANDROID = re.compile(
    r"^(?P<d>\d{1,2}[/.]\d{1,2}[/.]\d{2,4}),?\s+(?P<t>\d{1,2}[:.]\d{2})\s+-\s+"
    r"(?P<a>[^:]+?):\s?(?P<x>.*)$"
)

MEDIA_MARKERS = {
    "image": ("immagine omessa", "image omitted", "<media omessi>", "<media omitted>"),
    "video": ("video omesso", "video omitted"),
    "audio": ("audio omesso", "audio omitted"),
    "document": ("documento omesso", "document omitted"),
    "sticker": ("sticker omesso", "sticker omitted"),
    "gif": ("gif omessa", "gif omitted"),
}
_EDITED = re.compile(r"<\s*(questo messaggio è stato modificato|this message was edited)\s*>", re.I)
_DELETED = re.compile(r"^(questo messaggio è stato eliminato|this message was deleted|hai eliminato questo messaggio)", re.I)
_SYSTEM_HINTS = ("crittografati end-to-end", "end-to-end encrypted")


@dataclass
class Message:
    index: int
    timestamp: datetime
    author: str
    text: str                       # cleaned text (markers removed)
    raw: str                        # original text
    media: str | None = None        # image/video/... when an attachment was omitted
    edited: bool = False
    deleted: bool = False
    system: bool = False
    mentions: list[str] = field(default_factory=list)

    @property
    def date(self):
        return self.timestamp.date()

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())


@dataclass
class Chat:
    title: str | None
    messages: list[Message]

    @property
    def participants(self) -> list[str]:
        seen: dict[str, int] = {}
        for m in self.messages:
            if not m.system:
                seen[m.author] = seen.get(m.author, 0) + 1
        return sorted(seen, key=lambda a: -seen[a])


def _parse_dt(d: str, t: str, dayfirst: bool) -> datetime:
    parts = re.split(r"[/.]", d)
    a, b, y = (int(p) for p in parts)
    day, month = (a, b) if dayfirst else (b, a)
    if y < 100:
        y += 2000
    tp = [int(p) for p in re.split(r"[:.]", t)]
    while len(tp) < 3:
        tp.append(0)
    return datetime(y, month, day, *tp)


def _clean(text: str) -> tuple[str, str | None, bool, bool]:
    media = None
    low = text.lower()
    for kind, markers in MEDIA_MARKERS.items():
        for mk in markers:
            if mk in low:
                media = kind
                i = low.index(mk)
                text = (text[:i] + text[i + len(mk):])
                low = text.lower()
    edited = bool(_EDITED.search(text))
    text = _EDITED.sub("", text)
    deleted = bool(_DELETED.match(text.strip()))
    return text.strip(), media, edited, deleted


def read_export_text(path: str | Path) -> tuple[str, str | None]:
    """Return (chat text, chat title) from a .txt or a WhatsApp .zip export."""
    path = Path(path)
    title = None
    m = re.match(r"WhatsApp Chat (?:-|with|con)\s*(.+)$", path.stem, re.I)
    if m:
        title = m.group(1).strip()
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".txt")]
            if not names:
                raise ValueError(f"No .txt chat file inside {path}")
            name = "_chat.txt" if "_chat.txt" in names else names[0]
            data = zf.read(name)
    else:
        data = path.read_bytes()
    return data.decode("utf-8-sig", errors="replace"), title


def parse_text(text: str, title: str | None = None, dayfirst: bool = True) -> Chat:
    text = text.translate(_INVISIBLE).replace("\r\n", "\n")
    msgs: list[Message] = []
    cur: dict | None = None

    def flush():
        if cur is None:
            return
        raw = "\n".join(cur["lines"])
        clean, media, edited, deleted = _clean(raw)
        mentions = re.findall(r"@([^\s@,.!?]+(?: [A-Z][^\s@,.!?]+)?)", raw)
        msgs.append(Message(len(msgs), cur["ts"], cur["author"], clean, raw, media, edited, deleted, False, mentions))

    for line in text.split("\n"):
        m = _IOS.match(line) or _ANDROID.match(line)
        if m:
            try:
                ts = _parse_dt(m["d"], m["t"], dayfirst)
            except ValueError:
                m = None
        if m:
            flush()
            cur = {"ts": ts, "author": m["a"].strip(), "lines": [m["x"]]}
        elif cur is not None:
            cur["lines"].append(line)
    flush()

    # System messages: authored by the chat itself (title) or containing system hints.
    for msg in msgs:
        low = msg.text.lower()
        if (title and msg.author == title) or any(h in low for h in _SYSTEM_HINTS):
            msg.system = True
            if title is None:
                title = msg.author
    if title:
        for msg in msgs:
            if msg.author == title:
                msg.system = True
    return Chat(title, msgs)


def parse_export(path: str | Path, dayfirst: bool = True) -> Chat:
    text, title = read_export_text(path)
    return parse_text(text, title, dayfirst)
