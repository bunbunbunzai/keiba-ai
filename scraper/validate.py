"""予想ファイルの検査：馬番の実在、印の重複、買い目の形式・点数。

使い方: python scraper/validate.py --date 20261026
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from common import DATA_DIR

ROOT = DATA_DIR.parent
TYPES = {"単勝": 1, "複勝": 1, "枠連": 2, "ワイド": 2, "馬連": 2, "馬単": 2, "3連複": 3, "3連単": 3}


def check(pred: dict, race: dict | None) -> list[str]:
    errs = []
    nums = {h.get("number") for h in (race or {}).get("horses", [])}
    for k in ("race_id", "results_key", "confidence", "marks", "bets", "summary", "horses"):
        if k not in pred:
            errs.append(f"{k} がない")
    if pred.get("confidence") not in ("A", "B", "C", "見送り"):
        errs.append("confidence は A/B/C/見送り")
    marked = []
    for m, v in (pred.get("marks") or {}).items():
        for n in v if isinstance(v, list) else [v]:
            if nums and n not in nums:
                errs.append(f"印{m}の馬番{n}は出走していない")
            marked.append(n)
    if len(marked) != len(set(marked)):
        errs.append("同じ馬に印が重複")
    bets = pred.get("bets") or []
    if pred.get("confidence") == "見送り" and bets:
        errs.append("見送りなのに買い目がある")
    if len(bets) > 12:
        errs.append(f"買い目が{len(bets)}点（原則10点以内）")
    for b in bets:
        t, c = b.get("type"), str(b.get("combo", ""))
        if t not in TYPES:
            errs.append(f"券種 {t} が不正")
            continue
        parts = c.split("-")
        if len(parts) != TYPES[t] or not all(re.fullmatch(r"\d+", p) for p in parts):
            errs.append(f"{t} {c} の形式が不正")
        elif t != "枠連" and nums and any(int(p) not in nums for p in parts):
            errs.append(f"{t} {c} に出走していない馬番")
        elif len(set(parts)) != len(parts):
            errs.append(f"{t} {c} に同じ番号が重複")
    return errs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    d = ap.parse_args().date
    bad = 0
    files = sorted((ROOT / "predictions" / d).glob("*.json"))
    for f in files:
        try:
            pred = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"NG {f.name}: JSONが読めない {e}")
            bad += 1
            continue
        rf = DATA_DIR / "races" / d / f"{pred.get('race_id')}.json"
        race = json.loads(rf.read_text(encoding="utf-8")) if rf.exists() else None
        errs = check(pred, race) + ([] if race else ["出馬表データがない（race_id を確認）"])
        if errs:
            bad += 1
            print(f"NG {f.name}: " + " / ".join(errs))
    print(f"{len(files)} files, {bad} with errors")
    sys.exit(1 if bad else 0)
