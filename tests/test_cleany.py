from datetime import date

import pytest

from cleany import Config, extract_chat, parse_text
from cleany.ledger import parse_report
from cleany.manual import split_instructions
from cleany.shopping import extract_items
from cleany.textutil import weekday_targets
from cleany.visits import is_arrival, planned_dates

CHAT = """\
[01/09/25, 06:00:00] Casa Test: ‎I messaggi e le chiamate sono crittografati end-to-end.
[01/09/25, 13:00:00] Pulizie: Da adesso chiedo 12€/h
[01/09/25, 18:00:00] Mamma: Domani per favore cambia le lenzuola del nostro letto
[01/09/25, 18:01:00] Pulizie: Ok
[02/09/25, 12:30:00] Pulizie: Tra poco arrivo
‎[02/09/25, 13:00:00] Pulizie: Buttare? ‎immagine omessa
[02/09/25, 13:01:00] Mamma: Si
[02/09/25, 16:00:00] Pulizie: Sono 36
[03/09/25, 21:00:00] Papa: Ciao domani passa da unes e prendi 2 finocchi e una verza.
Le verza va sbollentata 10 minuti
[03/09/25, 21:05:00] Pulizie: Ok
[04/09/25, 12:30:00] Pulizie: Tra poco arrivo
[04/09/25, 16:00:00] Pulizie: Al Unes -6
Sono 78, pagato 100, rimane 22 in più
[04/09/25, 16:02:00] Pulizie: Ho pulito i caloriferi <Questo messaggio è stato modificato>
[05/09/25, 12:30:00] Pulizie: Tra poco arrivo
[08/09/25, 11:00:00] Pulizie: Rimane 0
[08/09/25, 12:30:00] Pulizie: Tra poco arrivo
[08/09/25, 16:00:00] Pulizie: Rimane da dare 36
"""


@pytest.fixture(scope="module")
def ex():
    chat = parse_text(CHAT, title="Casa Test")
    return extract_chat(chat, Config(initial_rate=10))


def test_parser_multiline_media_edit():
    chat = parse_text(CHAT, title="Casa Test")
    assert chat.messages[0].system
    photo = [m for m in chat.messages if m.media == "image"][0]
    assert photo.text == "Buttare?"
    multi = [m for m in chat.messages if "sbollentata" in m.text][0]
    assert "\n" in multi.text and multi.author == "Papa"
    assert any(m.edited and m.text == "Ho pulito i caloriferi" for m in chat.messages)


def test_cleaner_detection(ex):
    assert ex.cleaner == "Pulizie"
    assert set(ex.household) == {"Mamma", "Papa"}


def test_visits_and_hours(ex):
    by = {v.date: v for v in ex.visits}
    assert sorted(by) == [date(2025, 9, d) for d in (2, 4, 5, 8)]
    assert by[date(2025, 9, 2)].hours is None          # opening balance: unknown
    v4 = by[date(2025, 9, 4)]
    # -36 -> pre-payment -78 with 6€ shopping => labour 36€ at 12€/h
    assert (v4.labor_eur, v4.hours, v4.shopping_eur, v4.paid_eur, v4.balance_after) == (36, 3, 6, 100, 22)
    # the 08/09 11:00 report is posted before arrival -> belongs to 05/09
    assert by[date(2025, 9, 5)].hours == pytest.approx(22 / 12, abs=0.01)
    assert by[date(2025, 9, 8)].hours == 3


def test_tasks_assignment(ex):
    by = {v.date: v for v in ex.visits}
    t2 = [t.text for t in by[date(2025, 9, 2)].tasks]
    assert any("lenzuola" in t for t in t2)
    assert any(t.startswith("Buttare") for t in t2)
    req = [t for t in by[date(2025, 9, 4)].tasks if t.role == "household"][0]
    assert "shopping" in req.categories and req.status in ("acknowledged", "done (reported)")
    done = [t for t in by[date(2025, 9, 4)].tasks if t.kind == "cleaner_done"]
    assert done and "radiators" in done[0].categories


def test_shopping(ex):
    items = {(i.item, i.quantity) for i in ex.shopping if i.visit_date == date(2025, 9, 4)}
    assert ("finocchi", 2) in items and ("verza", 1) in items


def test_parse_report_variants():
    stores = Config().stores
    r = parse_report("Rimane-361", stores)
    assert r.balance == 361 and r.notes
    r = parse_report("Al Unes -5\nSono 11, pagato 200, rimane 159", stores)
    assert r.shopping == 5 and r.pre_payment_balance == -11 and r.balance == 159
    assert "does not add up" in r.notes[0]
    r = parse_report("Ho perso lo scontrino ma sono 6€ più meno , ho preso anche detersivo, sono 94", stores)
    assert r.shopping == 6 and r.balance == -94
    r = parse_report("Giovedì mi sono dimenticata di contare anche Unes , sono più meno 7€", stores)
    assert r.balance is None and r.shopping == 7
    assert parse_report("Oggi ho fatto 4h\nSono 97", stores).reported_hours == 4
    assert parse_report("Ok grazie", stores) is None


def test_text_helpers():
    assert is_arrival("Tra poco arrivo") and is_arrival("Più meno 14.00")
    assert not is_arrival("Ciao, vengo martedì, giovedì e venerdì")
    sun = date(2025, 9, 21)  # Sunday
    assert planned_dates("Ciao , vengo domani , giovedì e venerdì", sun) == [date(2025, 9, 22), date(2025, 9, 25), date(2025, 9, 26)]
    assert planned_dates("Vengo giovedì non domani", sun) == [date(2025, 9, 25)]
    assert weekday_targets("Giovedì cambia le lenzuola", sun) == [date(2025, 9, 25)]
    assert extract_items("3 mazzi di cime di rapa e un iceberg", Config()) == [
        ("insalata iceberg", 1, ""), ("cime di rapa", 3, "mazzi")]
    assert split_instructions("Ciao Valeria. Per favore domani: - fare brodino - lavare iceberg") == [
        "Fare brodino", "Lavare iceberg"]


def test_extraordinary():
    from cleany.extraordinary import build_episodes, find_mentions, summarize
    text = """\
[02/03/26, 18:00:00] Mamma: Domani per favore pulisci i caloriferi e i davanzali
[03/03/26, 12:30:00] Pulizie: Tra poco arrivo
[03/03/26, 16:00:00] Pulizie: Ho pulito i caloriferi, mi è rimasto per la settimana prossima i davanzali
[03/03/26, 16:01:00] Pulizie: Sono 36
[03/03/26, 18:00:00] Mamma: C'è una lattuga da lavare in frigo
[05/05/26, 12:30:00] Pulizie: Tra poco arrivo
[05/05/26, 16:00:00] Pulizie: Oggi ho pulito i caloriferi
[05/05/26, 16:01:00] Pulizie: Sono 72
"""
    ex = extract_chat(parse_text(text, title="T"), Config(initial_rate=12))
    kinds = {(m.type_key, m.kind) for m in ex.extra_mentions if m.role == "cleaner"}
    assert ("radiators", "done") in kinds and ("window_sills", "partial/deferred") in kinds
    assert not any(m.type_key == "fridge" for m in ex.extra_mentions)       # lettuce in the fridge is not a clean-out
    rad = [s for s in ex.extra_summary if s.key == "radiators"][0]
    assert (rad.episodes, rad.done, rad.intervals) == (2, 2, [63])
    sills = [e for e in ex.extra_episodes if e.type_key == "window_sills"][0]
    assert sills.status.startswith("partially")
