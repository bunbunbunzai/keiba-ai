"""走破時計の指数（スピード指数）と、その効果の検証（2026-11-11）。

指数の作り方：保存してある全出馬表の近走（重複なし・約3.4万走）から
1. 場・馬場（芝/ダ）・距離ごとに走破時計の中央値と散らばり（四分位から）を求め（30走以上の組だけ）、
2. 各走の時計を「中央値からの差÷散らばり」にし、
3. その日・その場・その馬場の全走の平均を引いて、馬場の速さ（日ごとの差）を除く。
大きいほど速い。1頭の指数は、直近3走の最高と平均。

検証（--test）：予想したレースで、1〜3着の順番の説明力（プラケット・ルース型、日付で5つに分けた交差検証）を
「単勝オッズ＋AIの評価点」と「＋指数」で比べ、あわせて補正勝率の◎の単複1点の回収率も比べる。

2026-11-11の結果（596レース）：説明力は15.7%→17.1%（改善1.4ポイント、95%区間0.8〜1.9。ほぼ地方の分）、
◎の3着内率68.6%→69.0%。ただし◎の単複の回収率は87.0%→82.8%（差の95%区間−9.2〜+0.9）。
着順はよく当たるようになるが、指数で選び直した◎は人気寄りで配当が下がるため、採用基準（回収率を下げない）を満たさない。
◎の決定（blend.py）には入れず、月1回この検証をやり直す。

  python speed.py --test
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import random
import re
from collections import defaultdict
from functools import lru_cache

import bets as BT
from common import DATA_DIR

ROOT = DATA_DIR.parent
MIN_GROUP = 30
MIN_DAY = 8


def _pdate(s) -> str | None:
    s = str(s or "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s) or re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s)
    return f"{int(m.group(1)):04d}{int(m.group(2)):02d}{int(m.group(3)):02d}" if m else None


def _secs(t) -> float | None:
    m = re.match(r"(?:(\d+):)?(\d+)\.(\d)", str(t or ""))
    return int(m.group(1) or 0) * 60 + int(m.group(2)) + int(m.group(3)) / 10 if m else None


@lru_cache(maxsize=1)
def runs() -> dict:
    """{(日付, 場, 馬名): {...,'idx': 指数 or None}}"""
    out = {}
    for f in glob.glob(str(DATA_DIR / "races" / "*" / "*.json")):
        try:
            r = json.loads(open(f, encoding="utf-8").read())
        except Exception:  # noqa: BLE001
            continue
        for h in r.get("horses") or []:
            for p in h.get("past") or []:
                d, ts = _pdate(p.get("date")), _secs(p.get("time"))
                if not d or ts is None or not p.get("distance"):
                    continue
                k = (d, str(p.get("venue")).lstrip("Ｊ"), h.get("name"))
                out[k] = {"date": d, "venue": k[1], "surface": p.get("surface"), "dist": int(p.get("distance")), "t": ts}
    grp = defaultdict(list)
    for x in out.values():
        grp[(x["venue"], x["surface"], x["dist"])].append(x["t"])
    base = {}
    for k, v in grp.items():
        if len(v) >= MIN_GROUP:
            v = sorted(v)
            base[k] = (v[len(v) // 2], max((v[3 * len(v) // 4] - v[len(v) // 4]) / 1.349, 0.3))
    day = defaultdict(list)
    for x in out.values():
        b = base.get((x["venue"], x["surface"], x["dist"]))
        x["z"] = (x["t"] - b[0]) / b[1] if b else None
        if x["z"] is not None:
            day[(x["date"], x["venue"], x["surface"])].append(x["z"])
    var = {k: sum(v) / len(v) for k, v in day.items() if len(v) >= MIN_DAY}
    for x in out.values():
        x["idx"] = None if x["z"] is None else -(x["z"] - var.get((x["date"], x["venue"], x["surface"]), 0.0))
    return out


def horse(h: dict, date: str) -> tuple[float | None, float | None]:
    """(直近3走の最高, 平均)。指数が1走も無ければ (None, None)。"""
    rs = runs()
    xs = []
    for p in h.get("past") or []:
        d = _pdate(p.get("date"))
        if not d or d >= date:
            continue
        x = rs.get((d, str(p.get("venue")).lstrip("Ｊ"), h.get("name")))
        if x and x["idx"] is not None:
            xs.append((d, x["idx"]))
    xs = [v for _, v in sorted(xs, reverse=True)[:3]]
    return (max(xs), sum(xs) / len(xs)) if xs else (None, None)


def _payout(res: dict, kind: str, num) -> int:
    for x in (res.get("payouts") or {}).get(kind, []):
        if str(x.get("combo")) == str(num):
            return int(x.get("yen") or 0)
    return 0


def test() -> None:
    import numpy as np
    from scipy.optimize import minimize

    races = []
    for pf in sorted(glob.glob(str(ROOT / "predictions" / "*" / "*.json"))):
        date = pf.split("/")[-2]
        p = json.loads(open(pf, encoding="utf-8").read())
        try:
            race = json.loads((DATA_DIR / "races" / date / f"{p['race_id']}.json").read_text(encoding="utf-8"))
            res = json.loads((DATA_DIR / "results" / date / f"{p.get('results_key') or p['race_id']}.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        od = BT.win_odds(race)
        if not BT.odds_ready(race, od):
            continue
        sc = {int(h["number"]): h.get("score") for h in p.get("horses") or [] if h.get("number") is not None}
        fin = {}
        for r in res.get("rows") or []:
            try:
                fin[int(r["number"])] = int(str(r["finish"]).strip())
            except (TypeError, ValueError, KeyError):
                pass
        nums = [n for n in od if n in fin and isinstance(sc.get(n), (int, float))]
        if len(nums) < 5:
            continue
        hs = {int(h["number"]): h for h in race.get("horses") or [] if h.get("number") is not None}
        sp = {n: horse(hs.get(n, {}), date) for n in nums}
        have = [sp[n] for n in nums if sp[n][0] is not None]
        if len(have) < len(nums) / 2:
            continue
        bm, am = sum(x[0] for x in have) / len(have), sum(x[1] for x in have) / len(have)
        inv = {n: 1 / od[n] for n in nums}
        tot, smean = sum(inv.values()), sum(sc[n] for n in nums) / len(nums)
        X = np.array([[math.log(inv[n] / tot), sc[n] - smean,
                       (sp[n][0] - bm) if sp[n][0] is not None else 0.0, (sp[n][1] - am) if sp[n][1] is not None else 0.0,
                       1.0 if sp[n][0] is None else 0.0] for n in nums])
        order = sorted(nums, key=lambda n: fin[n])
        races.append({"date": date, "X": X, "top": [nums.index(n) for n in order[:3]], "nums": nums, "fin": fin,
                      "od": od, "res": res, "jra": p["race_id"].startswith("jra_")})

    def nll(w, rs, cols):
        t = 0.0
        for r in rs:
            u = r["X"][:, cols] @ w
            alive = np.ones(len(u), bool)
            for i in r["top"]:
                m = u[alive].max()
                t -= u[i] - (m + math.log(np.exp(u[alive] - m).sum()))
                alive[i] = False
        return t

    models = {"オッズ＋評価点": [0, 1], "＋指数": [0, 1, 2, 3, 4]}
    dates = sorted({r["date"] for r in races})
    folds = [dates[i::5] for i in range(5)]
    per = {m: {} for m in models}
    for fd in folds:
        tr = [r for r in races if r["date"] not in fd]
        te = [r for r in races if r["date"] in fd]
        for m, cols in models.items():
            w = minimize(nll, np.zeros(len(cols)), args=(tr, cols), method="BFGS").x
            for r in te:
                u = r["X"][:, cols] @ w
                hon = r["nums"][int(np.argmax(u))]
                b = BT.tanpuku(hon, r["od"])
                per[m][id(r)] = (nll(w, [r], cols), hon, 100 * len(b), sum(_payout(r["res"], x["type"], hon) for x in b))
    null = {id(r): sum(math.log(len(r["nums"]) - k) for k in range(3)) for r in races}
    print(f"対象 {len(races)}レース（中央{sum(r['jra'] for r in races)}）")
    for m in models:
        ll = sum(per[m][id(r)][0] for r in races)
        st = sum(per[m][id(r)][2] for r in races)
        rt = sum(per[m][id(r)][3] for r in races)
        t3 = sum(r["fin"][per[m][id(r)][1]] <= 3 for r in races)
        print(f"{m}：説明力 {100 * (1 - ll / sum(null.values())):.2f}%　◎3着内 {100 * t3 / len(races):.1f}%　◎単複 {100 * rt / st:.1f}%")
    rnd = random.Random(9)
    d_ll, d_roi = [], []
    a, b = "オッズ＋評価点", "＋指数"
    for _ in range(2000):
        ii = [races[rnd.randrange(len(races))] for _ in races]
        d_ll.append(100 * sum(per[a][id(r)][0] - per[b][id(r)][0] for r in ii) / sum(null[id(r)] for r in ii))
        ra = 100 * sum(per[a][id(r)][3] for r in ii) / sum(per[a][id(r)][2] for r in ii)
        rb = 100 * sum(per[b][id(r)][3] for r in ii) / sum(per[b][id(r)][2] for r in ii)
        d_roi.append(rb - ra)
    d_ll.sort(); d_roi.sort()
    print(f"説明力の改善 95%区間 {d_ll[50]:.2f}〜{d_ll[1949]:.2f}ポイント")
    print(f"◎単複の回収率の差（指数あり−なし）95%区間 {d_roi[50]:.1f}〜{d_roi[1949]:.1f}ポイント")
    print("採用の目安：説明力の区間が0より上、かつ回収率の差の区間の下限が−2ポイント以上")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    if a.test:
        test()
    else:
        rs = runs()
        print(f"近走 {len(rs)}走、指数あり {sum(1 for x in rs.values() if x['idx'] is not None)}走")


if __name__ == "__main__":
    main()
