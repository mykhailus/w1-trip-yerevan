#!/usr/bin/env python3
"""Spoil one input value at a time and make sure the control facts turn red.

    python corrupt_test.py trip/data.json
"""
import copy
import json
import sys
from pathlib import Path

import settle

CASES = [
    ("сумма квартиры R03 +1 000 AMD", lambda d: d["receipts"][2].__setitem__("amount", d["receipts"][2]["amount"] + 1000)),
    ("курс 13.09 0,21 → 0,22", lambda d: d["rates"]["AMD"].__setitem__("2026-09-13", "0.2200")),
    ("Даша добавлена в ужин R06", lambda d: d["receipts"][5].__setitem__("for", d["people"])),
    ("такси R02 записано вторым чеком по M07", lambda d: d["receipts"].append({**d["receipts"][1], "id": "R02b", "messages": ["M07"]})),
    ("возврат V01 пропал", lambda d: d["refunds"].pop(0)),
    ("возврат V02 ушёл Боре вместо Ани", lambda d: d["refunds"][1].__setitem__("to", "Боря")),
    ("кофе R09 на всех пятерых", lambda d: d["receipts"][8].pop("for")),
]


def main() -> int:
    base = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    missed = 0
    for name, spoil in CASES:
        d = copy.deepcopy(base)
        spoil(d)
        facts = settle.check_facts(d, settle.settle(d))
        red = [f["text"] for f, ok, _ in facts if not ok]
        print(f"{'поймано' if red else 'ПРОПУЩЕНО'}: {name}" + (f" → {len(red)} красн." if red else ""))
        missed += not red
    print(f"\nпоймано {len(CASES) - missed} из {len(CASES)}")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
