"""Tunable vocabulary and settings. Defaults are for Italian-language chats;
override any field of :class:`Config` to adapt to another household/language."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    pattern: str

    @property
    def regex(self) -> re.Pattern:
        return re.compile(self.pattern, re.I)


VEG = (r"verdur|insalat|iceberg|lattuga|carot|radicch|finocch|zucchin|cime di rapa|\bcime\b|puntarell|scarola|"
       r"broccol|verza|cavol|fagiolin|sedano|bieta|patat|melanzan|zucca|cetriol|spinac|\brape\b|pomodor|cipoll")

DEFAULT_CATEGORIES: tuple[Category, ...] = (
    Category("shopping", "Shopping", r"\bunes\b|\bubers\b|\bpam\b|esselunga|\bcoop\b|carrefour|\blidl\b|supermercat|"
             r"\bcompr[aio]|comprare|scontrino|serve da comprare|passa(?:re|i)? da"),
    Category("supplies", "Supplies running out", r"serve da (?:comprare|portare)|\bè finit|sono finit|\bmanca|mancano|"
             r"non c'è più|da portare su"),
    Category("cooking", "Cooking / food prep", VEG + r"|bollir|bollent|sbollent|cuoc|cottura|cucinar|cucinal|cucinat|"
             r"minestron|lenticch|farro|brodin|pentol|scola|\briso\b|\bpasta\b|legum"),
    Category("laundry", "Laundry", r"lavatric|bucato|centrifug|asciugatric|ammorbident|\bstend|\bstes[oi]\b|\bpieg|"
             r"\bgradi\b|vestiti|magliett|pantalon|asciugaman|tovagli|strofinacc|programma"),
    Category("bed_linen", "Bed linen", r"lenzuol|\bletto\b|\bletti\b|lettino|copriletto|copri ?lenzuolo|federe|materass|piumon|coperte?\b"),
    Category("kitchen", "Kitchen / dishwasher / fridge", r"lavastovigli|affettatric|\bpiatti\b|fornell|\bcappa\b|\bfrigo|frigorifer|microonde|\bforno\b"),
    Category("bathroom", "Bathroom", r"\bbagn[oi]\b|vasca|doccia|viakal|calcar|lavandin|\bwc\b|sanitari|rubinett"),
    Category("windows", "Windows / screens / balcony", r"finestr|zanzarier|\bvetri|davanzal|tapparell|balcon|terrazz|persian"),
    Category("radiators", "Radiators", r"calorifer|termosifon"),
    Category("floors_dust", "Floors / dusting / furniture", r"paviment|polvere|aspirapolver|battiscopa|swiffer|\bscopa\b|"
             r"\bmobil[ei]\b|\bporte\b|divan|tappet|calcinacci"),
    Category("stains", "Stain removal", r"smacchi|candeggin|macchi[ae]\b"),
    Category("ironing", "Ironing", r"\bstir[aoi]|ferro da stiro"),
    Category("tidying", "Tidying / storage / cellar", r"cantina|soffitta|armadi|scaffal|scatol|valigi|nicchia|cassett|mensol|"
             r"riordin|sistema|mettil[ei]|\bscend|\bsalir|portare su|zain|borse\b|busta"),
    Category("waste", "Rubbish / throwing away", r"\bbutt|spazzatur|rifiut|plastica|bottigli|differenziat"),
    Category("deliveries", "Deliveries / keys / house", r"\bpacco|\bposta\b|corriere|citofon|\bchiav|allarme|idraulic"),
    Category("childcare", "Child-related", r"\bnicco|niccol|nicol[oò]|biberon|giochi|seggiolon|passeggin|fasciatoi|triciclo"),
)

# Canonical grocery name -> regex. Order matters (more specific first).
DEFAULT_GROCERIES: tuple[tuple[str, str], ...] = (
    ("insalata iceberg", r"(?:insalata |lattuga )?iceberg"),
    ("lattuga", r"lattug\w*"),
    ("cime di rapa", r"cime(?: di rapa)?"),
    ("cavolo nero", r"cavolo nero"),
    ("cavolfiore", r"cavolfior\w*"),
    ("cavolo", r"cavol[oi]\b"),
    ("verza", r"verz[ae]"),
    ("broccoli", r"broccol\w*"),
    ("radicchio", r"radicch\w*"),
    ("finocchi", r"finocch\w*"),
    ("zucchine", r"zucchin\w*"),
    ("carote", r"carot\w*"),
    ("puntarelle", r"puntarell\w*"),
    ("scarola", r"scarol\w*"),
    ("melanzane", r"melanzan\w*"),
    ("bieta", r"biet\w*"),
    ("sedano", r"sedan\w*"),
    ("patate", r"patat\w*"),
    ("cipolla", r"cipoll\w*"),
    ("fagiolini", r"fagiolin\w*"),
    ("zucca", r"zucca\b"),
    ("cetrioli", r"cetriol\w*"),
    ("spinaci", r"spinac\w*"),
    ("pomodori", r"pomodor\w*"),
    ("rape", r"\brape\b"),
    ("insalata", r"insalat\w*"),
    ("minestrone", r"minestron\w*"),
    ("lenticchie", r"lenticch\w*"),
    ("farro", r"farro"),
    ("latte", r"\blatte\b"),
    ("yogurt", r"yogurt"),
    ("pesto", r"pesto(?: senza aglio)?"),
    ("frutta", r"\bfrutta\b"),
    ("verdura (generic)", r"verdur\w*"),
    ("ammorbidente", r"ammorbident\w*(?: felce azzurra)?"),
    ("acido citrico", r"acido citrico"),
    ("detersivo pavimenti", r"detersivo per (?:i )?paviment\w*"),
    ("detersivo", r"detersiv\w*"),
    ("guanti", r"guanti"),
    ("swiffer", r"swiffer"),
    ("sacchetti plastica", r"sacchett\w*(?: per la plastica)?"),
    ("viakal", r"viakal"),
    ("carta igienica", r"carta igienica"),
    ("sapone", r"sapone"),
)

STORES = r"unes|ubers|pam|esselunga|coop|carrefour|lidl|conad|supermercato"


@dataclass
class Config:
    cleaner: str | None = None                  # auto-detected when None
    aliases: dict[str, str] = field(default_factory=dict)  # display name -> friendly name
    dayfirst: bool = True
    # Hourly rate schedule: list of (effective_from, eur/h). Parsed "chiedo N€/h" messages
    # are appended automatically; ``initial_rate`` None means "infer from the data".
    initial_rate: float | None = None
    rate_changes: list[tuple[date, float]] = field(default_factory=list)
    default_visit_hours: float = 3.0
    categories: tuple[Category, ...] = DEFAULT_CATEGORIES
    groceries: tuple[tuple[str, str], ...] = DEFAULT_GROCERIES
    stores: str = STORES
    max_days_to_next_visit: int = 10

    def name(self, author: str) -> str:
        return self.aliases.get(author, author)
