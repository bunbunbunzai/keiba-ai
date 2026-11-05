"""初心者向けの入門ガイド記事（columns/guide-<slug>.md）をWeb検索つきの上位モデルで書く。

制度・手順（ネット投票の申込み、購入方法、年齢制限など）は Web 検索で主催者の公式情報を確かめさせ、出典を残す。
既にある記事は作り直さない（--force で作り直し）。

  python guide_gen.py --max-calls 12
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ai

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))

TOPICS = [
    ("keiba-hajimekata", "競馬の始め方：最初に知っておきたいことと、はじめの一歩"),
    ("jra-baken-kaikata", "JRA（中央競馬）の馬券の買い方：競馬場・ウインズ・ネット投票"),
    ("chiho-baken-kaikata", "地方競馬の馬券の買い方：ネット投票の種類と選び方"),
    ("shutsuba-yomikata", "出馬表の見方：馬番・枠・斤量・前走成績の読み方"),
    ("keiba-shinbun", "競馬新聞（出馬表の情報）の読み方：印・近走・調教欄"),
    ("paddock-mikata", "パドックの見方：初心者が見るべきポイント"),
    ("keibajo-kansen", "初めての競馬場観戦ガイド：入場から馬券購入、レース観戦まで"),
    ("race-class", "競馬のクラスと格付けの仕組み：新馬戦からGⅠまで、地方のクラスも"),
    ("yosou-tejun", "初心者向け 競馬予想の手順：5つのステップ"),
    ("yosan-kimekata", "馬券の予算の決め方：無理なく楽しむためのルールと相談窓口"),
]

SYSTEM = (
    "あなたは競馬の入門書の編集者。指定されたテーマで、競馬を始めたばかりの人向けのガイド記事を書く。"
    "制度・手順・年齢制限・購入方法・サービス名などの事実は web_search で主催者（JRA・地方競馬の主催者）や公式サービスの情報を調べ、確かめられたことだけを書く。"
    "年や時期で変わりうる内容は「（記事作成時点）」と書くか、公式サイトで確認するよう書く。"
    "調べた記事の文章をそのまま写さず、自分の言葉で書く（引用符での引用もしない）。本文に引用タグやURLを入れない。"
    "だ・である調、絵文字なし、誇大表現なし。馬券の購入を勧めない。20歳未満は馬券を買えないことに触れる。"
    "依存症や使いすぎの相談窓口に触れる場合は、公式に案内されている窓口を調べて書く。"
    "出力はJSONのみ（前置き・コードブロック不要）。キー：description（検索結果用、100字前後）、lead（記事の結論、2〜3文）、"
    "sections（[{\"h\": 見出し, \"text\": 本文（段落は空行で区切る、合計3〜8文）, \"points\": 箇条書き（0〜5個の短い文）}] を4〜6個）、"
    "sources（実際に事実の確認に使ったページ。[{\"url\": URL, \"title\": ページ名}] を2〜6個。検索結果に出たURLだけ）。"
)


def clean(s) -> str:
    return re.sub(r'[<(]?cite index="[^"]*">', "", str(s)).replace("</cite>", "").replace("<", "").replace(">", "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=12)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if not ai.enabled():
        print("ANTHROPIC_API_KEY が無いので何もしない")
        return
    today = datetime.now(JST).strftime("%Y-%m-%d")
    calls = made = 0
    for i, (slug, title) in enumerate(TOPICS):
        f = ROOT / "columns" / f"guide-{slug}.md"
        if f.exists() and not a.force:
            continue
        if calls >= a.max_calls or ai.too_many_failures():
            break
        calls += 1
        res = ai.ask_with_search("analysis", SYSTEM, f"テーマ：{title}", max_tokens=16000, max_searches=5)
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
        body = []
        for sec in j["sections"]:
            body += [f"## {clean(sec.get('h'))}", "", clean(sec.get("text")), ""]
            pts = [clean(x) for x in sec.get("points") or [] if x]
            if pts:
                body += [f"- {x}" for x in pts] + [""]
        if srcs:
            body += ["## 出典", ""] + [f"- [{clean(x['title'])}]({x['url']})" for x in srcs if str(x.get("url", "")).startswith("http")] + [""]
        body += [f"※ 公開情報をもとにAIがまとめた記事（{today}時点）。制度や手順は変わることがあるので、正式な情報は主催者の公式サイトで確認してほしい。馬券の購入は20歳から。"]
        one = lambda s: clean(s).replace("\n", " ")
        fm = ["---", f"title: {one(title)}", f"description: {one(j.get('description', ''))}", f"lead: {one(j['lead'])}",
              f"date: {today}", "draft: false", f"order: {i + 1}", "series: guide", "---", ""]
        f.write_text("\n".join(fm + body) + "\n", encoding="utf-8")
        made += 1
        print("ok", slug, "searches", res["searches"], "sources", len(srcs), flush=True)
    print(f"guide_gen: {made} articles, {calls} calls", flush=True)


if __name__ == "__main__":
    main()
