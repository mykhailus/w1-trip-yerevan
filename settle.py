#!/usr/bin/env python3
"""Trip settlement: who spent what and who owes whom.

Everything trip-specific lives in the data file: people, currencies, rates,
receipts, refunds, disputed items and control facts. The code knows nothing
about any particular trip.

    python settle.py trip/data.json               # report to stdout
    python settle.py trip/data.json -o report.md  # report to file
    python settle.py trip/data.json --check       # control facts only, exit 1 on failure
"""
import argparse
import json
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

CENT = Decimal("0.01")


class DataError(Exception):
    pass


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(CENT, rounding=ROUND_HALF_UP)


def fmt(x: Decimal) -> str:
    s = f"{abs(x):,.2f}".replace(",", " ").replace(".", ",")
    if s.endswith(",00"):
        s = s[:-3]
    return ("−" if x < 0 else "") + s


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise DataError(f"{path}: не JSON ({e})")
    for key in ("people", "base_currency", "receipts"):
        if key not in data:
            raise DataError(f"в данных нет поля «{key}»")
    return data


def rate(data: dict, currency: str, date: str) -> Decimal:
    if currency == data["base_currency"]:
        return Decimal(1)
    try:
        return Decimal(str(data["rates"][currency][date]))
    except KeyError:
        raise DataError(f"нет курса {currency} на {date}")


def to_base(data: dict, amount, currency: str, date: str) -> Decimal:
    return money(Decimal(str(amount)) * rate(data, currency, date))


def split(total: Decimal, people: list) -> dict:
    """Split evenly; leftover cents go to the first people in the list."""
    n = len(people)
    base = (total / n).quantize(CENT, rounding="ROUND_DOWN")
    rest = int((total - base * n) / CENT)
    return {p: base + (CENT if i < rest else 0) for i, p in enumerate(people)}


def settle(data: dict) -> dict:
    people = data["people"]
    known = set(people)
    paid = {p: Decimal(0) for p in people}
    share = {p: Decimal(0) for p in people}
    rows, refund_rows = [], []
    by_id = {}

    for r in data["receipts"]:
        who, for_ = r["paid_by"], r.get("for", people)
        for p in [who, *for_]:
            if p not in known:
                raise DataError(f"{r['id']}: «{p}» нет в списке участников")
        base = to_base(data, r["amount"], r["currency"], r["date"])
        paid[who] += base
        for p, s in split(base, for_).items():
            share[p] += s
        by_id[r["id"]] = {**r, "base": base, "for": for_}
        rows.append(by_id[r["id"]])

    for v in data.get("refunds", []):
        orig = by_id.get(v["receipt"])
        if orig is None:
            raise DataError(f"{v['id']}: чека {v['receipt']} нет")
        base = to_base(data, v["amount"], v["currency"], v["date"])
        paid[v["to"]] -= base          # the money came back to whoever received it
        for p, s in split(base, orig["for"]).items():
            share[p] -= s              # and lowers the cost for those who shared the receipt
        refund_rows.append({**v, "base": base, "for": orig["for"]})

    balance = {p: paid[p] - share[p] for p in people}
    total = sum(r["base"] for r in rows) - sum(v["base"] for v in refund_rows)
    return {"rows": rows, "refunds": refund_rows, "paid": paid, "share": share,
            "balance": balance, "total": total, "transfers": transfers(balance)}


def transfers(balance: dict) -> list:
    """Greedy: the largest debtor pays the largest creditor. At most n-1 transfers."""
    debt = {p: -b for p, b in balance.items() if b < 0}
    cred = {p: b for p, b in balance.items() if b > 0}
    plan = []
    while debt and cred:
        d = max(debt, key=debt.get)
        c = max(cred, key=cred.get)
        x = min(debt[d], cred[c])
        plan.append((d, c, x))
        debt[d] -= x
        cred[c] -= x
        if debt[d] == 0:
            del debt[d]
        if cred[c] == 0:
            del cred[c]
    return plan


