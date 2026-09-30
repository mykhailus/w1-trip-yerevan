#!/usr/bin/env python3
"""Stage 2: convert Maxim's Tbilisi data into the settle.py schema.

settle.py itself is not changed. Every manual edit is one numbered block below.

    python stage2/tbilisi/adapt.py <path to baramba/trip-settle-tbilisi/data.json> > stage2/tbilisi/data.json
"""
import json
import sys
from pathlib import Path

src = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out = {"people": src["people"], "base_currency": src["base_currency"]}

# 1. title: "trip" -> "title"
out["title"] = "Тбилиси, 3–6 сентября 2026 (набор baramba/trip-settle-tbilisi)"

# 2. rates: one field per currency pair -> rates[currency][date]
out["rates"] = {"GEL": {d: str(r) for d, r in src["rates_rub_per_gel"].items()}}

# 3. receipts: "payer" -> "paid_by"
# 4. receipts: "source" + "also_mentioned" -> "messages" list
out["receipts"] = []
for r in src["receipts"]:
    msgs = [r["source"]] + ([r["also_mentioned"]] if r.get("also_mentioned") else [])
    out["receipts"].append({"id": r["id"], "date": r["date"], "paid_by": r["payer"],
                            "amount": r["amount"], "currency": r["currency"], "what": r["what"],
                            "for": r["for"], "messages": msgs})

# 5. refunds: "source" -> "messages" (other fields already match)
out["refunds"] = [{"id": v["id"], "date": v["date"], "to": v["to"], "amount": v["amount"],
                   "currency": v["currency"], "receipt": v["receipt"], "messages": [v["source"]]}
                  for v in src["refunds"]]

# 6. disputed: who/what/action/source -> what/messages/why
out["disputed"] = [{"what": f"{s['who']}: {s['what']}", "messages": [s["source"]], "why": s["action"]}
                   for s in src["disputed"]]

# 7. control facts: facts.md is prose; transcribed by hand into typed checks.
#    Fact 2 ("Глеб переводит Ане 3 842 ₽") has no check type in settle.py -
#    it is checked by reading the plan in report.md, see README.
out["control_facts"] = [
    {"type": "total", "value": 90000, "text": "факт 1: всего потрачено 90 000 ₽ после двух возвратов"},
    {"type": "balance", "person": "Аня", "value": 24359, "text": "факт 3: баланс Ани +24 359 ₽"},
    {"type": "counted_once", "receipt": "R02", "messages": ["M07", "M08"], "text": "факт 4: такси R02 учтено один раз (M07 фото, M08 «скинул»)"},
    {"type": "not_in", "receipt": "R06", "person": "Ира", "text": "факт 5: Ира не была на ужине R06 и не платит"},
    {"type": "not_in", "receipt": "R10", "person": "Борис", "text": "доп.: Борис не был в банях R10"},
    {"type": "max_transfers", "value": 4, "text": "доп.: план не длиннее n−1 = 4"},
]

sys.stdout.reconfigure(encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=1))
