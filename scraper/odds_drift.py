"""予想に使った単勝オッズと確定オッズの差を測る（2026-11-11から。週次見直しで使う）。

予想ファイルの blend.odds（買い目を決めた時点の単勝オッズ）と、確定後の単勝の払戻（=1着馬の確定オッズ×100円）を比べる。
1. 勝った馬：確定オッズは単勝の払戻から分かるので、「確定オッズ ÷ 予想時オッズ」の中央値を、
   中央／地方、予想時の人気、オッズを取ってから発走までの時間で分けて出す。
2. ◎：final_odds.py が残した全頭のオッズ（中央は確定、地方は発走2〜12分前）と比べ、
   ◎の買い目の区分（単勝・複勝・なし）が締め切りまでに変わった割合を出す。
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


def honmei_rows(since: str, until: str = "99999999") -> list[dict]:
    """◎について、予想時オッズと final_odds（中央は確定、地方は発走直前）を比べる。"""
    import bets as BT

    out = []
    for d in sorted(x.name for x in (ROOT / "predictions").iterdir() if x.is_dir() and since <= x.name <= until):
        for f in sorted((ROOT / "predictions" / d).glob("*.json")):
            p = json.loads(f.read_text(encoding="utf-8"))
            snap = (p.get("blend") or {}).get("odds") or {}
            ff = DATA_DIR / "final_odds" / d / f"{p['race_id']}.json"
            hon = (p.get("marks") or {}).get("◎")
            if not snap or not ff.exists() or hon is None or p.get("confidence") == "見送り":
                continue
            fo = json.loads(ff.read_text(encoding="utf-8"))
            fin = fo.get("odds") or {}
            if str(hon) not in snap or str(hon) not in fin:
                continue
            s_od = {int(k): float(v) for k, v in snap.items()}
            f_od = {int(k): float(v) for k, v in fin.items()}
            a, b = BT.tanpuku(int(hon), s_od), BT.tanpuku(int(hon), f_od)
            out.append({"date": d, "jra": p["race_id"].startswith("jra_"), "kind": fo.get("kind"), "checked": fo.get("checked"),
                        "ratio": f_od[int(hon)] / s_od[int(hon)],
                        "type_snap": a[0]["type"] if a else "なし", "type_final": b[0]["type"] if b else "なし"})
    return out


def honmei_report(rs: list[dict]) -> str:
    if not rs:
        return "◎の締め切り後（地方は直前）のオッズの記録はまだ無い"
    lines = [f"◎の 締め切り後（地方は発走直前）÷予想時 のオッズ（中央値・レース数）　対象{len(rs)}レース"]
    for k, sub in (("中央（確定）", [r for r in rs if r["jra"]]), ("地方（直前）", [r for r in rs if not r["jra"]])):
        if sub:
            sw = sum(1 for r in sub if r["type_snap"] != r["type_final"])
            lines.append(f"- {k}：{_median([r['ratio'] for r in sub]):.2f}（{len(sub)}）、単勝・複勝・なしの区分が変わる割合 {100 * sw / len(sub):.0f}%")
    chk = [r for r in rs if r["jra"] and r["checked"] is not None]
    if chk:
        lines.append(f"- 中央の確定オッズの確認：勝ち馬のオッズ×100が単勝の払戻と一致 {sum(r['checked'] for r in chk)}/{len(chk)}"
                     "（一致しないものが多いときは、夜の出馬表のオッズが確定オッズになっていない）")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="20261111")
    ap.add_argument("--until", default="99999999")
    a = ap.parse_args()
    print(report(rows(a.since, a.until)))
    print(honmei_report(honmei_rows(a.since, a.until)))


if __name__ == "__main__":
    main()
