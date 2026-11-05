"""馬別ページに載せるAIの寸評（2〜3文）を作る（data/horse_notes/<馬ID>.json）。

材料：その馬の近走（出馬表に載る直近5走）と、このサイトのAIの評価の履歴（印・評価点・想定勝率・短評・着順）。
評価が増えたときだけ作り直す。並列で呼び、--max-calls で回数の上限をかける。

  python horse_gen.py --max-calls 6000 --workers 6
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import ai

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site"))
import build as B  # noqa: E402
from extra import nfkc, short_id  # noqa: E402

OUT = ROOT / "data" / "horse_notes"
SYSTEM = (
    "あなたは競馬のデータ記者。与えられた1頭の馬の近走成績と、AI予想サイトでの評価の履歴だけを根拠に、"
    "その馬の特徴を日本語で2〜3文（合計150字以内）で書く。だ・である調、絵文字なし。"
    "近走の着順や着差の流れ、走った距離・馬場・競馬場の傾向、位置取り（通過順）や上がりの特徴、AIの評価の変化のうち、目立つ点を書く。"
    "与えられていない事実（血統の評判、調教の内容など）や数字は書かない。データが少なければ少ないと書く。"
    "「次は買い」など馬券を勧める表現はしない。文章だけを返す（見出し・箇条書き・前置きは不要）。"
)


def collect() -> dict:
    horses: dict = {}
    for d in B.all_dates():
        if d < B.STATS_FROM:
            continue
        for p in B.predictions(d):
            mm = B.mark_map(p)
            race_h = {h.get("number"): h for h in p["_race"].get("horses", []) or []}
            for e in p.get("horses", []):
                rh = race_h.get(e.get("number"), {})
                name = nfkc(e.get("name") or rh.get("name") or "").replace(" ", "")
                if len(name) < 2:
                    continue
                fin = ""
                for row in (p.get("_result") or {}).get("rows") or []:
                    if row.get("number") == e.get("number"):
                        fin = str(row.get("finish") or "")
                horses.setdefault(name, []).append({
                    "d": d, "race": B.race_label(p), "mark": mm.get(e.get("number"), "無印"), "score": e.get("score"),
                    "win_pct": e.get("win_pct"), "comment": e.get("comment") or "", "finish": fin,
                    "past": rh.get("past") or [], "profile": {k: rh.get(k) for k in ("sex_age", "sire", "damsire", "trainer")}})
    return horses


def material(name: str, items: list) -> str:
    items = sorted(items, key=lambda x: x["d"])
    last = items[-1]
    pr = last["profile"]
    lines = [f"馬名：{name}（{pr.get('sex_age') or ''}）"]
    past = last["past"][:5]
    if past:
        lines.append("近走（新しい順）：")
        for r in past:
            lines.append(f"- {r.get('date')} {r.get('venue')} {r.get('race_name') or ''} {r.get('surface') or ''}{r.get('distance') or ''}m"
                         f"（{r.get('track') or ''}・{r.get('field') or '?'}頭）{r.get('finish')}着 {r.get('popularity') or '?'}番人気"
                         f" 通過{r.get('corners') or '-'} 上がり{r.get('last3f') or '-'} 着差{r.get('margin') if r.get('margin') is not None else '-'}")
    lines.append("このサイトのAIの評価（古い順）：")
    for x in items:
        wp = f"想定勝率{x['win_pct']}%" if x["win_pct"] is not None else ""
        fin = f"→{x['finish']}着" if x["finish"].isdigit() else ("→" + x["finish"] if x["finish"] else "→結果待ち")
        lines.append(f"- {x['d'][4:6]}/{x['d'][6:]} {x['race']}：{x['mark']} 評価点{x['score']} {wp} {fin}　短評「{x['comment'][:80]}」")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-calls", type=int, default=6000)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    if not ai.enabled():
        print("ANTHROPIC_API_KEY が無いので何もしない")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    horses = collect()
    todo = []
    for name, items in horses.items():
        hid = short_id(name)
        basis = f"{len(items)}:{max(x['d'] for x in items)}:{sum(1 for x in items if x['finish'])}"
        f = OUT / f"{hid}.json"
        if f.exists() and json.loads(f.read_text(encoding="utf-8")).get("basis") == basis:
            continue
        todo.append((name, hid, basis, items))
    todo.sort(key=lambda t: -len(t[3]))  # 評価の多い馬から
    todo = todo[: a.max_calls]
    print(f"horses {len(horses)}, to write {len(todo)}", flush=True)

    def one(t):
        name, hid, basis, items = t
        if ai.too_many_failures():
            return False
        text = ai.ask("bulk", SYSTEM, material(name, items), max_tokens=1500)
        if not text:
            return False
        (OUT / f"{hid}.json").write_text(json.dumps({"name": name, "basis": basis, "text": text.strip()[:300],
                                                       "updated": max(x["d"] for x in items)}, ensure_ascii=False), encoding="utf-8")
        return True

    ok = 0
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for i, fut in enumerate(as_completed([ex.submit(one, t) for t in todo]), 1):
            ok += bool(fut.result())
            if i % 200 == 0:
                print(f"{i}/{len(todo)} done, ok {ok}", flush=True)
    print(f"horse_gen: {ok} notes", flush=True)


if __name__ == "__main__":
    main()
