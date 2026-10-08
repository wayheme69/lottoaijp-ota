#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jp_results.py — robot LOTTO AI JP : écrit jp_results.json (30 derniers tirages ロト6 et ロト7 avec le vrai
gain et le nombre de gagnants (口数) de chaque rang, + prochain tirage).

Sources (historique officiel complet, Shift_JIS) :
  1. loto-life.net/csv/loto6|loto7      (principale : dates ISO, 口数/賞金 alternés)
  2. loto6|loto7.thekyo.jp/data/*.csv   (recoupement : 口数 groupés puis 賞金 groupés)
Recoupement OBLIGATOIRE : pour chaque tirage présent dans les deux, numéros, bonus, 口数 et 賞金 doivent être
identiques, sinon le robot échoue (rien n'est publié). Si une seule source répond, elle est utilisée seule.

Format :
  {"updated": "...", "loto6": [{date, draw, numbers[6], bonus[1], payouts{"6","5+B","5","4","3"}, winners{...}, carryover}],
   "loto7": [{date, draw, numbers[7], bonus[2], payouts{"7","6+B","6","5","4","3+B"}, winners{...}, carryover}],
   "next": {"loto6": "yyyy-mm-dd", "loto7": "yyyy-mm-dd"}}
payouts[k] = null quand personne n'a gagné ce rang (賞金 0) ; tirages du plus récent au plus ancien.
"""
import json, re, sys, time, urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "jp_results.json"
KEEP = 30
GAMES = {
    "loto6": dict(nm=6, nb=1, pool=43, ranks=["6", "5+B", "5", "4", "3"], weekdays=[0, 3],   # lundi, jeudi
                  life="https://loto-life.net/csv/loto6", kyo="https://loto6.thekyo.jp/data/loto6.csv"),
    "loto7": dict(nm=7, nb=2, pool=37, ranks=["7", "6+B", "6", "5", "4", "3+B"], weekdays=[4],  # vendredi
                  life="https://loto-life.net/csv/loto7", kyo="https://loto7.thekyo.jp/data/loto7.csv"),
}


def fetch(url):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (LOTTO AI JP results robot)"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
            if len(raw) > 10000:
                return raw.decode("cp932", "replace")
        except Exception as e:
            print(f"  {url} : {e}", file=sys.stderr)
        time.sleep(5 * (i + 1))
    return None


def parse_date(s):
    y, m, d = map(int, re.split(r"[-/]", s.strip()))
    return date(y, m, d)


def parse(text, g, layout):
    c = GAMES[g]; nm, nb, nr = c["nm"], c["nb"], len(c["ranks"])
    rows = {}
    for line in text.splitlines()[1:]:
        p = [x.strip() for x in line.split(",")]
        if len(p) < 2 + nm + nb + 2 * nr or not p[0].isdigit():
            continue
        nums = sorted(int(x) for x in p[2:2 + nm]); bonus = sorted(int(x) for x in p[2 + nm:2 + nm + nb])
        rest = [int(x) for x in p[2 + nm + nb:2 + nm + nb + 2 * nr + 1]]
        if layout == "life":       # 口数, 賞金 alternés
            counts, prizes = rest[0:2 * nr:2], rest[1:2 * nr:2]
        else:                      # 口数 ×nr puis 賞金 ×nr
            counts, prizes = rest[:nr], rest[nr:2 * nr]
        carry = rest[2 * nr] if len(rest) > 2 * nr else None
        rows[int(p[0])] = dict(date=parse_date(p[1]), numbers=nums, bonus=bonus, counts=counts, prizes=prizes, carry=carry)
    return rows


def check(g, rows):
    c = GAMES[g]
    for no, r in rows.items():
        allv = r["numbers"] + r["bonus"]
        if len(set(allv)) != c["nm"] + c["nb"] or not all(1 <= v <= c["pool"] for v in allv):
            raise SystemExit(f"{g} 第{no}回 : numéros invalides {r['numbers']} + {r['bonus']}")


def next_draw(g, last):
    d = last + timedelta(days=1)
    while d.weekday() not in GAMES[g]["weekdays"] or (d.month == 12 and d.day == 31) or (d.month == 1 and d.day <= 3):
        d += timedelta(days=1)
    return d


def build(g):
    c = GAMES[g]
    life_t, kyo_t = fetch(c["life"]), fetch(c["kyo"])
    life = parse(life_t, g, "life") if life_t else {}
    kyo = parse(kyo_t, g, "kyo") if kyo_t else {}
    if not life and not kyo:
        raise SystemExit(f"{g} : aucune source ne répond")
    for rows in (life, kyo):
        check(g, rows)
    base = life or kyo
    nos = sorted(base)[-KEEP:]
    if nos != list(range(nos[0], nos[0] + len(nos))):
        raise SystemExit(f"{g} : n° de tirage non continus {nos[:3]}…{nos[-3:]}")
    if life and kyo:
        both = [n for n in nos if n in kyo]
        for n in both:
            a, b = life[n], kyo[n]
            for k in ("date", "numbers", "bonus", "counts", "prizes"):
                if a[k] != b[k]:
                    raise SystemExit(f"{g} 第{n}回 : les deux sources divergent sur {k} : {a[k]} ≠ {b[k]}")
        extra = [n for n in nos if n not in kyo]
        if len(extra) > 1:
            raise SystemExit(f"{g} : la source de recoupement a {len(extra)} tirages de retard")
        print(f"{g} : {len(both)} tirages recoupés, {len(extra)} en avance sur thekyo", file=sys.stderr)
    else:
        print(f"⚠️ {g} : une seule source disponible ({'loto-life' if life else 'thekyo'})", file=sys.stderr)
    out = []
    for n in reversed(nos):
        r = base[n]
        payouts = {k: (float(p) if p > 0 else None) for k, p in zip(c["ranks"], r["prizes"])}
        winners = {k: w for k, w in zip(c["ranks"], r["counts"])}
        if all(p == 0 for p in r["prizes"]) and all(w == 0 for w in r["counts"]):
            payouts, winners = None, None      # gains pas encore publiés
        out.append(dict(date=r["date"].isoformat(), draw=n, numbers=r["numbers"], bonus=r["bonus"],
                        payouts=payouts, winners=winners, carryover=r["carry"]))
    latest = base[nos[-1]]["date"]
    today = datetime.now(timezone(timedelta(hours=9))).date()
    if (today - latest).days > 10 and not (today.month == 1 and today.day <= 8):
        raise SystemExit(f"{g} : dernier tirage {latest} trop ancien (sources figées ?)")
    return out, next_draw(g, latest).isoformat()


def main():
    data = {"loto6": None, "loto7": None, "next": {}}
    for g in GAMES:
        data[g], data["next"][g] = build(g)
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    if {k: old.get(k) for k in data} == data:
        print("Aucun changement."); return
    data = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **data}
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    print(f"jp_results.json : ロト6 第{data['loto6'][0]['draw']}回 ({data['loto6'][0]['date']}), ロト7 第{data['loto7'][0]['draw']}回 ({data['loto7'][0]['date']}), next {data['next']}")


if __name__ == "__main__":
    main()
