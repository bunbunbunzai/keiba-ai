"""当日の確定結果から、場×芝ダートごとのトラックバイアスを判定する（JRA・地方共通）。

使い方: python scraper/bias.py --date 20261026 [--source jra|rakuten|all]
出力: data/bias/<date>_<source>.json と、標準出力に1行ずつの判定

判定のしかた（連対馬＝1・2着を見る）
- 先行：4角で5番手以内（12頭未満のレースは4番手以内）
- 内枠：馬番が頭数の下から1/3以内、外枠：上から1/3以内
- 脚質：連対馬のうち先行の割合が 75%以上→先行有利、35%以下→差し有利、間→フラット
- 枠  ：連対馬の内枠と外枠の割合の差が 30ポイント以上→内／外、それ未満→枠差なし
- 確度：参照レース 3未満→弱、3〜5→中（傾向がはっきりしなければ弱）、6以上→強（同）
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from common import DATA_DIR, save_json

JRA_CODE = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京", "06": "中山",
            "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}


def load(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def race_for_result(date: str, key: str, res: dict) -> dict | None:
    if key.startswith("jra_"):
        _, code, rno = key.split("_")
        venue = JRA_CODE.get(code)
        return load(DATA_DIR / "races" / date / f"jra_{date}_{venue}_{rno}.json")
    return load(DATA_DIR / "races" / date / f"{key}.json")


def pos4_of(row: dict):
    if row.get("pos4") is not None:
        return row["pos4"]
    c = re.findall(r"\d+", str(row.get("corners") or ""))
    return int(c[-1]) if c else None


def judge(date: str, source: str = "all") -> dict:
    groups = defaultdict(lambda: {"races": [], "front": 0, "inner": 0, "outer": 0, "n": 0})
    for f in sorted((DATA_DIR / "results" / date).glob("*.json")):
        if f.name == "score.json":
            continue
        if source == "jra" and not f.stem.startswith("jra_") or source == "rakuten" and f.stem.startswith("jra_"):
            continue
        res = load(f) or {}
        rows = res.get("rows") or []
        race = race_for_result(date, f.stem, res)
        if not rows or not race or not res.get("payouts"):
            continue
        field = race.get("field") or len(rows)
        surf = race.get("surface") or "?"
        if surf == "障":
            continue
        key = f"{race.get('venue')}{'芝' if surf == '芝' else 'ダ'}"
        g = groups[key]
        top2 = [r for r in rows if str(r.get("finish")) in ("1", "2")]
        if len(top2) < 2:
            continue
        g["races"].append(race.get("race_no"))
        lim = 5 if field >= 12 else 4
        for r in top2:
            p4 = pos4_of(r)
            n = r.get("number")
            if p4 is None or n is None:
                continue
            g["n"] += 1
            g["front"] += p4 <= lim
            g["inner"] += n <= max(1, round(field / 3))
            g["outer"] += n > field - max(1, round(field / 3))
    out = {}
    for key, g in groups.items():
        k = len(g["races"])
        if not g["n"]:
            continue
        fr = g["front"] / g["n"]
        inn, outr = g["inner"] / g["n"], g["outer"] / g["n"]
        style = "先行有利" if fr >= 0.75 else "差し有利" if fr <= 0.35 else "フラット"
        lane = "内" if inn - outr >= 0.3 else "外" if outr - inn >= 0.3 else "枠差なし"
        clear = style != "フラット" or lane != "枠差なし"
        conf = "弱" if k < 3 else ("中" if clear else "弱") if k <= 5 else ("強" if clear and (fr >= 0.85 or fr <= 0.25) else "中")
        label = {("先行有利", "内"): "内先行", ("差し有利", "外"): "外差し"}.get((style, lane), f"{style}・{lane}" if lane != "枠差なし" else style)
        out[key] = {"judgement": label, "confidence": conf, "races": sorted(r for r in g["races"] if r),
                    "front_share": round(fr, 2), "inner_share": round(inn, 2), "outer_share": round(outr, 2),
                    "horses": g["n"]}
    now = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
    data = {"date": date, "updated": now, "bias": out}
    save_json(f"bias/{date}_{source}.json", data)
    return data


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--source", default="all")
    a = ap.parse_args()
    d = judge(a.date, a.source)
    for k, v in sorted(d["bias"].items()):
        print(f"{k}＝{v['judgement']}【{v['confidence']}】（{len(v['races'])}R参照：{','.join(map(str, v['races']))}R、先行{int(v['front_share']*100)}%・内{int(v['inner_share']*100)}%・外{int(v['outer_share']*100)}%）")
