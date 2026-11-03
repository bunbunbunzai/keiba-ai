"""レース回顧の自動生成：確定したレースごとに「なぜ当たった／外れたか」を1〜2文で書く。

入力：予想（印・要約・展開予想）と結果（着順・4角位置・人気・着差・払戻）。
出力：data/reviews/<date>/<race_id>.json {"text", "model", "at"}。サイトのレースページの結果欄に出る。

使い方: python scraper/review_gen.py --date 20261103 [--limit 20]
ANTHROPIC_API_KEY が無ければ何もしない。すでに回顧があるレースは飛ばす。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

import ai
from common import DATA_DIR, save_json

ROOT = DATA_DIR.parent
JST = timezone(timedelta(hours=9))
SYSTEM = (
    "あなたは競馬の全レースをAIで予想して記録するサイト「競馬全頭ログ」の公式キャラクター「全頭くん」。確定したレースの予想と結果を照らして、"
    "なぜ当たったか、または外れたかを日本語で1〜2文（合計120字以内）で書く。"
    "です・ます調で、競馬を始めたばかりの人にも分かる言葉を使う。「想定勝率×単勝」の数値や「確度」「型」などサイト内の用語は使わず、意味で言い換える。"
    "絵文字なし。数字は与えられたものだけを使い、推測で事実を作らない。"
    "言い訳や自己弁護はしない。見立てのどこが合っていて、どこが違ったかを具体的に（展開・人気・位置取り・相手の評価など）。"
    "馬名は与えられた表記のまま。文章だけを返す（見出し・箇条書き・前置きは不要）。"
)


def _name(race: dict, pred: dict, num) -> str:
    for h in race.get("horses", []) or []:
        if h.get("number") == num:
            return h.get("name") or str(num)
    for e in pred.get("horses", []) or []:
        if e.get("number") == num:
            return e.get("name") or str(num)
    return str(num)


def prompt_for(pred: dict, race: dict, res: dict, sc: dict) -> str:
    mk = pred.get("marks", {})
    marks = "、".join(f"{m}{mk[m]}{_name(race, pred, mk[m])}" for m in ("◎", "〇", "▲") if mk.get(m) is not None)
    sub = []
    for m in ("△", "☆"):
        v = mk.get(m)
        for n in (v if isinstance(v, list) else [v] if v is not None else []):
            sub.append(f"{m}{n}{_name(race, pred, n)}")
    rows = sorted((r for r in res.get("rows", []) if str(r.get("finish", "")).isdigit()), key=lambda r: int(r["finish"]))[:5]
    rtxt = " / ".join(
        f"{r['finish']}着 {r.get('number')}{_name(race, pred, r.get('number'))}"
        + (f"（{r['popularity']}人気）" if r.get("popularity") else "")
        + (f" 4角{r['pos4']}番手" if r.get("pos4") else "")
        + (f" 着差{r['margin']}" if r.get("margin") else "")
        for r in rows)
    hon = mk.get("◎")
    hon_fin = next((r.get("finish") for r in res.get("rows", []) if r.get("number") == hon), None)
    hon_pos = next((r.get("pos4") for r in res.get("rows", []) if r.get("number") == hon), None)
    pay = "、".join(f"{k} {'/'.join(x['combo'] + ' ' + str(x['yen']) + '円' for x in v[:3])}" for k, v in (res.get("payouts") or {}).items()
                   if not k.startswith("_") and k in ("単勝", "複勝", "3連複", "馬連"))
    outcome = ("的中（払戻が投資を下回るトリガミ）" if 0 < sc["return"] < sc["stake"] else "的中" if sc["return"] else "不的中")
    return (f"レース：{race.get('venue')}{race.get('race_no')}R {race.get('race_name') or ''} {race.get('surface') or ''}{race.get('distance') or ''}m {race.get('field')}頭\n"
            f"予想の印：{marks}" + (f"、{'、'.join(sub)}" if sub else "") + f"。自信度{pred.get('confidence')}\n"
            f"予想の要約：{pred.get('summary')}\n展開予想：{pred.get('pace')}\n"
            f"買い目：{'、'.join(b['type'] + ' ' + b['combo'] for b in pred.get('bets', []))}\n"
            f"結果：{rtxt}\n◎の着順：{hon_fin}着" + (f"（4角{hon_pos}番手）" if hon_pos else "") + "\n"
            f"払戻：{pay or '不明'}\n判定：{outcome}、投資{sc['stake']}円→払戻{sc['return']}円\n"
            "この予想の回顧を1〜2文で。")


def run(date: str, limit: int | None = None) -> int:
    if not ai.enabled():
        print("ANTHROPIC_API_KEY が無いので回顧は作らない")
        return 0
    score = json.loads((DATA_DIR / "results" / date / "score.json").read_text(encoding="utf-8")) if (DATA_DIR / "results" / date / "score.json").exists() else {}
    sc_by = {r.get("race_id"): r for r in score.get("races", [])}
    n = 0
    for pf in sorted((ROOT / "predictions" / date).glob("*.json")):
        pred = json.loads(pf.read_text(encoding="utf-8"))
        rid = pred["race_id"]
        out = DATA_DIR / "reviews" / date / f"{rid}.json"
        if out.exists():
            continue
        sc = sc_by.get(rid)
        if not sc or "stake" not in sc or sc.get("voided") or not sc["stake"]:
            continue
        rf = DATA_DIR / "results" / date / f"{pred.get('results_key') or rid}.json"
        if not rf.exists():
            continue
        res = json.loads(rf.read_text(encoding="utf-8"))
        if not res.get("rows"):
            continue
        race = json.loads((DATA_DIR / "races" / date / f"{rid}.json").read_text(encoding="utf-8")) if (DATA_DIR / "races" / date / f"{rid}.json").exists() else {}
        text = ai.ask("review", SYSTEM, prompt_for(pred, race, res, sc), max_tokens=2000)
        if not text:
            if ai.too_many_failures():
                print("APIの失敗が続くので打ち切り", flush=True)
                break
            continue
        save_json(f"reviews/{date}/{rid}.json", {"text": text.strip(), "model": ai.MODELS["review"], "at": datetime.now(JST).strftime("%Y-%m-%d %H:%M")})
        n += 1
        if limit and n >= limit:
            break
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    print("reviews:", run(a.date, a.limit))
