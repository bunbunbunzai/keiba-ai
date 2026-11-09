"""◎と自信度を「補正勝率」（単勝オッズとAIの評価点を合わせた勝つ確率）で決める（2026-11-10から）。

AIは全頭の評価点・想定勝率・短評・印（AI自身の見立て）を書く。このスクリプトが
1. 補正勝率を計算する：勝つ確率 ∝ (単勝オッズから求めた市場の勝つ確率)^0.555 × exp(0.100 × 評価点の差)
   オッズが無いとき（前日夜など）は exp(0.178 × 評価点の差) だけで計算する。
   係数は過去739レース（10/25〜11/9）の1〜3着の順番から推定した（プラケット・ルース型）。
2. ◎を補正勝率1位の馬にする。AIの◎と違うときは、AIの◎を〇にし、印を順に送る（総数は変えない）。
3. 自信度を◎の補正勝率で決める：A 50%以上／B 35〜49%／C 35%未満（見送りはAIの判断のまま）。
4. 各馬に adj_pct（補正勝率%）を入れ、AIが書いた印・自信度と評価点1位は blend に残す（サイトに「AIの評価点1位」として出す）。

過去の検証（日付で分けて、学習に使っていないレースで計算）：◎の勝率28.4%→36.2%、3着内率60.7%→66.4%、
同じ買い目の型で回収率73.3%→79.9%（95%区間64〜100、差は誤差の範囲）。

  python blend.py --date 20261110            # 表示だけ
  python blend.py --date 20261110 --write    # 予想ファイルを書き換える（発走20分前を過ぎたレースは触らない）
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta

import bets as BT
from common import DATA_DIR

ROOT = DATA_DIR.parent
COEF_MKT = 0.555        # 市場の勝つ確率（対数）の係数
COEF_SCORE = 0.100      # 評価点1点あたり（オッズ込みのとき）
COEF_SCORE_ONLY = 0.178  # 評価点1点あたり（オッズが無いとき）
CONF_A, CONF_B = 0.50, 0.35
DELTA_MAX = 3            # △の上限


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def probs(pred: dict, race: dict) -> tuple[dict[int, float], str]:
    """{馬番: 補正勝率(0〜1)}, 計算の種類。評価点の無い馬は平均点として扱う。"""
    ai = {int(h["number"]): _num(h.get("score")) for h in pred.get("horses") or [] if h.get("number") is not None}
    nums = [int(h["number"]) for h in race.get("horses") or [] if h.get("number") is not None]
    nums = [n for n in nums if n in ai] or list(ai)
    od = BT.win_odds(race)
    ready = BT.odds_ready(race, od)
    if ready:
        nums = [n for n in nums if n in od]  # 取消の馬は外す
    if not nums:
        return {}, ""
    sc = [ai[n] for n in nums if ai[n] is not None]
    mean = sum(sc) / len(sc) if sc else 0.0
    s = {n: (ai[n] if ai[n] is not None else mean) - mean for n in nums}
    if ready:
        inv = {n: 1 / od[n] for n in nums}
        tot = sum(inv.values())
        u = {n: COEF_MKT * math.log(inv[n] / tot) + COEF_SCORE * s[n] for n in nums}
        kind = "オッズ込み"
    else:
        u = {n: COEF_SCORE_ONLY * s[n] for n in nums}
        kind = "評価点のみ"
    m = max(u.values())
    e = {n: math.exp(v - m) for n, v in u.items()}
    z = sum(e.values())
    return {n: v / z for n, v in e.items()}, kind


def _as_list(v) -> list[int]:
    return [int(x) for x in (v if isinstance(v, list) else [v] if v is not None else []) if x is not None]


def rotate(marks: dict, new: int) -> dict:
    """◎を new に。AIの◎は〇へ、〇は▲へ…と送り、new が持っていた印の位置で止める。"""
    m = {k: (list(v) if isinstance(v, list) else v) for k, v in (marks or {}).items()}
    old = m.get("◎")
    if old is None or int(old) == new:
        m["◎"] = new
        return m
    where = next((k for k, v in m.items() if new in _as_list(v)), None)
    o, a = m.get("〇"), m.get("▲")
    m["◎"] = new
    if where == "〇":
        m["〇"] = old
    elif where == "▲":
        m["〇"], m["▲"] = old, o
    else:
        m["〇"], m["▲"] = old, o
        if where in ("△", "☆"):
            lst = [a if x == new else x for x in _as_list(m[where])]
            m[where] = lst if isinstance(marks.get(where), list) else lst[0]
        elif a is not None:
            tri = [a] + _as_list(m.get("△"))
            m["△"] = tri[:DELTA_MAX]
    for k in ("〇", "▲"):
        if m.get(k) is None:
            m.pop(k, None)
    return m


def conf_of(p: float) -> str:
    return "A" if p >= CONF_A else "B" if p >= CONF_B else "C"


def blend(pred: dict, race: dict) -> dict | None:
    """書き換えた予想（新しい dict）を返す。見送り・材料不足なら None。"""
    if pred.get("confidence") == "見送り":
        return None
    old_blend = pred.get("blend") or {}
    # すでにこのスクリプトが書いた印のままなら、AIが書いた元の印から計算し直す（AIが書き直していればそれを使う）
    if old_blend and pred.get("marks") == old_blend.get("marks"):
        ai_marks, ai_conf = old_blend.get("ai_marks") or pred.get("marks"), old_blend.get("ai_confidence") or pred.get("confidence")
    else:
        ai_marks, ai_conf = pred.get("marks") or {}, pred.get("confidence")
    if not ai_marks or ai_marks.get("◎") is None:
        return None
    pr, kind = probs(pred, race)
    if not pr:
        return None
    new = max(pr, key=lambda n: (pr[n], n == int(ai_marks["◎"])))
    marks = rotate(ai_marks, new)
    scores = {int(h["number"]): _num(h.get("score")) for h in pred.get("horses") or [] if h.get("number") is not None}
    top_score = max((n for n in scores if scores[n] is not None), key=lambda n: (scores[n], n == int(ai_marks["◎"])), default=None)
    q = dict(pred)
    q["marks"] = marks
    q["confidence"] = conf_of(pr[new])
    q["horses"] = [dict(h, adj_pct=round(100 * pr[int(h["number"])], 1)) if h.get("number") is not None and int(h["number"]) in pr else h
                   for h in pred.get("horses") or []]
    q["blend"] = {"kind": kind, "ai_marks": ai_marks, "ai_confidence": ai_conf, "ai_top": top_score,
                  "marks": marks, "honmei_pct": round(100 * pr[new], 1)}
    return q


def apply(date: str, race_ids: list[str] | None = None, write: bool = False, force: bool = False) -> list[str]:
    changed = []
    now = datetime.now(BT.JST)
    for f in sorted((ROOT / "predictions" / date).glob("*.json")):
        pred = json.loads(f.read_text(encoding="utf-8"))
        rid = pred.get("race_id")
        if race_ids and rid not in race_ids:
            continue
        rf = DATA_DIR / "races" / date / f"{rid}.json"
        if not rf.exists():
            continue
        race = json.loads(rf.read_text(encoding="utf-8"))
        post = BT._post_dt(date, race)
        locked = post is not None and now > post - timedelta(minutes=BT.LOCK_MIN)
        q = blend(pred, race)
        if q is None:
            continue
        old_hon, new_hon = (pred.get("marks") or {}).get("◎"), q["marks"]["◎"]
        ai_hon = q["blend"]["ai_marks"].get("◎")
        diff = q["marks"] != pred.get("marks") or q["confidence"] != pred.get("confidence")
        print(f"{rid} ◎{new_hon}（補正勝率{q['blend']['honmei_pct']}%・{q['blend']['kind']}）自信度{q['confidence']}"
              + (f"　AIの◎{ai_hon}から変更" if int(ai_hon) != int(new_hon) else "")
              + ("　← 変更" if diff else "") + ("（発走20分前を過ぎたので変えない）" if diff and locked and not force else ""))
        if not write or (locked and not force):
            continue
        if pred.get("blend") and old_hon is not None and int(old_hon) != int(new_hon):
            q.setdefault("updates", []).append({"at": now.strftime("%m/%d %H:%M"),
                                                "text": f"オッズの変化で補正勝率の1位が変わったため、本命を{old_hon}番から{new_hon}番に替えた"})
        if json.dumps(q, ensure_ascii=False, sort_keys=True) != json.dumps(pred, ensure_ascii=False, sort_keys=True):
            f.write_text(json.dumps(q, ensure_ascii=False, indent=2), encoding="utf-8")
            if diff:
                changed.append(rid)
    return changed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--race", action="append", default=[])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    ch = apply(a.date, a.race or None, a.write, a.force)
    print(f"blend: {len(ch)} races changed" + (" (written)" if a.write else " (dry run)"))


if __name__ == "__main__":
    main()
