"""コースの形のガイド（data/course_layout/<slug>.json）をWeb検索つきの上位モデルで作る。

コース別の傾向ページ（データの集計＋解説）に、スタート地点・最初のコーナーまでの距離・コースの形など、
予想に直結する「コースの形」を足す。事実は主催者などの公開情報を調べさせ、出典を残す。
レース数の多いコースから --max-calls まで。90日以内に作ったものは作り直さない。

  python course_layout_gen.py --max-calls 40
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ai

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site"))
import course_stats as C  # noqa: E402
from course_gen import VENUE_SLUG  # noqa: E402

JST = timezone(timedelta(hours=9))
OUT = ROOT / "data" / "course_layout"

SYSTEM = (
    "あなたは競馬のデータ記者。指定されたコース（競馬場・芝ダート・距離）の「形」を、予想する人向けに説明する。"
    "スタート地点の位置、最初のコーナーまでのおおよその距離、使う回り（内回り・外回り）、コーナーの数、坂の位置、最後の直線の長さ、"
    "芝スタートのダートなどの特徴を、web_search で主催者（JRA・地方競馬の主催者）や信頼できるデータサイトを調べ、確かめられたことだけを書く。"
    "確かめられない数字は書かない。与えられた集計の数字（勝ち馬の位置取り・枠の成績）は使ってよく、形との関係を説明する。"
    "調べた記事の文章をそのまま写さず、自分の言葉で書く（引用符での引用もしない）。本文に引用タグやURLを入れない。"
    "だ・である調、絵文字なし、誇大表現なし。出力はJSONのみ（前置き・コードブロック不要）。キー："
    "facts（[{\"k\": 項目, \"v\": 内容}] を4〜7個：スタート地点、最初のコーナーまで、回り・使うコース、坂、最後の直線、その他の特徴）、"
    "text（コースの形と、それが展開や枠にどう影響するかの説明、3〜5文）、"
    "sources（実際に確認に使ったページ。[{\"url\": URL, \"title\": ページ名}] を2〜5個。検索結果に出たURLだけ）。"
)


def clean(s) -> str:
    return re.sub(r'[<(]?cite index="[^"]*">', "", str(s)).replace("</cite>", "").replace("<", "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=40)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if not ai.enabled():
        print("ANTHROPIC_API_KEY が無いので何もしない")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    stats = C.collect(30)
    today = datetime.now(JST).strftime("%Y-%m-%d")
    calls = made = 0
    for key in sorted(stats, key=lambda k: -stats[k]["races"]):
        v, s, m = key
        slug = C.course_slug(VENUE_SLUG.get(v, "venue"), s, m)
        f = OUT / f"{slug}.json"
        if f.exists() and not a.force:
            old = json.loads(f.read_text(encoding="utf-8"))
            if (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(old.get("updated", "2000-01-01"), "%Y-%m-%d")).days < 90:
                continue
        if calls >= a.max_calls or ai.too_many_failures():
            break
        calls += 1
        res = ai.ask_with_search("analysis", SYSTEM, f"コース：{v}競馬場 {C.SURF_NAME.get(s, s)}{m}m\n\n【このコースの集計（このサイトが公式結果から作成）】\n"
                                 + C.summary_text(key, stats[key], v), max_tokens=12000, max_searches=4)
        if not res or not res["text"]:
            print("生成できなかった", slug, flush=True)
            continue
        t = res["text"]
        try:
            j = json.loads(t[t.find("{"): t.rfind("}") + 1])
            assert j.get("text")
        except Exception as e:  # noqa: BLE001
            print("JSONを読めない", slug, e, t[:200], flush=True)
            continue
        seen = {x["url"] for x in res["results"]}
        srcs = [x for x in (j.get("sources") or []) if isinstance(x, dict) and x.get("url") in seen][:5] or res["sources"]
        f.write_text(json.dumps({"slug": slug, "updated": today, "text": clean(j["text"]),
                                 "facts": [{"k": clean(x.get("k")), "v": clean(x.get("v"))} for x in j.get("facts", [])[:8]],
                                 "sources": srcs}, ensure_ascii=False, indent=1), encoding="utf-8")
        made += 1
        print("ok", slug, "searches", res["searches"], "sources", len(srcs), flush=True)
    print(f"course_layout_gen: {made} layouts, {calls} calls", flush=True)


if __name__ == "__main__":
    main()
