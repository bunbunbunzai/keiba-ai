"""コース別の傾向ページに載せるAIの解説文を作る（data/course_notes/<slug>.json）。

材料は過去の公式レース結果の集計（site/course_stats.py）だけ。数字は渡したものしか使わせない。
同じコースは、レース数が2割以上増えるか30日たつまで作り直さない（無駄な呼び出しをしない）。

  python course_gen.py --max-calls 80
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
OUT = ROOT / "data" / "course_notes"
VENUE_SLUG = {
    "札幌": "sapporo", "函館": "hakodate", "福島": "fukushima", "新潟": "niigata", "東京": "tokyo",
    "中山": "nakayama", "中京": "chukyo", "京都": "kyoto", "阪神": "hanshin", "小倉": "kokura",
    "帯広ば": "obihiro", "帯広": "obihiro", "門別": "monbetsu", "盛岡": "morioka", "水沢": "mizusawa",
    "浦和": "urawa", "船橋": "funabashi", "大井": "ooi", "川崎": "kawasaki", "金沢": "kanazawa",
    "笠松": "kasamatsu", "名古屋": "nagoya", "園田": "sonoda", "姫路": "himeji", "高知": "kochi", "佐賀": "saga",
}

SYSTEM = (
    "あなたは競馬のデータ記者。与えられたコースの過去の公式レース結果の集計だけを根拠に、そのコースの傾向を解説する。"
    "読者は競馬を始めたばかりの人も含む。だ・である調、絵文字なし、誇大表現なし。"
    "数字は与えられたものだけを使い、推測で数字を作らない。コースの形状・坂・直線の長さなど、与えられていない事実は書かない。"
    "平均的な傾向（どのコースでも1番人気がいちばん勝つ、など）より、このコースの数字で目立つ点を書く。サンプルが少ない区分は断定しない。"
    "出力はJSONのみ（前置き・コードブロック不要）。キー：lead（結論、2文）、points（傾向の箇条書き、4〜5個、各1文で数字を入れる）、"
    "howto（予想や馬券に使うときの考え方、2〜3文。馬券の購入を勧めない）。"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=80)
    ap.add_argument("--min-races", type=int, default=30)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if not ai.enabled():
        print("ANTHROPIC_API_KEY が無いので何もしない")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    stats = C.collect(a.min_races)
    today = datetime.now(JST).strftime("%Y-%m-%d")
    calls = made = 0
    for key in sorted(stats, key=lambda k: -stats[k]["races"]):
        v, s, m = key
        slug = C.course_slug(VENUE_SLUG.get(v, "venue"), s, m)
        f = OUT / f"{slug}.json"
        st = stats[key]
        if f.exists() and not a.force:
            old = json.loads(f.read_text(encoding="utf-8"))
            fresh = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(old.get("updated", "2000-01-01"), "%Y-%m-%d")).days < 30
            if fresh and st["races"] < old.get("races", 0) * 1.2:
                continue
        if calls >= a.max_calls or ai.too_many_failures():
            break
        calls += 1
        text = ai.ask("article", SYSTEM, C.summary_text(key, st, v), max_tokens=4000)
        if not text:
            continue
        try:
            j = json.loads(text[text.find("{"): text.rfind("}") + 1])
            assert j.get("lead") and isinstance(j.get("points"), list)
        except Exception as e:  # noqa: BLE001
            print("JSONを読めない", slug, e, text[:200], flush=True)
            continue
        f.write_text(json.dumps({"slug": slug, "updated": today, "races": st["races"], "lead": j["lead"],
                                 "points": [str(x) for x in j["points"]][:6], "howto": j.get("howto", "")},
                                ensure_ascii=False, indent=1), encoding="utf-8")
        made += 1
        print("ok", slug, flush=True)
    print(f"course_gen: {made} notes, {calls} calls", flush=True)


if __name__ == "__main__":
    main()
