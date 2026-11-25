"""One-call extraction: chat export -> visits, ledger, tasks, shopping, manual."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .config import Config
from .extraordinary import Episode, Mention, TypeSummary, build_episodes, find_mentions, summarize
from .manual import ManualEntry, build_manual
from .parser import Chat, parse_export
from .shopping import ShoppingItem, build_shopping
from .tasks import Task, assign_tasks
from .visits import LedgerEntry, Visit, build_visits, detect_cleaner


@dataclass
class Extraction:
    chat: Chat
    cleaner: str
    household: list[str]
    visits: list[Visit]
    ledger: list[LedgerEntry]
    tasks: list[Task]
    shopping: list[ShoppingItem]
    manual: list[ManualEntry]
    planned: set[date] = field(default_factory=set)
    config: Config = field(default_factory=Config)
    extra_mentions: list[Mention] = field(default_factory=list)
    extra_episodes: list[Episode] = field(default_factory=list)
    extra_summary: list[TypeSummary] = field(default_factory=list)


def extract_chat(chat: Chat, config: Config | None = None) -> Extraction:
    config = config or Config()
    msgs = chat.messages
    cleaner = detect_cleaner(msgs, config)
    household = [p for p in chat.participants if p != cleaner]
    visits, ledger, planned = build_visits(msgs, cleaner, config)
    tasks = assign_tasks(msgs, visits, cleaner, config)
    shopping = build_shopping(msgs, visits, tasks, cleaner, config)
    manual = build_manual(msgs, cleaner, config)
    mentions = find_mentions(msgs, visits, cleaner, config)
    episodes = build_episodes(mentions)
    end = max(m.date for m in msgs)
    return Extraction(chat, cleaner, household, visits, ledger, tasks, shopping, manual, planned, config,
                      mentions, episodes, summarize(episodes, end))


def extract(path: str | Path, config: Config | None = None) -> Extraction:
    config = config or Config()
    return extract_chat(parse_export(path, dayfirst=config.dayfirst), config)
