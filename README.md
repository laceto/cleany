# cleany

Turn a WhatsApp chat with your house cleaner into structured data: **which days the cleaner came, how many hours,
what was done, what was bought, what was paid**, plus a **house manual** of recurring instructions and a
**calendar** (HTML + iCalendar).

Works on the raw WhatsApp export (`.zip` or `_chat.txt`, iOS or Android format). Defaults are tuned for
Italian-language chats, and all vocabulary is configurable.

## Install & run

```bash
pip install -e .            # or: pip install -e ".[test]" && pytest
cleany "WhatsApp Chat - Casa Luigi e Fabrizia.zip" -o output/
```

Options: `--cleaner NAME` (otherwise auto-detected), `--alias "Display name=Friendly name"` (repeatable),
`--initial-rate 10` (€/h before the first rate change found in the chat; otherwise inferred),
`--rate 2026-01-01=13` (extra rate change), `--monthfirst` (US date order).

```python
from cleany import extract, write_all, Config

ex = extract("export.zip", Config(aliases={"Luis": "Luigi"}))
for v in ex.visits:
    print(v.date, v.hours, [t.text for t in v.tasks])
write_all(ex, "output/")
```

## Outputs (`output/`)

| file | one row per | key columns |
|---|---|---|
| `visits.csv` | cleaner visit | date, weekday, hours, how hours were derived, rate, labour €, shopping €, paid €, balance after, task categories, task summary, notes/anomalies |
| `tasks.csv` | task message | visit_date, author, role (household/cleaner), kind (`request`, `cleaner_done`, `cleaner_question`, `cleaner_deferred`, `cleaner_note`), categories, status, text, replies |
| `ledger.csv` | money event | balance reports, payments, shopping expenses, rate changes, cash left by the household; derived labour/hours per step; arithmetic checks |
| `shopping.csv` | requested grocery item | visit_date, store, item, quantity, unit, requested_by, source, trip total € |
| `house_manual.csv` / `.md` | recurring instruction | category, instruction, times given, first/last date, other wordings; includes Q&A pairs |
| `extraordinary_summary.csv` | extraordinary task type | times, done / partial / requested-only, first & last date, days between occurrences (list, mean, median, min, max), days since last, next due estimate |
| `extraordinary_tasks.csv` | occurrence (episode) | date, task, status, days since previous same task, who asked, evidence messages |
| `extraordinary_mentions.csv` | message mentioning such a job | visit_date, task, author, kind (request / done / partial/deferred / remark) |
| `calendar.html` | — | self-contained month calendar; click a day for hours, money and all tasks; filter by category |
| `calendar.ics` | visit | import into Google/Apple Calendar |

## How it works

* **Parsing** (`parser.py`): handles multi-line messages, omitted media, edited/deleted markers and the invisible
  Unicode marks WhatsApp inserts.
* **Visits** (`visits.py`): a visit day is one with an arrival message ("Tra poco arrivo", "Più meno 14.00", …)
  or a balance report. A report posted *before* that day's arrival, or one that says "ieri", is attributed to the
  previous visit. An ETA sent after 19:00 counts for the next day. Announcements such as "vengo martedì, giovedì
  e venerdì" give the *planned* days, and newer announcements override older ones.
* **Ledger** (`ledger.py`, `visits.py`): the cleaner keeps a running balance in her messages:
  * `Sono N` / `rimane da dare N` means N is owed to her (balance −N).
  * `Rimane N (in più)` means the household has N in credit (balance +N).
  * `pagato N` is a payment, and `Al Unes -N` is shopping she paid for.

  Labour per step = `prev_balance + paid − shopping − new_balance`, and hours = labour ÷ hourly rate. Rate changes
  ("Da adesso chiedo 12€/h") are detected. The rate before the first change is inferred as the one that makes
  hours whole half-hours. When one report covers several visits, the labour is split evenly between them. Typos
  and internal arithmetic errors in the cleaner's messages are flagged in `notes`.
* **Tasks** (`tasks.py`): household messages that match a category (laundry, bed linen, cooking, shopping, …) are
  attached to the next visit that hasn't ended. A day named at the start of the message ("Domani…", "Giovedì…")
  overrides that. The cleaner's own messages during a visit become questions, done-reports or notes. A request's
  status comes from the cleaner's reply (ack, "ho fatto…", "farò domani").
* **Shopping** (`shopping.py`): grocery vocabulary plus quantities ("3 mazzi di cime di rapa") from shopping
  requests and from messages exchanged while the cleaner is at the shop.
* **Extraordinary tasks** (`extraordinary.py`): non-routine deep-cleaning jobs (mosquito screens, windows, sills,
  radiators, dishwasher filter, tops of doors and wardrobes, inside cupboards, skirting boards, sofas, rugs,
  balcony, tiles, fridge, …). Each mention is classified as a request, a done report, partial/deferred or a remark,
  with clause-level parsing ("Ho fatto i vetri, zanzariere… farò i battiscopa"). Mentions of the same job within
  14 days are merged into one *episode*, and intervals are measured between episodes. They're marked ★ in the
  calendar.
* **House manual** (`manual.py`): splits messages into single instructions and keeps the procedural ones
  (temperatures, minutes, programmes, "attenta", "sempre", …). Near-duplicates are merged and counted.

Everything is rule-based and deterministic (no network, no LLM). Adapt it by passing a `Config` with your own
`categories`, `groceries`, `stores` or rate schedule.

## Limitations

The output is inferred from chat text. Tasks the household asked for are not proof the work was done; check the
`status` column. Visits with no message at all are invisible, and the hours for the last visit are unknown until
the next balance report.
