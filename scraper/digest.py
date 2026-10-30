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


def detail(r: dict, date: str = "") -> str:
    head = (f"{r.get('race_id')} | {r.get('venue')}{r.get('race_no')}R {r.get('post_time') or ''} "
            f"{r.get('surface') or ''}{r.get('distance') or ''}m {r.get('field')}頭 | "
            f"{r.get('race_name') or r.get('title_text') or ''} {r.get('conditions') or ''}")
    lines = [head, bias_line(date, r) if date else ""]
    for h in r.get("horses", []):
        prof = h.get("profile") or {}
        sire = h.get("sire") or prof.get("父") or ""
        damsire = h.get("damsire") or prof.get("母の父") or ""
        lines.append(
            f"[{h.get('frame')}-{h.get('number')}] {h.get('name')} {h.get('sex_age')} {h.get('weight')}kg "
            f"{h.get('jockey')} / {h.get('trainer')} | 父{sire} 母父{damsire} | "
            f"単勝{h.get('odds') if h.get('odds') is not None else '-'} 人気{h.get('popularity') or '-'} "
            f"体重{h.get('body_weight') or ''}{h.get('body_weight_change') or ''}")
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
            odds = sum(1 for h in r.get("horses", []) if h.get("odds") is not None)
            print(f"{r.get('post_time')} {r['race_id']} {r.get('venue')}{r.get('race_no')}R "
                  f"{r.get('surface') or ''}{r.get('distance') or ''} {r.get('field')}頭 オッズ{odds}/{r.get('field')}")
