"""Parse the cleaner's running-balance messages and reconstruct a ledger.

Balance convention used throughout (euros):
    balance > 0  -> credit: the household has prepaid, the cleaner holds money ("Rimane 86")
    balance < 0  -> debt:   the household owes the cleaner ("Sono 94", "rimane da dare 36")

Between two reports:  labour = prev_balance + paid - shopping - new_balance
and hours = labour / hourly_rate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import Config
from .parser import Message
from .textutil import norm, parse_amount

NUM = r"(\d+(?:[.,]\d+)?)"


@dataclass
class BalanceReport:
    message: Message
    balance: float | None            # see module docstring for sign
    pre_payment_balance: float | None = None   # "Sono 134, pagato 220, rimane 86" -> -134
    paid: float = 0.0
    shopping: float = 0.0
    store: str | None = None
    reported_hours: float | None = None
    extra_half_hour: bool = False
    refers_to_yesterday: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def is_balance(self) -> bool:
        return self.balance is not None


@dataclass
class RateChange:
    message: Message
    rate: float


@dataclass
class CashLeft:
    message: Message
    amount: float | None


def parse_rate_change(text: str) -> float | None:
    m = re.search(r"(?:chiedo|prendo|costa|tariffa(?: è)?)\s+" + NUM + r"\s*(?:€|euro)?\s*(?:/|all'|l')\s*(?:h|ora)\b", norm(text))
    return parse_amount(m.group(1)) if m else None


def parse_report(text: str, stores: str) -> BalanceReport | None:
    """Parse one cleaner message. Returns None when it carries no money information."""
    t = norm(text)
    rep = BalanceReport(message=None, balance=None)  # type: ignore[arg-type]

    m = re.search(r"pagat[oi]\s+" + NUM, t)
    if m:
        rep.paid = parse_amount(m.group(1))

    m = re.search(r"rimane\s+da\s+dare\s+" + NUM, t)
    if m:
        rep.balance = -parse_amount(m.group(1))
    else:
        m = re.search(r"rimane\s*(-)?\s*" + NUM + r"(\s*in più)?", t)
        if m:
            rep.balance = parse_amount(m.group(2))
            if m.group(1):
                rep.notes.append("minus sign after 'rimane' treated as a typo (credit)")
        else:
            # "Sono 94" = amount owed; ignore "sono 6€" (an expense) and "sono più meno 7€".
            ms = [x for x in re.finditer(r"\bsono\s+" + NUM + r"(?!\s*(?:€|euro|h\b|ore\b|min))", t)]
            if ms:
                rep.balance = -parse_amount(ms[-1].group(1))

    if rep.paid and rep.balance is not None:
        m = re.search(r"\b(sono|oggi)\s+(-)?" + NUM + r"(?!\s*(?:€|euro|h\b))[^\n]*?pagat", t)
        if m and (m.group(1) == "sono" or m.group(2)):
            rep.pre_payment_balance = -parse_amount(m.group(3))
            if abs(rep.pre_payment_balance + rep.paid - rep.balance) > 0.01:
                rep.notes.append(f"cleaner's arithmetic does not add up: {rep.pre_payment_balance:g} + {rep.paid:g} paid "
                                 f"= {rep.pre_payment_balance + rep.paid:g}, but she wrote {rep.balance:g} "
                                 f"(difference {rep.balance - rep.pre_payment_balance - rep.paid:+g}€)")

    store_m = re.search(r"\b(" + stores + r")\b", t)
    if store_m or "scontrino" in t:
        rep.store = store_m.group(1).capitalize() if store_m else None
        if rep.store == "Ubers":
            rep.store = "Unes"
        amt = None
        if store_m:
            m = re.search(r"\b" + re.escape(store_m.group(1)) + r"\b\s*(?:più meno|piu meno|circa)?\s*-?\s*" + NUM, t)
            if m:
                amt = m.group(1)
        if amt is None:
            m = re.search(NUM + r"\s*(?:€|euro)", t)
            if m:
                amt = m.group(1)
        if amt is not None:
            rep.shopping = parse_amount(amt)
        if "scontrino" in t:
            rep.notes.append("receipt lost, amount approximate")

    m = re.search(r"oggi\s+(?:ho fatto\s+)?" + NUM + r"\s*h\b", t)
    if m:
        rep.reported_hours = parse_amount(m.group(1))
    if re.search(r"mezz'?\s*ora in più", t):
        rep.extra_half_hour = True
    if re.search(r"\bieri\b", t):
        rep.refers_to_yesterday = True
    if "dimenticat" in t and rep.balance is None:
        rep.notes.append("late expense the cleaner forgot to count earlier")

    if rep.balance is None and not rep.shopping and not rep.paid:
        return None
    return rep


def parse_cash_left(text: str) -> CashLeft | None:
    """Household messages telling the cleaner where money was left."""
    t = norm(text)
    if not re.search(r"soldi|€|euro", t):
        return None
    if not re.search(r"trov|per te|lasciat|cucina|mensola|ha i soldi|ci sono", t):
        return None
    m = re.search(NUM + r"\s*(?:€|euro)", t)
    return CashLeft(message=None, amount=parse_amount(m.group(1)) if m else None)  # type: ignore[arg-type]


def collect_money_messages(messages: list[Message], cleaner: str, config: Config):
    reports: list[BalanceReport] = []
    rates: list[RateChange] = []
    cash: list[CashLeft] = []
    for msg in messages:
        if msg.system or not msg.has_text:
            continue
        if msg.author == cleaner:
            r = parse_rate_change(msg.text)
            if r:
                rates.append(RateChange(msg, r))
                continue
            rep = parse_report(msg.text, config.stores)
            if rep:
                rep.message = msg
                reports.append(rep)
        else:
            c = parse_cash_left(msg.text)
            if c:
                c.message = msg
                cash.append(c)
    return reports, rates, cash
