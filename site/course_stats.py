"""コース（競馬場×芝ダ×距離）ごとの傾向を、過去の公式レース結果（data/history）から数える。

AIの予想とは無関係の数字。ページの表（site/extra.py）と、AIの解説文の材料（scraper/course_gen.py）の両方で使う。
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SURF_NAME = {"芝": "芝", "ダ": "ダート", "障": "障害"}
SURF_SLUG = {"芝": "turf", "ダ": "dirt", "障": "jump"}
POP_BANDS = [(1, 1, "1番人気"), (2, 2, "2番人気"), (3, 3, "3番人気"), (4, 5, "4〜5番人気"), (6, 9, "6〜9番人気"), (10, 99, "10番人気以下")]
POS_BANDS = [(1, 1, "逃げ（4角1番手）"), (2, 4, "先行（4角2〜4番手）"), (5, 9, "中団（4角5〜9番手）"), (10, 99, "後方（4角10番手以下）")]
GATE_BANDS = ["内（馬番が頭数の1/3以内）", "中", "外（馬番が頭数の2/3より外）"]
PAY_TYPES = ("単勝", "馬連", "3連複", "3連単")


def _iter_history():
    for src in ("jra", "local"):
        for f in sorted((ROOT / "data" / "history" / src).glob("*/*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    yield src, json.loads(line)
                except json.JSONDecodeError:
                    continue


def course_slug(venue_slug: str, s: str, m: int) -> str:
    return f"{venue_slug}-{SURF_SLUG.get(s, 'dirt')}-{m}"


def collect(min_races: int = 30) -> dict:
    """{(venue, s, m): stats} を返す。s は 芝/ダ/障。"""
    acc: dict = defaultdict(lambda: {"races": 0, "first": "99999999", "last": "", "fields": 0,
                                     "pop": {b[2]: [0, 0, 0] for b in POP_BANDS},       # [頭数, 1着, 3着内]
                                     "gate": {g: [0, 0, 0] for g in GATE_BANDS},
                                     "pos": {b[2]: 0 for b in POS_BANDS}, "pos_n": 0,
                                     "pay": {t: [] for t in PAY_TYPES}, "big3t": 0, "src": ""})
    for src, r in _iter_history():
        if not r.get("m") or not r.get("s"):
            continue
        rows = [x for x in r.get("rows") or [] if str(x[0]).isdigit()]
        if len(rows) < 3:
            continue
        a = acc[(r["v"], r["s"], int(r["m"]))]
        a["src"] = src
        a["races"] += 1
        a["first"], a["last"] = min(a["first"], r["d"]), max(a["last"], r["d"])
        n = r.get("n") or len(r.get("rows") or [])
        a["fields"] += n
        for fin, num, _frame, pos4, pop in rows:
            f = int(fin)
            if isinstance(pop, int):
                for lo, hi, lab in POP_BANDS:
                    if lo <= pop <= hi:
                        a["pop"][lab][0] += 1
                        a["pop"][lab][1] += f == 1
                        a["pop"][lab][2] += f <= 3
            if isinstance(num, int) and n:
                g = GATE_BANDS[0] if num <= n / 3 else GATE_BANDS[2] if num > n * 2 / 3 else GATE_BANDS[1]
                a["gate"][g][0] += 1
                a["gate"][g][1] += f == 1
                a["gate"][g][2] += f <= 3
            if f == 1 and isinstance(pos4, int):
                a["pos_n"] += 1
                for lo, hi, lab in POS_BANDS:
                    if lo <= pos4 <= hi:
                        a["pos"][lab] += 1
        pay = r.get("pay") or {}
        for t in PAY_TYPES:
            ys = [int(y) for _, y in pay.get(t, []) if y]
            if ys:
                a["pay"][t].append(ys[0])
        if any(int(y) >= 100000 for _, y in pay.get("3連単", []) if y):
            a["big3t"] += 1
    return {k: v for k, v in acc.items() if v["races"] >= min_races}


def pct(a, b) -> str:
    return f"{100 * a / b:.1f}%" if b else "-"


def med(v: list) -> int:
    v = sorted(v)
    return v[len(v) // 2] if v else 0


def fd(d: str) -> str:
    return f"{d[:4]}年{int(d[4:6])}月"


def summary_text(key, a, venue_name: str) -> str:
    """AIに渡す材料（数字だけ）。"""
    v, s, m = key
    lines = [f"コース：{venue_name}{SURF_NAME.get(s, s)}{m}m",
             f"対象：{fd(a['first'])}〜{fd(a['last'])}の{a['races']}レース、平均{a['fields'] / a['races']:.1f}頭立て"]
    if any(x[0] for x in a["pop"].values()):
        lines.append("人気別（1頭あたり）：" + "／".join(f"{lab} 勝率{pct(x[1], x[0])}・3着内率{pct(x[2], x[0])}（{x[0]}頭）" for lab, x in a["pop"].items() if x[0]))
    lines.append("馬番の位置別（1頭あたり）：" + "／".join(f"{g} 勝率{pct(x[1], x[0])}・3着内率{pct(x[2], x[0])}" for g, x in a["gate"].items() if x[0]))
    if a["pos_n"]:
        lines.append(f"勝ち馬の4コーナーの位置（{a['pos_n']}頭）：" + "／".join(f"{lab} {pct(c, a['pos_n'])}" for lab, c in a["pos"].items()))
    lines.append("払戻の中央値（100円あたり）：" + "／".join(f"{t} {med(a['pay'][t]):,}円" for t in PAY_TYPES if a["pay"][t]))
    if a["pay"]["3連単"]:
        lines.append(f"3連単が10万円以上になったレース：{pct(a['big3t'], len(a['pay']['3連単']))}")
    return "\n".join(lines)


def tables_html(a, esc) -> str:
    out = []
    if any(x[0] for x in a["pop"].values()):
        out.append("<h3>人気別の成績</h3><div class='scroll'><table><thead><tr><th>人気</th><th>頭数</th><th>勝率</th><th>3着内率</th></tr></thead><tbody>"
                   + "".join(f"<tr><td>{esc(lab)}</td><td>{x[0]:,}</td><td>{pct(x[1], x[0])}</td><td>{pct(x[2], x[0])}</td></tr>" for lab, x in a["pop"].items() if x[0])
                   + "</tbody></table></div>")
    out.append("<h3>馬番の位置別の成績</h3><div class='scroll'><table><thead><tr><th>位置</th><th>頭数</th><th>勝率</th><th>3着内率</th></tr></thead><tbody>"
               + "".join(f"<tr><td>{esc(g)}</td><td>{x[0]:,}</td><td>{pct(x[1], x[0])}</td><td>{pct(x[2], x[0])}</td></tr>" for g, x in a["gate"].items() if x[0])
               + "</tbody></table></div>")
    if a["pos_n"]:
        out.append("<h3>勝ち馬の位置取り（4コーナー）</h3><div class='scroll'><table><thead><tr><th>位置</th><th>勝ち馬に占める割合</th></tr></thead><tbody>"
                   + "".join(f"<tr><td>{esc(lab)}</td><td>{pct(c, a['pos_n'])}</td></tr>" for lab, c in a["pos"].items())
                   + "</tbody></table></div>")
    pays = [(t, a["pay"][t]) for t in PAY_TYPES if a["pay"][t]]
    if pays:
        out.append("<h3>払戻（100円あたり）</h3><div class='scroll'><table><thead><tr><th>券種</th><th>中央値</th><th>平均</th><th>最高</th></tr></thead><tbody>"
                   + "".join(f"<tr><td>{t}</td><td>{med(v):,}円</td><td>{sum(v) // len(v):,}円</td><td>{max(v):,}円</td></tr>" for t, v in pays)
                   + "</tbody></table></div>")
    return "".join(out)
