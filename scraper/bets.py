"""買い目をオッズから組む（PREDICT.md「買い目の型」をプログラムにしたもの）。

印と自信度はAIが決め、買い目はこのスクリプトが決める。
- ◎の単複（1点）：◎が1〜2番人気または単勝3.9倍以下 → 複勝、3〜5番人気（4.0〜9.9倍）→ 単勝、6番人気以下 → なし。
  オッズが無ければ複勝。
- 3連複フォーメーション（◎→〇▲→印全部）は自信度Aのレースだけ。オッズを見て、
  当たっても購入額の合計を下回る組み合わせ（トリガミ）を外す。外すと購入額が減るので、残りがすべて
  購入額以上になるまで繰り返す。2点以上残ったら買う。3連複を買うときは複勝は買わない
  （◎が3着以内に来ても3連複が外れると、複勝だけでは購入額を取り戻せないため）。
- 3連複のオッズは、発表オッズ（data/odds/<日付>/<race_id>.json）があればそれを、無ければ単勝オッズからの推定を使う。
  推定はハーヴィル法（各馬の勝つ確率を単勝オッズから求め、3頭が3着以内に入る確率を順番の全パターンで足す）で、
  過去503レースの実際の3連複配当で較正した（実際の配当は素の推定の約0.59倍。順位の相関0.71）。
  低い組み合わせでは推定は発表オッズの約半分に出る（=トリガミ判定では安全側）。
  発表オッズを使うときは、締め切りまでの下落を見込んで8割の値で判定する（表示は発表オッズのまま）。

  python bets.py --date 20261108                # 結果を表示するだけ
  python bets.py --date 20261108 --write        # 予想ファイルの bets を書き換える（発走20分前を過ぎたレースは触らない）
  python bets.py --date 20261108 --race jra_20261108_東京_11 --write
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from itertools import permutations

from common import DATA_DIR

ROOT = DATA_DIR.parent
JST = timezone(timedelta(hours=9))
PAYOUT = 0.75   # 3連複の払戻率の目安
LAM = 0.9       # 2着・3着の確率をならす係数（人気馬が2・3着に来る確率の過大評価を抑える）
CAL = 0.59      # 較正係数（実際の配当／素の推定の中央値。2026-11-08に過去503レースで推定）
MIN_TRIO = 2    # 3連複は2点以上残ったときだけ買う
PUB_SAFETY = 0.8  # 発表オッズは締め切りまでに人気の組み合わせほど下がるので、判定は8割で行う（予想時→確定で◎の単勝は中央値0.72倍）
LOCK_MIN = 20   # 発走20分前を過ぎたら買い目を変えない


def _int_list(v) -> list[int]:
    out = []
    for x in v if isinstance(v, list) else [v] if v is not None else []:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            pass
    return out


def win_odds(race: dict) -> dict[int, float]:
    """出走馬の単勝オッズ（取消などでオッズが無い馬は入れない）。"""
    od = {}
    for h in race.get("horses") or []:
        try:
            n, o = int(h.get("number")), float(h.get("odds") or 0)
        except (TypeError, ValueError):
            continue
        if o > 0:
            od[n] = o
    return od


def odds_ready(race: dict, od: dict[int, float]) -> bool:
    """単勝オッズがほぼ全頭そろっているか（取消1頭までは許す）。"""
    n = len([h for h in race.get("horses") or [] if h.get("number") is not None])
    return n >= 3 and len(od) >= max(3, n - 1)


def popularity(od: dict[int, float], num: int) -> int | None:
    if num not in od:
        return None
    return sorted(od.values()).index(od[num]) + 1


def _market(od: dict[int, float]) -> dict[int, float]:
    inv = {k: 1 / v for k, v in od.items()}
    s = sum(inv.values())
    return {k: v / s for k, v in inv.items()}


def trio_prob(p: dict[int, float], combo: tuple[int, int, int]) -> float:
    q = {k: v ** LAM for k, v in p.items()}
    s = sum(q.values())
    q = {k: v / s for k, v in q.items()}
    tot = 0.0
    for a, b, c in permutations(combo):
        if q[a] + q[b] >= 1:
            continue
        tot += p[a] * q[b] / (1 - q[a]) * q[c] / (1 - q[a] - q[b])
    return tot


def est_trio(od: dict[int, float], combo: tuple[int, int, int]) -> float | None:
    if any(c not in od for c in combo):
        return None
    pr = trio_prob(_market(od), combo)
    return round(PAYOUT / pr * CAL, 1) if pr > 0 else None


def load_trio(date: str, race_id: str) -> dict | None:
    f = DATA_DIR / "odds" / date / f"{race_id}.json"
    if not f.exists():
        return None
    try:
        j = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return j if j.get("3連複") else None


def tanpuku(hon: int, od: dict[int, float]) -> list[dict]:
    o, pop = od.get(hon), popularity(od, hon)
    if not od or o is None:
        return [{"type": "複勝", "combo": str(hon)}]
    if (pop and pop <= 2) or o < 4.0:
        return [{"type": "複勝", "combo": str(hon)}]
    if (pop and pop <= 5) or o < 10.0:
        return [{"type": "単勝", "combo": str(hon), "odds": o}]
    return []


def formation(pred: dict, scratched: set[int]) -> list[tuple[int, int, int]]:
    m = pred.get("marks") or {}
    hon = _int_list(m.get("◎"))
    if not hon:
        return []
    hon = hon[0]
    second = [x for x in _int_list(m.get("〇")) + _int_list(m.get("▲")) if x != hon and x not in scratched]
    third = second + [x for x in _int_list(m.get("△")) + _int_list(m.get("☆")) if x != hon and x not in scratched]
    return sorted({tuple(sorted((hon, a, b))) for a in second for b in third if a != b})


def build(pred: dict, race: dict, trio: dict | None = None) -> tuple[list[dict], str]:
    """(買い目, 読者向けの一言) を返す。"""
    if pred.get("confidence") == "見送り":
        return [], ""
    hon = _int_list((pred.get("marks") or {}).get("◎"))
    if not hon:
        return [], ""
    hon = hon[0]
    od = win_odds(race)
    ready = odds_ready(race, od)
    tp = tanpuku(hon, od if ready else {})
    if pred.get("confidence") != "A":
        return tp, ""
    real = (trio or {}).get("3連複") or {}
    if not ready and not real:
        return tp, "3連複はオッズが出てから組む（オッズが出る前は◎の単複だけ）"
    scratched = ({int(h["number"]) for h in race.get("horses") or [] if h.get("number") is not None} - set(od)) if ready else set()
    cands = formation(pred, scratched)
    if not cands:
        return tp, ""
    odds_of = {}
    for c in cands:
        k = "-".join(map(str, c))
        if real.get(k):
            odds_of[c] = (float(real[k]), "発表")
        elif ready:
            e = est_trio(od, c)
            if e:
                odds_of[c] = (e, "推定")
    base = [b for b in tp if b["type"] == "単勝"]  # 3連複を買うときは複勝を買わない
    keep = [c for c in cands if c in odds_of]
    judge = {c: v * (PUB_SAFETY if kind == "発表" else 1.0) for c, (v, kind) in odds_of.items()}
    while keep:
        stake = 100 * (len(base) + len(keep))
        nxt = [c for c in keep if judge[c] * 100 >= stake]
        if len(nxt) == len(keep):
            break
        keep = nxt
    dropped = len(cands) - len(keep)
    if len(keep) < MIN_TRIO:
        return tp, "3連複は、当たっても購入額を下回る組み合わせばかりだったため買わない"
    kinds = {odds_of[c][1] for c in keep}
    src = "発表オッズ" if kinds == {"発表"} else "単勝オッズからの推定" if kinds == {"推定"} else "発表オッズと推定"
    bets = base + [{"type": "3連複", "combo": "-".join(map(str, c)), "odds": odds_of[c][0], "odds_src": odds_of[c][1]}
                   for c in sorted(keep, key=lambda c: odds_of[c][0])]
    note = f"3連複は{src}で、当たれば購入額（{100 * len(bets):,}円）以上になる組み合わせだけ"
    if dropped:
        note += f"（当たっても購入額を下回る{dropped}点を外した）"
    if trio and trio.get("fetched_at"):
        note += f"。オッズは{trio['fetched_at']}時点"
    return bets, note


def _post_dt(date: str, race: dict) -> datetime | None:
    t = str(race.get("post_time") or "")
    try:
        h, m = map(int, t.split(":")[:2])
        return datetime.strptime(date, "%Y%m%d").replace(hour=h, minute=m, tzinfo=JST)
    except ValueError:
        return None


def _same(a: list[dict], b: list[dict]) -> bool:
    key = lambda x: [(y.get("type"), str(y.get("combo"))) for y in x]  # noqa: E731
    return sorted(key(a)) == sorted(key(b))


def apply(date: str, race_ids: list[str] | None = None, write: bool = False, force: bool = False,
          reason: str = "") -> list[str]:
    """予想ファイルの買い目を作り直す。変えたレースの race_id を返す。"""
    changed = []
    now = datetime.now(JST)
    for f in sorted((ROOT / "predictions" / date).glob("*.json")):
        pred = json.loads(f.read_text(encoding="utf-8"))
        rid = pred.get("race_id")
        if race_ids and rid not in race_ids:
            continue
        rf = DATA_DIR / "races" / date / f"{rid}.json"
        if not rf.exists():
            continue
        race = json.loads(rf.read_text(encoding="utf-8"))
        post = _post_dt(date, race)
        locked = post is not None and now > post - timedelta(minutes=LOCK_MIN)
        bets, note = build(pred, race, load_trio(date, rid))
        old = pred.get("bets") or []
        same = _same(old, bets)
        line = (f"{rid} 自信度{pred.get('confidence')} "
                + " / ".join(f"{b['type']}{b['combo']}" + (f"({b['odds']}倍)" if b.get("odds") else "") for b in bets)
                + (f" ／{note}" if note else "") + ("" if same else "  ← 変更" + ("（発走20分前を過ぎたので変えない）" if locked and not force else "")))
        print(line)
        if not write or (locked and not force):
            continue
        if same and pred.get("bet_note", "") == note and all(b.get("odds") == o.get("odds") for b, o in zip(sorted(bets, key=str), sorted(old, key=str))):
            continue
        pred["bets"], pred["bet_note"] = bets, note
        if not same and old:
            ups = pred.setdefault("updates", [])
            ups.append({"at": now.strftime("%m/%d %H:%M"), "text": reason or "オッズを見て買い目を組み直した（当たっても購入額を下回る3連複の組み合わせを外す）"})
        f.write_text(json.dumps(pred, ensure_ascii=False, indent=1), encoding="utf-8")
        if not same:
            changed.append(rid)
    return changed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--race", action="append", default=[])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--force", action="store_true", help="発走20分前を過ぎたレースも書き換える（検証用）")
    a = ap.parse_args()
    ch = apply(a.date, a.race or None, a.write, a.force)
    print(f"bets: {len(ch)} races changed" + (" (written)" if a.write else " (dry run)"))


if __name__ == "__main__":
    main()