def check_facts(data: dict, res: dict) -> list:
    """Control facts are data, not code: each one is a typed check."""
    out = []
    by_id = {r["id"]: r for r in res["rows"]}
    for f in data.get("control_facts", []):
        kind, ok, got = f["type"], False, ""
        if kind == "total":
            got = res["total"]
            ok = abs(got - money(f["value"])) <= money(f.get("tolerance", 1))
        elif kind == "balance":
            got = res["balance"][f["person"]]
            ok = abs(got - money(f["value"])) <= money(f.get("tolerance", 1))
        elif kind == "not_in":
            r = by_id[f["receipt"]]
            got = ", ".join(r["for"])
            ok = f["person"] not in r["for"] and f["person"] in data["people"]
        elif kind == "counted_once":
            hits = [r["id"] for r in res["rows"] if set(f["messages"]) & set(r.get("messages", []))]
            got = ", ".join(hits) or "нет"
            ok = hits == [f["receipt"]]
        elif kind == "max_transfers":
            got = len(res["transfers"])
            ok = got <= int(f["value"])
        else:
            raise DataError(f"неизвестный тип контрольного факта «{kind}»")
        out.append((f, ok, got))
    return out


def report(data: dict, res: dict, facts: list) -> str:
    cur = data["base_currency"]
    L = [f"# {data.get('title', 'Поездка')} – расчёт", ""]
    L += ["## Чеки", "", f"| чек | дата | кто платил | сумма | курс | {cur} | на кого | источник |",
          "|---|---|---|---|---|---|---|---|"]
    for r in res["rows"]:
        who = "все" if len(r["for"]) == len(data["people"]) else ", ".join(r["for"])
        L.append(f"| {r['id']} | {r['date']} | {r['paid_by']} | {fmt(money(r['amount']))} {r['currency']} "
                 f"| {rate(data, r['currency'], r['date'])} | {fmt(r['base'])} | {who} | {', '.join(r.get('messages', []))} |")
    if res["refunds"]:
        L += ["", "## Возвраты", "", f"| возврат | дата | кому | сумма | по чеку | {cur} | делится на | источник |",
              "|---|---|---|---|---|---|---|---|"]
        for v in res["refunds"]:
            L.append(f"| {v['id']} | {v['date']} | {v['to']} | {fmt(money(v['amount']))} {v['currency']} | {v['receipt']} "
                     f"| −{fmt(v['base'])} | {', '.join(v['for'])} | {', '.join(v.get('messages', []))} |")
    L += ["", "## Балансы", "", f"| участник | заплатил, {cur} | его доля, {cur} | баланс, {cur} |", "|---|---|---|---|"]
    for p in data["people"]:
        L.append(f"| {p} | {fmt(res['paid'][p])} | {fmt(res['share'][p])} | **{fmt(res['balance'][p])}** |")
    L += ["", f"Сумма балансов: {fmt(sum(res['balance'].values()))} {cur}. Плюс – ему должны, минус – он должен.",
          "", f"Всего потрачено с учётом возвратов: **{fmt(res['total'])} {cur}**.", "",
          f"## План переводов ({len(res['transfers'])} из максимум {len(data['people']) - 1})", ""]
    for i, (d, c, x) in enumerate(res["transfers"], 1):
        L.append(f"{i}. {d} → {c}: {fmt(x)} {cur}")
    if data.get("disputed"):
        L += ["", "## Спорное – в расчёт не вошло", ""]
        for s in data["disputed"]:
            L.append(f"- {s['what']} ({', '.join(s['messages'])}): {s['why']}")
    if facts:
        L += ["", "## Контрольные факты", "", "| # | факт | получилось | |", "|---|---|---|---|"]
        for i, (f, ok, got) in enumerate(facts, 1):
            got_s = fmt(got) if isinstance(got, Decimal) else got
            L.append(f"| {i} | {f['text']} | {got_s} | {'✅' if ok else '❌'} |")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    try:
        data = load(a.data)
        res = settle(data)
        facts = check_facts(data, res)
    except DataError as e:
        print(f"ошибка в данных: {e}", file=sys.stderr)
        return 2
    if a.check:
        for f, ok, got in facts:
            print(f"{'OK ' if ok else 'FAIL'} {f['text']} → {fmt(got) if isinstance(got, Decimal) else got}")
        return 0 if all(ok for _, ok, _ in facts) else 1
    text = report(data, res, facts)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
