"""競馬場ガイド（data/venue_notes/<slug>.json）をWeb検索つきの上位モデルで作る。

材料：その場のコース別の集計（過去の公式結果、site/course_stats.py）。
コースの形状・直線の長さ・坂・ナイター・主な重賞などの事実は Web 検索で調べさせ、出典を残す。
30日以内に作った場は作り直さない（--force で作り直し）。

  python venue_gen.py --max-calls 30
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ai

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site"))
import course_stats as C  # noqa: E402

JST = timezone(timedelta(hours=9))
OUT = ROOT / "data" / "venue_notes"
VENUES = [("札幌", "sapporo"), ("函館", "hakodate"), ("福島", "fukushima"), ("新潟", "niigata"), ("東京", "tokyo"), ("中山", "nakayama"),
          ("中京", "chukyo"), ("京都", "kyoto"), ("阪神", "hanshin"), ("小倉", "kokura"), ("帯広", "obihiro"), ("門別", "monbetsu"),
          ("盛岡", "morioka"), ("水沢", "mizusawa"), ("浦和", "urawa"), ("船橋", "funabashi"), ("大井", "ooi"), ("川崎", "kawasaki"),
          ("金沢", "kanazawa"), ("笠松", "kasamatsu"), ("名古屋", "nagoya"), ("園田", "sonoda"), ("姫路", "himeji"), ("高知", "kochi"), ("佐賀", "saga")]
JRA = {"札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"}

SYSTEM = (
    "あなたは競馬のデータ記者。指定された競馬場について、予想に役立つガイドを書く。"
    "コースの形状（右回り・左回り、1周の距離、最後の直線の長さ、坂の有無）、ナイター開催の有無、主な重賞、その場ならではの特色は、"
    "web_search で主催者（JRA・地方競馬の各主催者・地方競馬情報サイト）や信頼できる報道を調べて確かめ、確かめられたことだけを書く。"
    "確かめられない数字は書かない。与えられた集計表の数字はそのまま使ってよい（集計表は過去の公式レース結果から作ったもの）。"
    "調べた記事の文章をそのまま写さず、必ず自分の言葉で短く書き直す（引用符での引用もしない）。本文に引用タグやURLを入れない。"
    "読者は競馬を始めたばかりの人も含む。だ・である調、絵文字なし、誇大表現なし。記事の文章を長く写さない。"
    "出力はJSONのみ（前置き・コードブロック不要）。キー：lead（2〜3文の要約）、"
    "facts（表にする基本情報。[{\"k\": 項目, \"v\": 内容}] を5〜8個。例：所在地、回り、1周の距離（ダート・芝）、最後の直線、坂、ナイター、主な重賞）、"
    "sections（[{\"h\": 見出し, \"text\": 3〜6文}] を4つ：「コースの特徴」「データで見る傾向」「主な重賞と開催の特色」「予想のポイント」）。"
    "sources（実際に事実の確認に使ったページ。[{\"url\": URL, \"title\": ページ名}] を2〜6個。検索結果に出たURLだけ）。"
    "予想のポイントでは馬券の購入を勧めない。"
)


def material(name: str, slug: str, stats: dict) -> str:
    keys = sorted((k for k in stats if k[0] == name or (name == "帯広" and k[0].startswith("帯広"))), key=lambda k: -stats[k]["races"])
    blocks = [C.summary_text(k, stats[k], name) for k in keys[:6]]
    kind = "中央競馬（JRA）" if name in JRA else ("地方競馬（ばんえい競馬）" if name == "帯広" else "地方競馬")
    head = f"競馬場：{name}競馬場（{kind}）\n"
    if blocks:
        return head + "\n【過去の公式レース結果の集計（コース別、レース数の多い順）】\n" + "\n\n".join(blocks)
    return head + "\n（このサイトにはまだこの場の過去結果の集計が少ない。データで見る傾向は、集計が少ないことを書いたうえで、確かめられた一般的な特徴にとどめる）"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=30)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    if not ai.enabled():
        print("ANTHROPIC_API_KEY が無いので何もしない")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    stats = C.collect(20)
    today = datetime.now(JST).strftime("%Y-%m-%d")
    calls = 0
    for name, slug in VENUES:
        if a.only and slug not in a.only.split(","):
            continue
        f = OUT / f"{slug}.json"
        if f.exists() and not a.force:
            old = json.loads(f.read_text(encoding="utf-8"))
            if (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(old.get("updated", "2000-01-01"), "%Y-%m-%d")).days < 30:
                continue
        if calls >= a.max_calls or ai.too_many_failures():
            break
        calls += 1
        res = ai.ask_with_search("analysis", SYSTEM, material(name, slug, stats), max_tokens=16000, max_searches=5)
        if not res or not res["text"]:
            print("生成できなかった", slug, flush=True)
            continue
        t = res["text"]
        try:
            j = ai.parse_json(t)
            assert j.get("lead") and j.get("sections")
        except Exception as e:  # noqa: BLE001
            print("JSONを読めない", slug, e, t[:200], flush=True)
            continue
        seen_urls = {x["url"] for x in res["results"]}
        srcs = [x for x in (j.get("sources") or []) if isinstance(x, dict) and x.get("url") in seen_urls][:6] or res["sources"]
        f.write_text(json.dumps({"slug": slug, "name": name, "updated": today, "lead": j["lead"], "facts": j.get("facts", [])[:10],
                                 "sections": j["sections"][:5], "sources": srcs, "searches": res["searches"]},
                                ensure_ascii=False, indent=1), encoding="utf-8")
        print("ok", slug, "searches", res["searches"], "sources", len(res["sources"]), flush=True)
    print(f"venue_gen: {calls} calls", flush=True)


if __name__ == "__main__":
    main()
