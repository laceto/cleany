"""Render visits + tasks as a self-contained HTML calendar and an iCalendar (.ics) file."""

from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone

from .textutil import WEEKDAY_NAMES_EN

PALETTE = {
    "shopping": "#c2410c", "supplies": "#ea580c", "cooking": "#15803d", "laundry": "#1d4ed8", "bed_linen": "#7c3aed",
    "kitchen": "#0e7490", "bathroom": "#0369a1", "windows": "#4d7c0f", "radiators": "#b45309",
    "floors_dust": "#57534e", "stains": "#be185d", "ironing": "#6d28d9", "tidying": "#a16207",
    "waste": "#4b5563", "deliveries": "#9333ea", "childcare": "#db2777", "other": "#6b7280",
}


def _payload(ex) -> dict:
    labels = {c.key: c.label for c in ex.config.categories} | {"other": "Other"}
    extra: dict = {}
    for e in ex.extra_episodes:
        extra.setdefault(e.date.isoformat(), []).append({"label": e.label, "status": e.status})
    visits = {}
    for v in ex.visits:
        visits[v.date.isoformat()] = {
            "hours": v.hours, "method": v.hours_method, "labour": v.labor_eur, "shopping": v.shopping_eur or 0,
            "paid": v.paid_eur or 0, "balance": v.balance_after, "arrival": v.arrival.strftime("%H:%M") if v.arrival else None,
            "stores": sorted(v.stores), "extra": extra.get(v.date.isoformat(), []), "planned": v.planned, "notes": list(dict.fromkeys(v.notes)),
            "tasks": [{"t": t.message.timestamp.strftime("%d/%m %H:%M"), "who": t.author, "role": t.role,
                       "kind": t.kind, "cats": t.categories, "status": t.status, "text": " ".join(t.text.split())}
                      for t in v.tasks],
        }
    missed = sorted(d.isoformat() for d in ex.planned if d.isoformat() not in visits)
    return {"title": ex.chat.title or "Cleaning calendar", "cleaner": ex.config.name(ex.cleaner),
            "visits": visits, "missed": missed, "labels": labels, "colors": PALETTE,
            "weekdays": WEEKDAY_NAMES_EN}


