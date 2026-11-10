"""締め切り後（確定）・発走直前の単勝オッズと人気を、全頭分残す（2026-11-11から）。

予想に使ったオッズ（予想ファイルの blend.odds）と比べて、締め切りまでにどれだけ動いたか、
◎の単勝と複勝の切り替え（4倍・10倍の境目）がずれていなかったかを odds_drift.py で測るため。

- 中央（JRA）：夜の取得（daily.yml の night）で出馬表を取り直すと、締め切り後のオッズが載っている。
  それを kind="確定" として残す（出馬表のファイルは取り直す前の内容に戻す）。勝ち馬のオッズ×100 が単勝の払戻と一致するか（checked）も記録する。
- 地方（楽天）：楽天は締め切り後のオッズのページが読めない（発売終了後は空になる）ため、
  発走の2〜12分前に出馬表を取り直したときのオッズを kind="直前" として残す（live.py が呼ぶ）。

保存先：data/final_odds/<日付>/<race_id>.json
  {"race_id", "kind": "確定"|"直前", "fetched_at": "HH:MM", "min_before": 発走何分前, "odds": {"1": 3.4, ...},
   "popularity": {"1": 2, ...}, "checked": true|false|null}

  python final_odds.py --date 20261115 --source jra     # 夜：中央の出馬表を取り直して確定オッズを残す
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from common import DATA_DIR, save_json

JST = timezone(timedelta(hours=9))


def _odds_pop(race: dict) -> tuple[dict[str, float], dict[str, int]]:
    od, pop = {}, {}
    for h in race.get("horses") or []:
        n = h.get("number")
        try:
            o = float(h.get("odds") or 0)
        except (TypeError, ValueError):
            o = 0
        if n is None or o <= 0:
            continue
        od[str(n)] = o
        if h.get("popularity"):
            pop[str(n)] = int(h["popularity"])
    if od and not pop:
        vals = sorted(od.values())
        pop = {k: vals.index(v) + 1 for k, v in od.items()}
    return od, pop


def _results_key(rid: str) -> str:
    import ippen

    return ippen.results_key(rid)


def check(date: str, rid: str, od: dict[str, float]) -> bool | None:
    """勝ち馬のオッズ×100 が単勝の払戻と一致するか（確定オッズかどうかの確認）。結果が無ければ None。"""
    rf = DATA_DIR / "results" / date / f"{_results_key(rid)}.json"
    if not rf.exists():
        return None
    try:
        res = json.loads(rf.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    tan = (res.get("payouts") or {}).get("単勝") or []
    if len(tan) != 1 or str(tan[0].get("combo")) not in od:
        return None
    return round(od[str(tan[0]["combo"])] * 100) == int(tan[0].get("yen") or 0)


def snapshot(date: str, rid: str, kind: str, overwrite: bool = True) -> dict | None:
    """出馬表（data/races）の今のオッズを final_odds に残す。"""
    rf = DATA_DIR / "races" / date / f"{rid}.json"
    out_f = DATA_DIR / "final_odds" / date / f"{rid}.json"
    if not rf.exists() or (out_f.exists() and not overwrite):
        return None
    return snapshot_race(date, rid, json.loads(rf.read_text(encoding="utf-8")), kind)


def snapshot_race(date: str, rid: str, race: dict, kind: str) -> dict | None:
    od, pop = _odds_pop(race)
    if not od:
        return None
    now = datetime.now(JST)
    mb = None
    try:
        hh, mm = map(int, str(race.get("post_time") or "").split(":")[:2])
        mb = round((datetime.strptime(date, "%Y%m%d").replace(hour=hh, minute=mm, tzinfo=JST) - now).total_seconds() / 60)
    except ValueError:
        pass
    rec = {"race_id": rid, "kind": kind, "fetched_at": now.strftime("%H:%M"), "min_before": mb,
           "odds": od, "popularity": pop, "checked": check(date, rid, od)}
    save_json(f"final_odds/{date}/{rid}.json", rec)
    return rec


def jra_night(date: str) -> int:
    """中央の出馬表を取り直して締め切り後のオッズを残し、出馬表のオッズは取り直す前に戻す
    （出馬表のオッズは「予想時に見られたオッズ」として過去の検証に使うので、確定オッズで上書きしない）。"""
    import jra_cards

    files = sorted((DATA_DIR / "races" / date).glob("jra_*.json"))
    pre = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in files}
    try:
        jra_cards.run(date, past=0)
        n = ok = 0
        for f in sorted((DATA_DIR / "races" / date).glob("jra_*.json")):
            rec = snapshot(date, f.stem, "確定")
            if rec:
                n += 1
                ok += rec["checked"] is True
    finally:
        for rid, race in pre.items():  # 取り直す前の出馬表に戻す
            save_json(f"races/{date}/{rid}.json", race)
    print(f"final_odds jra {date}: {n}レース（勝ち馬のオッズが単勝の払戻と一致 {ok}）")
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--source", default="jra", choices=["jra"])
    a = ap.parse_args()
    jra_night(a.date)


if __name__ == "__main__":
    main()
