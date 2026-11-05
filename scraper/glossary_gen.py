"""用語集の各ページ（data/glossary/<slug>.json）を上位モデルで書く。12語ずつまとめて頼む。

  python glossary_gen.py --max-calls 20
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ai
from glossary_terms import TERMS

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "glossary"
JST = timezone(timedelta(hours=9))

SYSTEM = (
    "あなたは競馬の入門書の編集者。与えられた競馬用語を、競馬を始めたばかりの人に向けて正確に説明する。"
    "日本の競馬（JRA・地方競馬）の一般的なルールと慣習に沿って書く。制度の細かい数字（払戻率など）は、確実なものだけを書き、"
    "時期や主催者で違うものは「主催者によって異なる」と書く。だ・である調、絵文字なし、誇大表現なし。馬券の購入を勧めない。"
    "出力はJSONの配列のみ（前置き・コードブロック不要）。各要素：{\"slug\": そのまま, \"term\": そのまま, \"reading\": ひらがなの読み, "
    "\"short\": 1文の定義（40字以内）, \"body\": 説明（3〜5文）, \"example\": 使い方や具体例（1〜2文）, "
    "\"tip\": 予想やデータを見るときのポイント（1〜2文）, \"related\": 関連する用語のslug（与えた一覧の中から2〜4個）}。"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=20)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if not ai.enabled():
        print("ANTHROPIC_API_KEY が無いので何もしない")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    allterms = [(cat, s, t) for cat, lst in TERMS.items() for s, t in lst]
    slugs = "、".join(f"{s}={t}" for _, s, t in allterms)
    todo = [x for x in allterms if a.force or not (OUT / f"{x[1]}.json").exists()]
    today = datetime.now(JST).strftime("%Y-%m-%d")
    calls = made = 0
    for i in range(0, len(todo), 12):
        if calls >= a.max_calls or ai.too_many_failures():
            break
        batch = todo[i:i + 12]
        calls += 1
        user = ("説明する用語（slug=用語）：\n" + "\n".join(f"{s}={t}（分類：{c}）" for c, s, t in batch)
                + f"\n\nrelated に使える用語の一覧：{slugs}")
        text = ai.ask("analysis", SYSTEM, user, max_tokens=16000)
        if not text:
            continue
        try:
            arr = json.loads(text[text.find("["): text.rfind("]") + 1])
        except Exception as e:  # noqa: BLE001
            print("JSONを読めない", e, text[:200], flush=True)
            continue
        cats = {s: c for c, s, _ in batch}
        valid = {s for _, s, _ in allterms}
        for x in arr:
            s = x.get("slug")
            if s not in cats or not x.get("short") or not x.get("body"):
                continue
            x["category"] = cats[s]
            x["related"] = [r for r in x.get("related") or [] if r in valid and r != s][:4]
            x["updated"] = today
            (OUT / f"{s}.json").write_text(json.dumps(x, ensure_ascii=False, indent=1), encoding="utf-8")
            made += 1
        print(f"batch {calls}: {made} terms so far", flush=True)
    print(f"glossary_gen: {made} terms, {calls} calls", flush=True)


if __name__ == "__main__":
    main()
