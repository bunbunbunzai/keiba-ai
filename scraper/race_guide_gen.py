"""重賞のレースガイド（data/race_guides/<slug>.json）をWeb検索つきの上位モデルで作る。

材料：そのレースのコース（例年の条件）の過去の公式結果の集計（あれば）。
レースの条件・歴史・過去の傾向・ステップレースは Web 検索で確かめさせ、出典は実際の検索結果のURLだけ残す。
60日以内に作ったものは作り直さない（--force で作り直し）。

  python race_guide_gen.py --max-calls 60
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ai
from race_guides import RACES

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site"))
import course_stats as C  # noqa: E402

JST = timezone(timedelta(hours=9))
OUT = ROOT / "data" / "race_guides"

SYSTEM = (
    "あなたは競馬のデータ記者。指定された重賞レースについて、予想する人のためのレースガイドを書く。"
    "施行条件（競馬場・距離・出走条件・負担重量の方式・例年の時期）、レースの歴史と位置づけ、過去の傾向（人気・枠・脚質・前走のレースなど）、"
    "主な前哨戦（ステップレース）は web_search で主催者や信頼できる報道・データサイトを調べ、確かめられたことだけを書く。"
    "過去の傾向を書くときは、何年分のデータかを必ず書く。確かめられない数字や、年によって変わる条件は断定しない。"
    "与えられた「このコースの過去の集計」は、このサイトが公式結果から作ったもので、そのレース単体ではなく同じコースの全レースの数字である。使うときはそう書く。"
    "調べた記事の文章をそのまま写さず、自分の言葉で短く書き直す（引用符での引用もしない）。本文に引用タグやURLを入れない。"
    "読者は競馬を始めたばかりの人も含む。だ・である調、絵文字なし、誇大表現なし、馬券の購入を勧めない。"
    "出力はJSONのみ（前置き・コードブロック不要）。キー：lead（2〜3文の要約）、"
    "facts（[{\"k\": 項目, \"v\": 内容}] を5〜8個。例：格付け、競馬場・距離、出走条件、負担重量、例年の時期、主な前哨戦）、"
    "sections（[{\"h\": 見出し, \"text\": 3〜6文}] を4つ：「レースの特徴と歴史」「過去の傾向」「主な前哨戦」「予想のポイント」）、"
    "sources（実際に事実の確認に使ったページ。[{\"url\": URL, \"title\": ページ名}] を2〜6個。検索結果に出たURLだけ）。"
)

SLUG_V = {"東京": "tokyo", "中山": "nakayama", "京都": "kyoto", "阪神": "hanshin", "中京": "chukyo", "福島": "fukushima", "新潟": "niigata",
          "札幌": "sapporo", "函館": "hakodate", "小倉": "kokura", "大井": "ooi", "船橋": "funabashi", "川崎": "kawasaki", "浦和": "urawa",
          "盛岡": "morioka", "園田": "sonoda", "名古屋": "nagoya", "帯広": "obihiro"}


def clean(s) -> str:
    return re.sub(r'[<(]?cite index="[^"]*">', "", str(s)).replace("</cite>", "").replace("<", "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=60)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    if not ai.enabled():
        print("ANTHROPIC_API_KEY が無いので何もしない")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    stats = C.collect(20)
    today = datetime.now(JST).strftime("%Y-%m-%d")
    calls = made = 0
    for slug, name, grade, venue, surf, dist in RACES:
        if a.only and slug not in a.only.split(","):
            continue
        f = OUT / f"{slug}.json"
        if f.exists() and not a.force:
            old = json.loads(f.read_text(encoding="utf-8"))
            if (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(old.get("updated", "2000-01-01"), "%Y-%m-%d")).days < 60:
                continue
        if calls >= a.max_calls or ai.too_many_failures():
            break
        calls += 1
        key = (venue, surf, dist)
        data = C.summary_text(key, stats[key], venue) if key in stats else "（このコースの過去の集計はまだ無い）"
        user = (f"レース：{name}（{grade}）\n例年の条件（確かめること）：{venue}競馬場 {C.SURF_NAME.get(surf, surf)}{dist}m\n\n"
                f"【このコースの過去の集計（このサイトが公式結果から作成）】\n{data}")
        res = ai.ask_with_search("analysis", SYSTEM, user, max_tokens=16000, max_searches=5)
        if not res or not res["text"]:
            print("生成できなかった", slug, flush=True)
            continue
        t = res["text"]
        try:
            j = json.loads(t[t.find("{"): t.rfind("}") + 1])
            assert j.get("lead") and j.get("sections")
        except Exception as e:  # noqa: BLE001
            print("JSONを読めない", slug, e, t[:200], flush=True)
            continue
        seen = {x["url"] for x in res["results"]}
        srcs = [x for x in (j.get("sources") or []) if isinstance(x, dict) and x.get("url") in seen][:6] or res["sources"]
        f.write_text(json.dumps({
            "slug": slug, "name": name, "grade": grade, "venue": venue, "surface": surf, "distance": dist,
            "course_slug": C.course_slug(SLUG_V.get(venue, "venue"), surf, dist) if key in stats else None,
            "updated": today, "lead": clean(j["lead"]),
            "facts": [{"k": clean(x.get("k")), "v": clean(x.get("v"))} for x in j.get("facts", [])[:10]],
            "sections": [{"h": clean(x.get("h")), "text": clean(x.get("text"))} for x in j["sections"][:5]],
            "sources": srcs, "searches": res["searches"]}, ensure_ascii=False, indent=1), encoding="utf-8")
        made += 1
        print("ok", slug, "searches", res["searches"], "sources", len(srcs), flush=True)
    print(f"race_guide_gen: {made} guides, {calls} calls", flush=True)


if __name__ == "__main__":
    main()
