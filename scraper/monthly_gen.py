"""月次レポートに載せる分析（data/monthly_notes/<YYYY-MM>.json）を上位モデルで書く。週間振り返りと同じ材料を1か月分。

  python monthly_gen.py --month 2026-10
"""
from __future__ import annotations

import argparse
import calendar
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ai
import weekly_gen as W

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
SYSTEM = W.SYSTEM.replace("1週間分", "1か月分").replace("この週", "この月").replace("来週", "来月")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", default="")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    now = datetime.now(JST)
    ym = a.month or (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")  # 既定は先月
    f = ROOT / "data" / "monthly_notes" / f"{ym}.json"
    if f.exists() and not a.force:
        print("作成済み", ym)
        return
    if not ai.enabled():
        print("ANTHROPIC_API_KEY が無いので何もしない")
        return
    y, m = int(ym[:4]), int(ym[5:])
    d0, d1 = f"{y}{m:02d}01", f"{y}{m:02d}{calendar.monthrange(y, m)[1]:02d}"
    rows = W.rows_for(d0, d1)
    if len(rows) < 30:
        print("レースが少ないので作らない", len(rows))
        return
    tables = "\n\n".join([
        W.table("全体", W.agg(rows, lambda x: "全体")),
        W.table("自信度別", W.agg(rows, lambda x: f"自信度{x['conf']}"), ["自信度A", "自信度B", "自信度C"]),
        W.table("◎の人気別", W.agg(rows, W.pop_band), ["1番人気", "2番人気", "3〜5番人気", "6番人気以下", "人気不明（オッズ未取得）"]),
        W.table("場別", W.agg(rows, lambda x: x["venue"])),
    ])
    listing = "\n".join(
        f"{x['d'][4:6]}/{x['d'][6:]} {x['label']}（{x['course']}・{x['field']}頭{'・重賞' if x['graded'] else ''}）自信度{x['conf']} "
        f"◎{x['hon']}（{x['hon_pop'] or '?'}番人気）→{x['hon_fin'] or '-'}着／1〜3着の印 {'・'.join(x['top3_marks'])}／購入{x['stake']}円 払戻{x['ret']}円"
        for x in rows)
    text = ai.ask("analysis", SYSTEM, f"対象：{y}年{m}月の{len(rows)}レース\n\n【集計表】\n{tables}\n\n【全レースの一覧】\n{listing}", max_tokens=16000)
    if not text:
        print("生成できなかった")
        return
    j = ai.parse_json(text)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"ym": ym, "updated": now.strftime("%Y-%m-%d"), "races": len(rows), **j}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", f.name)


if __name__ == "__main__":
    main()