def render_html(ex) -> str:
    data = json.dumps(_payload(ex), ensure_ascii=False).replace("</", "<\\/")
    title = html.escape(f"Cleaning calendar — {ex.chat.title or ''}".strip(" —"))
    return _TEMPLATE.replace("__TITLE__", title).replace("__DATA__", data)


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    out, b = [], line.encode("utf-8")
    while len(b) > 74:
        cut = 74
        while (b[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(b[:cut].decode())
        b = b[cut:]
    out.append(b.decode())
    return "\r\n ".join(out)


def render_ics(ex) -> str:
    labels = {c.key: c.label for c in ex.config.categories} | {"other": "Other"}
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//cleany//cleaning visits//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{_ics_escape('Cleaning — ' + (ex.chat.title or ''))}"]
    for v in ex.visits:
        start = v.arrival or datetime.combine(v.date, datetime.min.time()).replace(hour=13)
        end = start + timedelta(hours=v.hours if v.hours and v.hours > 0 else ex.config.default_visit_hours)
        cats = sorted({labels.get(c, c) for t in v.tasks for c in t.categories})
        summary = f"Cleaning {v.hours:g}h" if v.hours else "Cleaning"
        desc = [f"Hours: {v.hours if v.hours is not None else '?'} ({v.hours_method})"]
        if v.shopping_eur:
            desc.append(f"Shopping: {v.shopping_eur:g}€ ({', '.join(sorted(v.stores))})")
        if v.balance_after is not None:
            desc.append(f"Balance after: {v.balance_after:g}€")
        if cats:
            desc.append("Areas: " + ", ".join(cats))
        desc += [f"- [{t.author}] {' '.join(t.text.split())} ({t.status})" for t in v.tasks]
        lines += ["BEGIN:VEVENT", f"UID:cleany-{v.date.isoformat()}@cleany", f"DTSTAMP:{now}",
                  f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}", f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}",
                  _fold("SUMMARY:" + _ics_escape(summary)), _fold("DESCRIPTION:" + _ics_escape("\n".join(desc))),
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f6f3;--card:#fff;--ink:#1c1917;--mute:#78716c;--line:#e7e5e4;--visit:#ecfdf5;--visit-b:#10b981;--miss:#fef2f2;--accent:#0f766e}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121212;--card:#1c1c1c;--ink:#f5f5f4;--mute:#a8a29e;--line:#2e2e2e;--visit:#0b2a22;--visit-b:#34d399;--miss:#2a1515;--accent:#5eead4}}
:root[data-theme="dark"]{--bg:#121212;--card:#1c1c1c;--ink:#f5f5f4;--mute:#a8a29e;--line:#2e2e2e;--visit:#0b2a22;--visit-b:#34d399;--miss:#2a1515;--accent:#5eead4}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{padding:20px 16px 8px;max-width:1200px;margin:auto}h1{font-size:22px;margin:0 0 4px}.sub{color:var(--mute)}
.stats{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px}
.stat b{display:block;font-size:18px}.legend{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.chip{display:inline-flex;align-items:center;gap:4px;border-radius:999px;padding:1px 8px;font-size:11px;color:#fff;cursor:pointer;border:2px solid transparent;user-select:none}
.chip.off{opacity:.3}.chip.sel{border-color:var(--ink)}
main{max-width:1200px;margin:auto;padding:0 16px 40px;display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}
.month{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
.month h2{font-size:15px;margin:0 0 2px;display:flex;justify-content:space-between}.month h2 span{color:var(--mute);font-weight:400;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(7,1fr);gap:3px;margin-top:8px}.wd{font-size:10px;color:var(--mute);text-align:center}
.day{min-height:52px;border-radius:6px;padding:3px;font-size:11px;border:1px solid transparent;position:relative}
.day .n{color:var(--mute)}.day.v{background:var(--visit);border-color:var(--visit-b);cursor:pointer}.day.v .n{color:var(--ink);font-weight:600}
.day.miss{background:var(--miss);border:1px dashed #ef4444}.day.dim{opacity:.25}.day.cur{outline:2px solid var(--accent)}
.h{font-weight:600;font-size:11px}.dots{display:flex;flex-wrap:wrap;gap:2px;margin-top:2px}.dot{width:7px;height:7px;border-radius:50%}
.cart{position:absolute;top:2px;right:3px;font-size:10px}.star{position:absolute;bottom:2px;right:3px;font-size:11px;color:#d97706}
.xt{margin:6px 0;padding:6px 8px;border-radius:8px;background:rgba(217,119,6,.12);font-size:12px}
#panel{position:fixed;right:16px;bottom:16px;width:min(460px,calc(100vw - 32px));max-height:70vh;overflow:auto;background:var(--card);border:1px solid var(--line);border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.2);padding:14px;display:none}
#panel h3{margin:0 0 6px}#panel .x{float:right;cursor:pointer;border:0;background:none;color:var(--ink);font-size:18px}
.task{border-top:1px solid var(--line);padding:6px 0}.task .meta{font-size:11px;color:var(--mute)}.st{font-size:10px;border:1px solid var(--line);border-radius:4px;padding:0 4px;margin-left:4px}
.note{font-size:12px;color:#b45309}
</style></head><body>
<header><h1 id="t"></h1><div class="sub" id="s"></div><div class="stats" id="stats"></div>
<div class="sub">Click a green day for details · red dashed = announced by the cleaner but no visit found · 🛒 = shopping trip · ★ = extraordinary cleaning · click a category to highlight it</div>
<div class="legend" id="legend"></div></header>
<main id="cal"></main>
<div id="panel"></div>
<script>
const D=__DATA__;
const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=x=>x==null?'?':(Math.round(x*100)/100).toString();
let sel=null;
$('#t').textContent='Cleaning calendar — '+D.title;
const days=Object.keys(D.visits).sort();
$('#s').textContent=`${D.cleaner} · ${days[0]} → ${days[days.length-1]}`;
const totH=days.reduce((a,d)=>a+(D.visits[d].hours>0?D.visits[d].hours:0),0);
const totL=days.reduce((a,d)=>a+(D.visits[d].labour>0?D.visits[d].labour:0),0);
const totS=days.reduce((a,d)=>a+(D.visits[d].shopping||0),0);
const totP=days.reduce((a,d)=>a+(D.visits[d].paid||0),0);
$('#stats').innerHTML=[['Visits',days.length],['Hours',fmt(totH)],['Labour €',fmt(totL)],['Shopping €',fmt(totS)],['Paid €',fmt(totP)],
 ['Tasks',days.reduce((a,d)=>a+D.visits[d].tasks.length,0)]].map(([k,v])=>`<div class="stat"><b>${v}</b>${k}</div>`).join('');
const used=new Set();days.forEach(d=>D.visits[d].tasks.forEach(t=>t.cats.forEach(c=>used.add(c))));
$('#legend').innerHTML=Object.keys(D.labels).filter(k=>used.has(k)).map(k=>`<span class="chip" data-c="${k}" style="background:${D.colors[k]}">${esc(D.labels[k])}</span>`).join('');
document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{sel=sel===c.dataset.c?null:c.dataset.c;
 document.querySelectorAll('.chip').forEach(x=>{x.classList.toggle('sel',x.dataset.c===sel);x.classList.toggle('off',!!sel&&x.dataset.c!==sel)});draw();});
function draw(){
 const first=new Date(days[0]+'T00:00'),last=new Date(days[days.length-1]+'T00:00');
 const miss=new Set(D.missed);let html='';
 for(let m=new Date(first.getFullYear(),first.getMonth(),1);m<=last;m=new Date(m.getFullYear(),m.getMonth()+1,1)){
  const y=m.getFullYear(),mo=m.getMonth(),n=new Date(y,mo+1,0).getDate(),off=(m.getDay()+6)%7;
  const key=d=>`${y}-${String(mo+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
  let vs=0,hs=0,cells='';
  for(let i=0;i<off;i++)cells+='<div></div>';
  for(let d=1;d<=n;d++){const k=key(d),v=D.visits[k];
   if(v){vs++;hs+=v.hours>0?v.hours:0;const cats=[...new Set(v.tasks.flatMap(t=>t.cats))];
    const dim=sel&&!cats.includes(sel)?' dim':'';
    cells+=`<div class="day v${dim}" data-k="${k}" title="${esc(cats.map(c=>D.labels[c]).join(', '))}"><span class="n">${d}</span>${v.shopping?'<span class="cart">🛒</span>':''}${v.extra.length?'<span class="star" title="'+esc(v.extra.map(x=>x.label).join(', '))+'">★</span>':''}
     <div class="h">${v.hours!=null?fmt(v.hours)+'h':'?h'}</div><div class="dots">${cats.map(c=>`<i class="dot" style="background:${D.colors[c]}"></i>`).join('')}</div></div>`;}
   else cells+=`<div class="day${miss.has(k)?' miss':''}"><span class="n">${d}</span></div>`;}
  html+=`<section class="month"><h2>${m.toLocaleString('en',{month:'long',year:'numeric'})}<span>${vs} visits · ${fmt(hs)} h</span></h2>
   <div class="grid">${D.weekdays.map(w=>`<div class="wd">${w}</div>`).join('')}${cells}</div></section>`;}
 $('#cal').innerHTML=html;
 document.querySelectorAll('.day.v').forEach(e=>e.onclick=()=>show(e.dataset.k));}
function show(k){const v=D.visits[k];document.querySelectorAll('.day.cur').forEach(e=>e.classList.remove('cur'));
 document.querySelector(`.day[data-k="${k}"]`)?.classList.add('cur');
 const p=$('#panel');p.style.display='block';
 const dt=new Date(k+'T00:00').toLocaleDateString('en',{weekday:'long',day:'numeric',month:'long',year:'numeric'});
 p.innerHTML=`<button class="x" aria-label="close">×</button><h3>${dt}</h3>
 <div>${v.arrival?'Arrival msg '+v.arrival+' · ':''}<b>${fmt(v.hours)} h</b> (${esc(v.method)})${v.labour!=null?' · labour '+fmt(v.labour)+'€':''}
 ${v.shopping?' · shopping '+fmt(v.shopping)+'€ '+esc(v.stores.join(', ')):''}${v.paid?' · paid '+fmt(v.paid)+'€':''}
 ${v.balance!=null?' · balance '+(v.balance>=0?'credit '+fmt(v.balance):'owed '+fmt(-v.balance))+'€':''}</div>
 ${v.extra.length?'<div class="xt">★ Extraordinary: '+v.extra.map(x=>esc(x.label)+' <i>('+esc(x.status)+')</i>').join(' · ')+'</div>':''}
 ${v.notes.map(n=>`<div class="note">⚠ ${esc(n)}</div>`).join('')}
 ${v.tasks.map(t=>`<div class="task"><div class="meta">${esc(t.t)} · ${esc(t.who)} · ${esc(t.kind.replace('_',' '))}<span class="st">${esc(t.status)}</span>
  ${t.cats.map(c=>`<span class="chip" style="background:${D.colors[c]}">${esc(D.labels[c])}</span>`).join(' ')}</div>${esc(t.text)}</div>`).join('')||'<div class="sub">No task messages for this visit.</div>'}`;
 p.querySelector('.x').onclick=()=>{p.style.display='none'};}
draw();
</script></body></html>
"""
