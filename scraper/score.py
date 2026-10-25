"""予想と結果を照合して回収率を出す（各点100円の均等買い）。

予想ファイル predictions/<date>/<race_id>.json の形式:
{
  "race_id": "...", "results_key": "jra_08_11" または楽天のRACEID,
  "marks": {"◎": 9, "〇": 8, "▲": 6, "△": [1, 2], "☆": [14]},
  "confidence": "B",            # A/B/C/見送り
  "bets": [{"type": "3連複", "combo": "6-8-9"}, {"type": "ワイド", "combo": "6-9"}, {"type": "複勝", "combo": "6"}]
}
出力: results/<date>/score.json と ledger.csv（全期間の1レース1行の記録）
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from common import DATA_DIR

ROOT = DATA_DIR.parent
UNORDERED = {"複勝", "枠連", "ワイド", "馬連", "3連複"}


def norm(kind: str, combo: str) -> str:
    parts = [str(int(x)) for x in str(combo).replace("－", "-").split("-") if x.strip()]
    return "-".join(sorted(parts, key=int) if kind in UNORDERED else parts)


def first(rows, pos):
    return next((r["number"] for r in rows if str(r.get("finish")) == str(pos)), None)


def score_race(pred: dict, res: dict) -> dict:
    pay = {k: {norm(k, p["combo"]): p["yen"] for p in v} for k, v in res.get("payouts", {}).items()}
    bets = pred.get("bets", [])
    stake = 100 * len(bets)
    ret = 0
    hits = []
    for b in bets:
        y = pay.get(b["type"], {}).get(norm(b["type"], b["combo"]))
        if y:
            ret += y
            hits.append(f'{b["type"]} {b["combo"]} {y}円')
    rows = res.get("rows", [])
    fin = {r["number"]: r.get("finish") for r in rows if r.get("number") is not None}
    hon = pred.get("marks", {}).get("◎")
    top3 = [first(rows, i) for i in (1, 2, 3)]
    return {
        "race_id": pred["race_id"],
        "confidence": pred.get("confidence"),
        "honmei": hon,
        "honmei_finish": fin.get(hon),
        "top3": top3,
        "stake": stake,
        "return": ret,
        "hits": hits,
        "voided": not res.get("payouts") or all(k.startswith("_") for k in res.get("payouts", {})),
    }


def run(date: str) -> dict:
    pdir = ROOT / "predictions" / date
    rdir = DATA_DIR / "results" / date
    races = []
    for pf in sorted(pdir.glob("*.json")):
        pred = json.loads(pf.read_text(encoding="utf-8"))
        rf = rdir / f'{pred.get("results_key", pred["race_id"])}.json'
        if not rf.exists():
            races.append({"race_id": pred["race_id"], "status": "結果未取得"})
            continue
        races.append(score_race(pred, json.loads(rf.read_text(encoding="utf-8"))))
    done = [r for r in races if "stake" in r and not r["voided"]]
    stake = sum(r["stake"] for r in done)
    ret = sum(r["return"] for r in done)
    summary = {
        "date": date,
        "races_scored": len(done),
        "stake": stake,
        "return": ret,
        "roi": round(100 * ret / stake, 1) if stake else None,
        "hit_races": sum(1 for r in done if r["return"] > 0),
        "honmei_win": sum(1 for r in done if str(r["honmei_finish"]) == "1"),
        "honmei_top3": sum(1 for r in done if str(r["honmei_finish"]) in ("1", "2", "3")),
        "races": races,
    }
    (rdir).mkdir(parents=True, exist_ok=True)
    (rdir / "score.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    ledger = ROOT / "results_ledger.csv"
    old = []
    if ledger.exists():
        with ledger.open(encoding="utf-8") as f:
            old = [r for r in csv.DictReader(f) if r["date"] != date]
    new = [{"date": date, "race_id": r["race_id"], "confidence": r["confidence"], "honmei": r["honmei"],
            "honmei_finish": r["honmei_finish"], "stake": r["stake"], "return": r["return"],
            "hits": " / ".join(r["hits"])} for r in done]
    with ledger.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "race_id", "confidence", "honmei", "honmei_finish", "stake", "return", "hits"])
        w.writeheader()
        w.writerows(old + new)
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    s = run(ap.parse_args().date)
    print({k: v for k, v in s.items() if k != "races"})
