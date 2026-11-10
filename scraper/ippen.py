"""一変候補（実験）：成績が一変するかもしれない馬を毎日記録する。サイトの成績・予想には使わない。

2026-11-11から。外部の予想家の調査で、長く勝っている人は「オッズにまだ入っていない材料」を狙っていた。
その候補として次の3つを、条件を先に決めてから毎日記録し、数百頭たまったところで判定する。
1. 休み明け：前走から90日を超えて間が空いた馬
2. 前走大敗からの巻き返し：前走が下位1/3の着順（6頭立て以上）だが、その前の4走に上位1/4以内の好走がある馬
3. 前走で人気を裏切った人気薄：前走1〜3番人気で6着以下、今回は4番人気以下の馬
4. AIの独自評価（2026-11-11追加）：AIの評価点1位なのに、補正勝率（オッズ込み）では◎にならなかった馬
   （AIがオッズと違う見方をした馬。過去の少数のレースでは単勝回収率が高く出たことがあるため、成績に数えずに確かめる）
判定：条件ごとに300頭以上たまってから、単勝・複勝の回収率と95%区間を見る。区間の下限が100%を超える条件だけ、
予想の材料に入れるかを検討する（数十頭の段階の数字では判断しない）。

記録：data/ippen/<日付>.json。発走20分前を過ぎたレースの記録は書き換えない（あとから条件を変えて数字を良く見せないため）。
条件は出馬表（近走・単勝オッズ）だけで決まり、レース結果は使わない。

  python ippen.py --date 20261111          # 記録する
  python ippen.py --date 20261111 --show   # 表示だけ
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timedelta, timezone

from common import DATA_DIR

ROOT = DATA_DIR.parent
JST = timezone(timedelta(hours=9))
FORWARD_FROM = "20261111"   # これ以降は毎日の記録（前向き）。それより前は過去の出馬表に当てはめた参考
LAYOFF_DAYS = 90
LOCK_MIN = 20
JUDGE_N = 300
JRA_CODE = {"札幌": "01", "函館": "02", "福島": "03", "新潟": "04", "東京": "05", "中山": "06",
            "中京": "07", "京都": "08", "阪神": "09", "小倉": "10"}
TYPES = {
    "layoff": "休み明け（90日超）",
    "rebound": "前走大敗からの巻き返し",
    "letdown": "前走で人気を裏切った人気薄",
    "aitop": "AIの評価点1位（◎ではない馬）",
}


def _pdate(s) -> datetime | None:
    s = str(s or "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s) or re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s)
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _int(x) -> int | None:
    try:
        return int(str(x).strip())
    except (TypeError, ValueError):
        return None


def _popularity(race: dict) -> dict[int, int]:
    """今回の単勝人気。出馬表に人気があればそれを、無ければ単勝オッズの順位。"""
    od = {}
    for h in race.get("horses") or []:
        n, o = _int(h.get("number")), h.get("odds")
        try:
            o = float(o)
        except (TypeError, ValueError):
            o = 0
        if n is not None and o > 0:
            od[n] = o
    out = {}
    for h in race.get("horses") or []:
        n = _int(h.get("number"))
        if n is None:
            continue
        p = _int(h.get("popularity"))
        if p:
            out[n] = p
        elif n in od:
            out[n] = sorted(od.values()).index(od[n]) + 1
    return out


def results_key(race_id: str) -> str:
    m = re.match(r"jra_\d{8}_(.+)_(\d{2})$", str(race_id))
    return f"jra_{JRA_CODE.get(m.group(1), m.group(1))}_{m.group(2)}" if m else str(race_id)


def candidates(date: str, race: dict) -> list[dict]:
    """そのレースの一変候補。条件は出馬表だけで決まる。"""
    day = datetime.strptime(date, "%Y%m%d")
    pop = _popularity(race)
    out = []
    for h in race.get("horses") or []:
        n = _int(h.get("number"))
        past = [p for p in h.get("past") or [] if _pdate(p.get("date")) and _pdate(p.get("date")) < day]
        if n is None or not past:
            continue
        last = past[0]
        types = []
        gap = (day - _pdate(last.get("date"))).days
        if gap > LAYOFF_DAYS:
            types.append("layoff")
        fin, field, lpop = _int(last.get("finish")), _int(last.get("field")), _int(last.get("popularity"))
        if fin and field and field >= 6 and fin > field * 2 / 3:
            good = any((f := _int(p.get("finish"))) and (fl := _int(p.get("field"))) and (f == 1 or f <= fl / 4)
                       for p in past[1:5])
            if good:
                types.append("rebound")
        if fin and lpop and lpop <= 3 and fin >= 6 and pop.get(n, 0) >= 4:
            types.append("letdown")
        if types:
            odds = h.get("odds")
            try:
                odds = float(odds) if odds else None
            except (TypeError, ValueError):
                odds = None
            out.append({"number": n, "name": h.get("name"), "types": types, "gap_days": gap,
                        "last": {"date": str(last.get("date")), "finish": fin, "field": field, "popularity": lpop},
                        "odds": odds, "popularity": pop.get(n)})
    return out


def _post_dt(date: str, race: dict) -> datetime | None:
    t = str(race.get("post_time") or "")
    try:
        hh, mm = map(int, t.split(":")[:2])
        return datetime.strptime(date, "%Y%m%d").replace(hour=hh, minute=mm, tzinfo=JST)
    except ValueError:
        return None


def ai_top(date: str, race: dict) -> int | None:
    """AIの評価点1位が◎（補正勝率1位）と違うとき、その馬番。予想が無い・見送り・オッズ無しなら None。"""
    pf = ROOT / "predictions" / date / f"{race.get('race_id')}.json"
    if not pf.exists():
        return None
    try:
        pred = json.loads(pf.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if pred.get("confidence") == "見送り":
        return None
    b = pred.get("blend") or {}
    marks = pred.get("marks") or {}
    if not b:  # 11/10より前の予想は、今の決め方を当てはめる（参考）
        import blend as BL

        q = BL.blend(pred, race)
        if not q:
            return None
        b, marks = q["blend"], q["marks"]
    if b.get("kind") != "オッズ込み" or b.get("ai_top") is None or marks.get("◎") is None:
        return None
    return int(b["ai_top"]) if int(b["ai_top"]) != int(marks["◎"]) else None


def build_day(date: str) -> list[dict]:
    """その日の全レースの候補（記録の形）。"""
    rows = []
    rdir = DATA_DIR / "races" / date
    if not rdir.exists():
        return rows
    for f in sorted(rdir.glob("*.json")):
        try:
            race = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        rid = race.get("race_id") or f.stem
        cs = candidates(date, race)
        top = ai_top(date, race)
        if top is not None:
            hit = next((c for c in cs if c["number"] == top), None)
            if hit:
                hit["types"].append("aitop")
            else:
                h = next((x for x in race.get("horses") or [] if _int(x.get("number")) == top), {})
                try:
                    odds = float(h.get("odds")) if h.get("odds") else None
                except (TypeError, ValueError):
                    odds = None
                cs.append({"number": top, "name": h.get("name"), "types": ["aitop"], "odds": odds,
                           "popularity": _popularity(race).get(top)})
        for c in sorted(cs, key=lambda c: c["number"]):
            rows.append({"race_id": rid, "results_key": results_key(rid), "venue": race.get("venue"),
                         "race_no": race.get("race_no"), "post_time": race.get("post_time"), **c})
    return rows


def record(date: str, write: bool = True) -> dict:
    """data/ippen/<日付>.json を作る・更新する。発走20分前を過ぎたレースの記録は前のまま。"""
    f = DATA_DIR / "ippen" / f"{date}.json"
    old = {}
    if f.exists():
        try:
            old = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            old = {}
    now = datetime.now(JST)
    new_rows = build_day(date)
    frozen_races = set()
    for r in old.get("horses") or []:
        rf = DATA_DIR / "races" / date / f"{r['race_id']}.json"
        race = json.loads(rf.read_text(encoding="utf-8")) if rf.exists() else {}
        post = _post_dt(date, race)
        if post is None or now > post - timedelta(minutes=LOCK_MIN):
            frozen_races.add(r["race_id"])
    rows = [r for r in old.get("horses") or [] if r["race_id"] in frozen_races]
    rows += [r for r in new_rows if r["race_id"] not in frozen_races]
    rows.sort(key=lambda r: (str(r.get("post_time") or "99:99"), str(r.get("venue")), r.get("race_no") or 0, r["number"]))
    out = {"date": date, "updated": now.strftime("%Y-%m-%d %H:%M"), "types": TYPES, "horses": rows}
    if write and json.dumps(rows, ensure_ascii=False, sort_keys=True) != json.dumps(old.get("horses"), ensure_ascii=False, sort_keys=True):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def _payout(res: dict, kind: str, num: int) -> int:
    for x in (res.get("payouts") or {}).get(kind, []):
        if str(x.get("combo")) == str(num):
            return int(x.get("yen") or 0)
    return 0


def outcomes(date: str, rows: list[dict]) -> list[dict]:
    """結果が出た候補に着順・単勝・複勝の払戻を付ける（取消・結果なしは除く）。"""
    out = []
    cache: dict[str, dict] = {}
    for r in rows:
        k = r.get("results_key") or results_key(r["race_id"])
        if k not in cache:
            rf = DATA_DIR / "results" / date / f"{k}.json"
            try:
                cache[k] = json.loads(rf.read_text(encoding="utf-8")) if rf.exists() else {}
            except Exception:  # noqa: BLE001
                cache[k] = {}
        res = cache[k]
        if not res.get("payouts") or not res.get("rows"):
            continue
        fin = next((_int(x.get("finish")) for x in res["rows"] if _int(x.get("number")) == r["number"]), None)
        if fin is None:
            continue  # 取消・除外・中止
        out.append(dict(r, finish=fin, tan=_payout(res, "単勝", r["number"]), fuku=_payout(res, "複勝", r["number"])))
    return out


def summarize(items: list[dict]) -> dict:
    """{n, win, top3, tan_roi, tan_ci, fuku_roi, fuku_ci}（各100円）。区間はブートストラップ2000回の95%。"""
    import random

    n = len(items)
    if not n:
        return {"n": 0}

    def roi(xs):
        return 100 * sum(xs) / (100 * len(xs))

    tan, fuku = [x["tan"] for x in items], [x["fuku"] for x in items]
    rnd = random.Random(7)
    bt, bf = [], []
    for _ in range(2000):
        idx = [rnd.randrange(n) for _ in range(n)]
        bt.append(roi([tan[i] for i in idx]))
        bf.append(roi([fuku[i] for i in idx]))
    bt.sort(); bf.sort()
    return {"n": n, "win": 100 * sum(x["finish"] == 1 for x in items) / n,
            "top3": 100 * sum(x["finish"] <= 3 for x in items) / n,
            "tan_roi": roi(tan), "tan_ci": (bt[50], bt[1949]), "fuku_roi": roi(fuku), "fuku_ci": (bf[50], bf[1949])}


def load(date: str) -> list[dict]:
    """記録があればそれを、無ければ（FORWARD_FROMより前など）出馬表から当てはめる。"""
    f = DATA_DIR / "ippen" / f"{date}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8")).get("horses") or []
        except Exception:  # noqa: BLE001
            pass
    return build_day(date) if date < FORWARD_FROM else []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    if a.date < FORWARD_FROM and not a.show:
        print(f"{FORWARD_FROM}より前は記録しない（過去分はサイトの集計で当てはめる）")
        return
    out = record(a.date, write=not a.show)
    by = {k: sum(k in r["types"] for r in out["horses"]) for k in TYPES}
    print(f"ippen {a.date}: {len(out['horses'])}頭 " + " ".join(f"{TYPES[k]}{v}" for k, v in by.items()))


if __name__ == "__main__":
    main()
