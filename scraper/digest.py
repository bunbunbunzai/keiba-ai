"""分析用の要約：data/races/<date>/*.json を1レースずつ短いテキストにする。

使い方:
  python scraper/digest.py --date 20261026                 # 全レースの一覧（発走順）
  python scraper/digest.py --date 20261026 --race <race_id> # 1レースの詳細（全頭＋近5走）
  python scraper/digest.py --date 20261026 --pending --after 12:30  # 未予想かつ指定時刻以降に発走のレース一覧
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from common import DATA_DIR
import people

import sys as _sys
_sys.path.insert(0, str(DATA_DIR.parent / "site"))
from extra import grade_of  # noqa: E402

ROOT = DATA_DIR.parent


def races(date: str) -> list[dict]:
    out = []
    for f in sorted((DATA_DIR / "races" / date).glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        r.setdefault("race_id", f.stem)
        out.append(r)
    out.sort(key=lambda r: (r.get("post_time") or "99:99", r.get("venue") or ""))
    return out


def predicted(date: str) -> set[str]:
    return {f.stem for f in (ROOT / "predictions" / date).glob("*.json")}


def past_line(p: dict) -> str:
    raw = p.get("date") or ""
    m = re.search(r"(\d{1,2})\D(\d{1,2})\D?$", raw)
    d = f"{int(m.group(1))}/{int(m.group(2))}" if m else raw[-5:]
    parts = [
        d,
        p.get("venue") or "",
        f"{p.get('surface') or ''}{p.get('distance') or ''}",
        p.get("track") or "",
        (p.get("race_name") or p.get("class") or "")[:10],
        f"{p.get('field') or '?'}頭{p.get('popularity') or '?'}人",
        f"{p.get('finish')}着",
        f"差{p.get('margin')}" if p.get("margin") not in (None, "") else "",
        f"通{p.get('corners')}" if p.get("corners") else "",
        f"上{p.get('last3f')}" if p.get("last3f") else "",
        p.get("jockey") or "",
        f"{p.get('weight')}kg" if p.get("weight") else "",
        f"{p.get('body_weight')}" if p.get("body_weight") else "",
    ]
    return " ".join(x for x in parts if x)


def bias_line(date: str, r: dict) -> str:
    key = f"{r.get('venue')}{'芝' if r.get('surface') == '芝' else 'ダ'}"
    for src in ("jra", "rakuten"):
        f = DATA_DIR / "bias" / f"{date}_{src}.json"
        if f.exists():
            b = json.loads(f.read_text(encoding="utf-8")).get("bias", {}).get(key)
            upd = json.loads(f.read_text(encoding="utf-8")).get("updated")
            if b:
                return (f"当日バイアス：{key}＝{b['judgement']}【{b['confidence']}】（{len(b['races'])}R参照："
                        f"{','.join(map(str, b['races']))}R、連対馬の先行{int(b['front_share'] * 100)}%・内枠{int(b['inner_share'] * 100)}%・"
                        f"外枠{int(b['outer_share'] * 100)}%、{upd}時点）")
    return "当日バイアス：未判定"


def _banei_prev_weight(p: dict) -> float | None:
    """ばんえいの近走の斤量。楽天の近走は class 欄が「騎手名 660」の形。"""
    if p.get("weight"):
        try:
            return float(p["weight"])
        except (TypeError, ValueError):
            pass
    m = re.search(r"(\d{3,4})\s*$", str(p.get("class") or ""))
    return float(m.group(1)) if m else None


def banei_lines(r: dict) -> tuple[str, dict]:
    """ばんえい専用の材料（2026-11-11から）：馬場水分と、各馬の斤量・前走からの斤量差・重い順。"""
    ws = {}
    for h in r.get("horses", []):
        try:
            ws[h.get("number")] = float(h.get("weight"))
        except (TypeError, ValueError):
            pass
    order = sorted(ws.values(), reverse=True)
    per = {}
    for h in r.get("horses", []):
        w = ws.get(h.get("number"))
        if w is None:
            continue
        prev = _banei_prev_weight((h.get("past") or [{}])[0]) if h.get("past") else None
        per[h.get("number")] = (f"    ばんえい：斤量{w:.0f}kg（出走馬で重いほうから{order.index(w) + 1}番目"
                                + (f"・前走{prev:.0f}kgから{w - prev:+.0f}kg" if prev else "") + "）")
    tr = r.get("track") or "不明"
    head = (f"ばんえいの材料：馬場水分{tr}（水分が多いほど砂が締まって軽く、時計が速く先行有利。水分が少ない乾いた馬場は重く、"
            f"力と斤量の差が出やすい）。斤量は最重{order[0]:.0f}kg・最軽{order[-1]:.0f}kg。前走より斤量が大きく増えた馬は割り引く。" if order else "")
    return head, per


def detail(r: dict, date: str = "") -> str:
    head = (f"{r.get('race_id')} | {r.get('venue')}{r.get('race_no')}R {r.get('post_time') or ''} "
            f"{r.get('surface') or ''}{r.get('distance') or ''}m {r.get('field')}頭 | "
            f"{r.get('race_name') or r.get('title_text') or ''} {r.get('conditions') or ''}"
            + (f" | 天候{r['weather']}" if r.get("weather") else "") + (f" 馬場{r['track']}" if r.get("track") else ""))
    banei = str(r.get("venue") or "").startswith("帯広")
    bhead, bper = banei_lines(r) if banei else ("", {})
    lines = [head, bias_line(date, r) if date else ""] + ([bhead] if bhead else [])
    for h in r.get("horses", []):
        prof = h.get("profile") or {}
        sire = h.get("sire") or prof.get("父") or ""
        damsire = h.get("damsire") or prof.get("母の父") or ""
        lines.append(
            f"[{h.get('frame')}-{h.get('number')}] {h.get('name')} {h.get('sex_age')} {h.get('weight')}kg "
            f"{h.get('jockey')}（騎手 {people.label(date, r.get('race_id'), 'j', h.get('jockey'))}） / "
            f"{h.get('trainer')}（厩舎 {people.label(date, r.get('race_id'), 't', h.get('trainer'))}） | 父{sire} 母父{damsire} | "
            f"単勝{h.get('odds') if h.get('odds') is not None else '-'} 人気{h.get('popularity') or '-'} "
            f"体重{h.get('body_weight') or ''}{h.get('body_weight_change') or ''}")
        if h.get("number") in bper:
            lines.append(bper[h.get("number")])
        for p in (h.get("past") or [])[:5]:
            lines.append("    " + past_line(p))
        if not h.get("past"):
            lines.append("    近走データなし")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--race")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--after", default="00:00")
    a = ap.parse_args()
    rs = races(a.date)
    if a.race:
        print("\n".join(detail(r, a.date) for r in rs if r["race_id"] == a.race))
    else:
        done = predicted(a.date) if a.pending else set()
        for r in rs:
            if r["race_id"] in done or (r.get("post_time") or "99:99") < a.after:
                continue
            # 楽天は発売開始直後に「0.0（-人気）」を出すことがある。0.0 はオッズ未確定として数えない
            odds = sum(1 for h in r.get("horses", []) if h.get("odds"))
            g = grade_of(r)
            print(f"{r.get('post_time')} {r['race_id']} {r.get('venue')}{r.get('race_no')}R " + (f"【重賞:{g}】" if g else "") +
                  f"{r.get('surface') or ''}{r.get('distance') or ''} {r.get('field')}頭 オッズ{odds}/{r.get('field')}")
