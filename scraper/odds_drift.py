"""予想に使った単勝オッズと確定オッズの差を測る（2026-11-11から。週次見直しで使う）。

予想ファイルの blend.odds（買い目を決めた時点の単勝オッズ）と、確定後の単勝の払戻（=1着馬の確定オッズ×100円）を比べる。
確定オッズが分かるのは1着馬だけなので、「勝った馬の 確定オッズ ÷ 予想時オッズ」の中央値を、
中央／地方、予想時の人気、オッズを取ってから発走までの時間で分けて出す。
1より小さい＝勝つ馬は締め切りまでにオッズが下がっていた（人気になっていた）。

  python odds_drift.py --since 20261111
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime

from common import DATA_DIR

ROOT = DATA_DIR.parent


def _median(v: list[float]) -> float | None:
    v = sorted(v)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


def rows(since: str, until: str = "99999999") -> list[dict]:
    out = []
    for d in sorted(x.name for x in (ROOT / "predictions").iterdir() if x.is_dir() and since <= x.name <= until):
        for f in sorted((ROOT / "predictions" / d).glob("*.json")):
            p = json.loads(f.read_text(encoding="utf-8"))
            od = (p.get("blend") or {}).get("odds") or {}
            if not od:
                continue
            rf = DATA_DIR / "results" / d / f"{p.get('results_key') or p['race_id']}.json"
            cf = DATA_DIR / "races" / d / f"{p['race_id']}.json"
            if not rf.exists():
                continue
            res = json.loads(rf.read_text(encoding="utf-8"))
            tan = (res.get("payouts") or {}).get("単勝") or []
            if len(tan) != 1:
                continue  # 同着・不成立は除く
            win = str(tan[0].get("combo"))
            if win not in od or not tan[0].get("yen"):
                continue
            snap = float(od[win])
            pop = sorted(od.values()).index(od[win]) + 1
            age = None
            race = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else {}
            at, post = (p.get("blend") or {}).get("odds_at"), race.get("post_time")
            if at and post:
                try:
                    a = datetime.strptime(f"{d[:4]}/{at}", "%Y/%m/%d %H:%M")
                    b = datetime.strptime(f"{d} {post}", "%Y%m%d %H:%M")
                    age = (b - a).total_seconds() / 60
                except ValueError:
                    age = None
            hon = (p.get("marks") or {}).get("◎")
            out.append({"date": d, "race_id": p["race_id"], "jra": p["race_id"].startswith("jra_"), "snap": snap,
                        "final": int(tan[0]["yen"]) / 100, "pop": pop, "min_before": age,
                        "honmei": str(hon) == win})
    return out


def report(rs: list[dict]) -> str:
    if not rs:
        return "予想時オッズの記録がある確定レースはまだ無い"
    groups = defaultdict(list)
    for r in rs:
        ratio = r["final"] / r["snap"]
        groups["全体"].append(ratio)
        groups["中央" if r["jra"] else "地方"].append(ratio)
        groups["予想時1〜2番人気" if r["pop"] <= 2 else "予想時3〜5番人気" if r["pop"] <= 5 else "予想時6番人気以下"].append(ratio)
        if r["min_before"] is not None:
            groups["発走60分以上前のオッズ" if r["min_before"] >= 60 else "発走60分未満前のオッズ"].append(ratio)
        if r["honmei"]:
            groups["◎が勝ったレース"].append(ratio)
    lines = [f"勝った馬の 確定オッズ÷予想時オッズ（中央値・レース数）　対象{len(rs)}レース"]
    for k, v in groups.items():
        lines.append(f"- {k}：{_median(v):.2f}（{len(v)}）")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="20261111")
    ap.add_argument("--until", default="99999999")
    a = ap.parse_args()
    print(report(rows(a.since, a.until)))


if __name__ == "__main__":
    main()
