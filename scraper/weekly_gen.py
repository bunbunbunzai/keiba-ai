"""週間振り返り記事（columns/weekly-<月曜の日付>.md）を作る。分析は上位モデル（Opus）。

1週間（月〜日）の全予想と結果をレース単位の一覧にして渡し、
「どんな条件で当たり／外れたか」「◎の選び方・相手・買い目のどこに問題があったか」を分析させる。
表（全体・場別・自信度別・◎の人気別）はプログラムで作る。数字はAIに作らせない。

  python weekly_gen.py                # 先週（直近の日曜まで）
  python weekly_gen.py --week 20261026
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ai

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site"))
import build as B  # noqa: E402

JST = timezone(timedelta(hours=9))

SYSTEM = (
    "あなたは、AIが中央・地方の全レースを予想して外れも含めた成績を公開するサイト「競馬全頭ログ」の分析担当。"
    "与えられた1週間分の全予想と結果の一覧（1行1レース）と集計表だけを根拠に、この週のAI予想を率直に振り返る記事の本文を書く。"
    "読者は競馬ファン（初心者も含む）。だ・である調、絵文字なし、誇大表現なし、言い訳をしない。"
    "数字は一覧と集計表から読み取れるものだけを使い、計算が必要な数字は一覧から数えて確かめてから書く。推測で数字を作らない。"
    "サンプルが少ない区分（10レース未満）は「参考程度」と書き、断定しない。"
    "出力はJSONのみ（前置き・コードブロック不要）。キー："
    "lead（この週の結論、2〜3文）、"
    "findings（気づいた傾向、5〜7個。各要素は {\"title\": 15字以内, \"text\": 2〜3文、具体的なレースや数字を挙げる} ）、"
    "good（よかった予想を2〜3レース。{\"race\": レース名, \"text\": 1〜2文}）、"
    "bad（悔しい外れを2〜3レース。{\"race\": レース名, \"text\": どこで見立てが違ったか1〜2文}）、"
    "next（来週に向けて見ておく点、2〜3文。予想ルールを変えると約束はしない）。"
)


def week_range(arg: str | None) -> tuple[str, str]:
    if arg:
        mon = datetime.strptime(arg, "%Y%m%d")
    else:
        today = datetime.now(JST).replace(tzinfo=None)
        mon = today - timedelta(days=today.weekday() + 7)  # 先週の月曜
    return mon.strftime("%Y%m%d"), (mon + timedelta(days=6)).strftime("%Y%m%d")


def rows_for(d0: str, d1: str):
    out = []
    for d in B.all_dates():
        if not (d0 <= d <= d1) or d < B.STATS_FROM:
            continue
        for p in B.predictions(d):
            sc = B.scored(p)
            if not sc or not sc.get("stake"):
                continue
            r = p["_race"]
            mk = B.mark_map(p)
            race_h = {h.get("number"): h for h in r.get("horses", []) or []}
            hon = (p.get("marks") or {}).get("◎")
            hh = dict(race_h.get(hon, {}))
            if not hh.get("popularity") and hh.get("odds"):
                ods = sorted(h.get("odds") for h in race_h.values() if h.get("odds"))
                if len(ods) == len(race_h):
                    hh["popularity"] = ods.index(hh["odds"]) + 1
            top = [x for x in (sc.get("top3") or []) if x is not None]
            out.append({
                "d": d, "venue": B.VENUE_NAME.get(B.venue_of(p), B.venue_of(p)), "label": B.race_label(p),
                "course": f"{r.get('surface') or ''}{r.get('distance') or ''}m", "field": r.get("field") or len(race_h),
                "conf": p.get("confidence"), "hon": hon, "hon_pop": hh.get("popularity"), "hon_odds": hh.get("odds"),
                "hon_fin": sc.get("honmei_finish"), "top3": top, "top3_marks": [mk.get(x, "無") for x in top],
                "stake": sc["stake"], "ret": sc["return"], "bets": "、".join(f"{b['type']}{b['combo']}" for b in p.get("bets", [])),
                "graded": bool(B.extra.grade_of(r, p.get("race_name") or r.get("race_name") or "")),
            })
    return out


def agg(rows, key):
    g = defaultdict(lambda: [0, 0, 0, 0, 0])  # races, stake, ret, hits, honmei_win
    for x in rows:
        k = key(x)
        a = g[k]
        a[0] += 1
        a[1] += x["stake"]
        a[2] += x["ret"]
        a[3] += x["ret"] > 0
        a[4] += str(x["hon_fin"]) == "1"
    return g


def table(title, g, order=None) -> str:
    keys = order or sorted(g, key=lambda k: -g[k][0])
    lines = [f"### {title}", "", "| 区分 | レース | 回収率 | 的中率 | ◎の勝率 |", "|---|---|---|---|---|"]
    for k in keys:
        if k not in g:
            continue
        n, st, rt, h, w = g[k]
        lines.append(f"| {k} | {n} | {100 * rt / st:.1f}% | {100 * h / n:.0f}% | {100 * w / n:.0f}% |")
    return "\n".join(lines)


def pop_band(x):
    p = x["hon_pop"]
    if not isinstance(p, int):
        return "人気不明（オッズ未取得）"
    return "1番人気" if p == 1 else "2番人気" if p == 2 else "3〜5番人気" if p <= 5 else "6番人気以下"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", default="")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    d0, d1 = week_range(a.week)
    slug = f"weekly-{d0}"
    f = ROOT / "columns" / f"{slug}.md"
    if f.exists() and not a.force:
        print("作成済み", f.name)
        return
    if not ai.enabled():
        print("ANTHROPIC_API_KEY が無いので何もしない")
        return
    rows = rows_for(d0, d1)
    if len(rows) < 30:
        print("レースが少ないので作らない", len(rows))
        return
    tot = agg(rows, lambda x: "全体")
    tables = "\n\n".join([
        table("全体", tot),
        table("自信度別", agg(rows, lambda x: f"自信度{x['conf']}"), ["自信度A", "自信度B", "自信度C"]),
        table("◎の人気別", agg(rows, pop_band), ["1番人気", "2番人気", "3〜5番人気", "6番人気以下", "人気不明（オッズ未取得）"]),
        table("中央・地方", agg(rows, lambda x: "中央" if x["venue"] in ("札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉") else "地方")),
        table("場別", agg(rows, lambda x: x["venue"])),
    ])
    listing = "\n".join(
        f"{x['d'][4:6]}/{x['d'][6:]} {x['label']}（{x['course']}・{x['field']}頭{'・重賞' if x['graded'] else ''}）自信度{x['conf']} "
        f"◎{x['hon']}（{x['hon_pop'] or '?'}番人気{'・' + str(x['hon_odds']) + '倍' if x['hon_odds'] else ''}）→{x['hon_fin'] or '-'}着 "
        f"／1〜3着 {'-'.join(map(str, x['top3']))}（印 {'・'.join(x['top3_marks'])}）／買い目 {x['bets']} 購入{x['stake']}円 払戻{x['ret']}円"
        for x in rows)
    user = f"対象：{d0[:4]}年{int(d0[4:6])}月{int(d0[6:])}日〜{int(d1[4:6])}月{int(d1[6:])}日の{len(rows)}レース\n\n【集計表】\n{tables}\n\n【全レースの一覧】\n{listing}"
    text = ai.ask("analysis", SYSTEM, user, max_tokens=16000)
    if not text:
        print("生成できなかった")
        return
    j = json.loads(text[text.find("{"): text.rfind("}") + 1])
    n, st, rt, h, w = tot["全体"]
    label = f"{int(d0[4:6])}月{int(d0[6:])}日〜{int(d1[4:6])}月{int(d1[6:])}日"
    body = [f"## この週の成績", "", f"{len(rows)}レースを予想し、回収率{100 * rt / st:.1f}%（購入{st:,}円・払戻{rt:,}円）、的中率{100 * h / n:.0f}%、◎の勝率{100 * w / n:.0f}%だった。", "", tables, "",
            "## 気づいた傾向", ""]
    for x in j.get("findings", []):
        body += [f"### {x.get('title', '')}", "", x.get("text", ""), ""]
    if j.get("good"):
        body += ["## よかった予想", ""] + [f"- **{x.get('race', '')}**：{x.get('text', '')}" for x in j["good"]] + [""]
    if j.get("bad"):
        body += ["## 悔しい外れ", ""] + [f"- **{x.get('race', '')}**：{x.get('text', '')}" for x in j["bad"]] + [""]
    if j.get("next"):
        body += ["## 来週に向けて", "", j["next"], ""]
    body += ["※ 表の数字はサイトの記録から計算。文章はその記録をもとにAIが書いた分析。買い目は1点100円ずつ買ったとして計算している。"]
    desc = j.get("lead", "")[:110]
    fm = ["---", f"title: AI予想の週間振り返り（{label}）{len(rows)}レース・回収率{100 * rt / st:.1f}%", f"description: {desc}",
          f"lead: {j.get('lead', '')}", f"date: {datetime.now(JST).strftime('%Y-%m-%d')}", "draft: false", "order: 0", "series: weekly", "---", ""]
    f.write_text("\n".join(fm + body) + "\n", encoding="utf-8")
    print("wrote", f.name)


if __name__ == "__main__":
    main()
