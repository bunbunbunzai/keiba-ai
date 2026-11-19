"""その年のJRA重賞を振り返る記事（特集：<年>年の重賞を振り返る）を、JRA公式の全着順から集計して作る。AIは呼ばない。

data/graded_hist/<年>.json（graded_hist.py が集めたJRA公式の成績）だけを使う。レースが終わるたびに数字が変わるので、
毎日の graded ワークフローで作り直す。本文が変わったときだけ updated を今日にする。

  python year_cols.py            # 今年の分
  python year_cols.py --year 2026
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, median

from common import DATA_DIR

ROOT = DATA_DIR.parent
COLS = ROOT / "columns"
HIST = DATA_DIR / "graded_hist"
JST = timezone(timedelta(hours=9))
WD = "月火水木金土日"
FIRST_DATE = "2026-11-20"  # この特集を始めた日（記事の date）


def load(y: int) -> list[dict]:
    f = HIST / f"{y}.json"
    if not f.exists():
        return []
    return json.loads(f.read_text(encoding="utf-8")).get("races", [])


def done(rs: list[dict]) -> list[dict]:
    return [r for r in rs if any(isinstance(x.get("fin"), int) for x in r.get("rows") or [])]


def runners(r: dict) -> list[dict]:
    return [x for x in r.get("rows") or [] if x.get("pop")]


def fin(x) -> int:
    return x["fin"] if isinstance(x.get("fin"), int) else 99


def at(r: dict, k: int) -> list[dict]:
    return [x for x in runners(r) if fin(x) == k]


def pay(r: dict, kind: str):
    v = (r.get("pay") or {}).get(kind) or []
    return v[0][1] if v else None


def yen(v) -> str:
    return f"{v:,}円" if v else "―"


def man(v: int) -> str:
    if v >= 10000:
        a, b = divmod(v, 10000)
        return f"{a}万{b:,}円" if b else f"{a}万円"
    return f"{v:,}円"


def md(d: str) -> str:
    return f"{int(d[4:6])}/{int(d[6:8])}"


def jp(d: str) -> str:
    x = datetime.strptime(d, "%Y%m%d")
    return f"{x.month}月{x.day}日（{WD[x.weekday()]}）"


def name(r: dict) -> str:
    return r.get("name") or r.get("abbr") or ""


def flat(r: dict) -> bool:
    return not str(r.get("grade") or "").startswith("J")


def rec(v: list[dict]) -> dict:
    n = len(v)
    w = sum(fin(x) == 1 for x in v)
    t2 = sum(fin(x) <= 2 for x in v)
    t3 = sum(fin(x) <= 3 for x in v)
    return dict(n=n, w=w, s=t2 - w, t=t3 - t2, o=n - t3, wr=100 * w / n if n else 0, r2=100 * t2 / n if n else 0, r3=100 * t3 / n if n else 0)


def fmt(v: dict) -> str:
    return f"{v['w']}-{v['s']}-{v['t']}-{v['o']}"


THEAD = "| 成績 | 勝率 | 連対率 | 3着内率 | 頭数 |\n|---|---|---|---|---|---|\n"


def row(label: str, v: dict) -> str:
    return f"| {label} | {fmt(v)} | {v['wr']:.0f}% | {v['r2']:.0f}% | {v['r3']:.0f}% | {v['n']} |"


def who(xs: list[dict], pop: bool = True) -> str:
    if not xs:
        return "―"
    return "・".join(f"{x['name']}（{x['pop']}）" if pop else x["name"] for x in xs) + ("（同着）" if len(xs) > 1 else "")


def asof(rs: list[dict]) -> str:
    d = max(r["date"] for r in rs)
    return f"{int(d[4:6])}月{int(d[6:8])}日"


CAUTION = "> 数字はJRA公式の成績から集計した。年の途中の集計なので、残りのレースで変わる。馬券は20歳から購入できる。"
SRC = "- JRA公式「{y}年 重賞競走一覧」の各レースの成績（このサイトが集めたJRAの重賞の全着順）"


def front(slug: str, order: int, title: str, desc: str, lead: str, hero: str, year: int) -> dict:
    return {"title": title, "description": desc, "lead": lead, "order": order, "series": f"year{year}", "hero": hero}


# ---------- 1. G1の全結果 ----------
def g1(year: int, rs: list[dict], sched: list[dict]) -> tuple:
    g = [r for r in rs if r.get("grade") == "G1"]
    up = [r for r in sched if r.get("grade") == "G1" and r not in g]
    p1w = sum(1 for r in g if any(x["pop"] == 1 for x in at(r, 1)))
    t3 = [(pay(r, "3連単") or 0, r) for r in g]
    top_pay, top_r = max(t3, key=lambda t: t[0]) if t3 else (0, None)
    multi = Counter(x["name"] for r in g for x in at(r, 1))
    multi = [(n, c) for n, c in multi.most_common() if c >= 2]
    jw = Counter(x["jockey"] for r in g for x in at(r, 1))
    jtop = jw.most_common(1)[0] if jw else ("", 0)
    tbl = "| 日付 | レース | 勝ち馬（人気） | 2着 | 3着 | 勝ち馬の騎手 | 単勝 | 3連単 |\n|---|---|---|---|---|---|---|---|\n"
    for r in g:
        tbl += (f"| {md(r['date'])} | {name(r)} | {who(at(r, 1))} | {who(at(r, 2))} | {who(at(r, 3))} | "
                f"{'・'.join(x['jockey'] for x in at(r, 1))} | {yen(pay(r, '単勝'))} | {yen(pay(r, '3連単'))} |\n")
    jg = [r for r in rs if r.get("grade") == "J・G1"]
    jt = ""
    if jg:
        jt = ("\n## 障害のG1\n\n| 日付 | レース | 勝ち馬（人気） | 2着 | 3着 | 騎手 |\n|---|---|---|---|---|---|\n"
              + "".join(f"| {md(r['date'])} | {name(r)} | {who(at(r, 1))} | {who(at(r, 2))} | {who(at(r, 3))} | {'・'.join(x['jockey'] for x in at(r, 1))} |\n" for r in jg))
    upt = ""
    if up:
        upt = ("\n## これから行われるG1\n\n| 日付 | レース | コース |\n|---|---|---|\n"
               + "".join(f"| {jp(r['date'])} | {name(r)} | {r.get('venue', '')}{'ダート' if r.get('surface') == 'ダ' else r.get('surface', '')}{r.get('distance', '')}m |\n" for r in up)
               + "\nレースが終わると、この表に結果を足していく。\n")
    lead = (f"{year}年のJRAのG1は、{asof(rs)}までに{len(g)}レースが終わった。1番人気の勝ちは{p1w}レース。"
            + (f"G1を2勝以上したのは{'、'.join(f'{n}（{c}勝）' for n, c in multi)}。" if multi else "")
            + (f"3連単の最高配当は{name(top_r)}の{man(top_pay)}。" if top_r else ""))
    title = f"{year}年のJRA G1 全レース結果一覧｜勝ち馬・人気・騎手・配当（{asof(rs)}時点）"
    desc = (f"{year}年のJRAのG1全{len(g) + len(up)}レースの結果を、勝ち馬・2着・3着・人気・騎手・単勝と3連単の配当で一覧にした。"
            f"{asof(rs)}までに{len(g)}レースが終わり、1番人気の勝ちは{p1w}レース。")
    body = (f"## {year}年のG1の結果\n\n（　）の数字は人気。\n\n{tbl}\n"
            f"## まとめ\n\n- 1番人気が勝ったのは{len(g)}レース中{p1w}レース\n"
            + (f"- G1を2勝以上した馬：{'、'.join(f'{n}（{c}勝）' for n, c in multi)}\n" if multi else "- G1を2勝以上した馬はいない\n")
            + (f"- G1をいちばん多く勝った騎手：{jtop[0]}（{jtop[1]}勝）\n" if jtop[1] >= 2 else "")
            + (f"- 3連単の最高配当：{name(top_r)}の{man(top_pay)}\n" if top_r else "")
            + jt + upt + f"\n{CAUTION}\n\n"
            "## あわせて読みたい\n\n- [重賞の高配当ランキング](/column/year{y}-kouhaitou/)\n- [重賞の騎手ランキング](/column/year{y}-kishu/)\n"
            "- [重賞の1番人気の成績](/column/year{y}-ninki/)\n- [有馬記念2026の特集](/column/arima2026-guide/)\n\n## 出典\n\n{src}\n").replace("{y}", str(year)).replace("{src}", SRC.format(y=year))
    return front("g1-kekka", 1, title, desc, lead, "g-turf-winter", year), body


# ---------- 2. 高配当ランキング ----------
def kouhaitou(year: int, rs: list[dict], prev: list[dict]) -> tuple:
    kinds = ["3連単", "3連複", "馬連", "単勝"]
    out = ""
    for k in kinds:
        v = sorted(((pay(r, k) or 0, r) for r in rs if pay(r, k)), key=lambda t: -t[0])[:10]
        out += (f"\n## {k}の高配当トップ10\n\n| 順位 | 配当 | 日付 | レース | 格 | 1〜3着（人気） |\n|---|---|---|---|---|---|\n"
                + "".join(f"| {i} | {man(p)} | {md(r['date'])} | {name(r)} | {r.get('grade', '')} | {who(at(r, 1))} → {who(at(r, 2))} → {who(at(r, 3))} |\n"
                          for i, (p, r) in enumerate(v, 1)))
    t3 = [pay(r, "3連単") for r in rs if pay(r, "3連単")]
    t3p = [pay(r, "3連単") for r in prev if pay(r, "3連単")]
    over = sum(v >= 100000 for v in t3)
    overp = sum(v >= 100000 for v in t3p)
    big = max(((pay(r, "3連単") or 0, r) for r in rs), key=lambda t: t[0])
    lead = (f"{year}年のJRAの重賞で、3連単の最高配当は{md(big[1]['date'])}の{name(big[1])}の{man(big[0])}。"
            f"{asof(rs)}までの{len(t3)}レースのうち、3連単が10万円を超えたのは{over}レース（{100 * over / max(1, len(t3)):.0f}%）。"
            f"3連単の真ん中の値（中央値）は{man(int(median(t3)))}。")
    title = f"{year}年のJRA重賞 高配当ランキング｜3連単{man(big[0])}が最高（{asof(rs)}時点）"
    desc = (f"{year}年のJRAの重賞{len(t3)}レースの配当を、3連単・3連複・馬連・単勝の高い順に並べた。3連単の最高は{name(big[1])}の{man(big[0])}、"
            f"10万円超えは{over}レース。前年との比較つき。")
    cmp_ = ""
    if t3p:
        cmp_ = ("\n## 前の年との比較\n\n| 年 | レース数 | 3連単の中央値 | 10万円超え | 100万円超え | 最高配当 |\n|---|---|---|---|---|---|\n"
                f"| {year}年（{asof(rs)}まで） | {len(t3)} | {man(int(median(t3)))} | {over}回 | {sum(v >= 1000000 for v in t3)}回 | {man(max(t3))} |\n"
                f"| {year - 1}年 | {len(t3p)} | {man(int(median(t3p)))} | {overp}回 | {sum(v >= 1000000 for v in t3p)}回 | {man(max(t3p))} |\n")
    body = (f"平地と障害のJRAの重賞（G1・G2・G3）の払戻金（100円あたり）を集計した。（　）の数字は人気。\n{out}{cmp_}\n{CAUTION}\n\n"
            f"## あわせて読みたい\n\n- [{year}年のG1全レース結果](/column/year{year}-g1-kekka/)\n- [重賞の1番人気の成績と、人気薄の勝ち馬](/column/year{year}-ninki/)\n\n"
            f"## 出典\n\n{SRC.format(y=year)}\n")
    return front("kouhaitou", 2, title, desc, lead, "g-turf-winter", year), body


# ---------- 3. 騎手 / 4. 調教師 ----------
def people(year: int, rs: list[dict], prev: list[dict], key: str) -> tuple:
    jp_ = "騎手" if key == "jockey" else "調教師"
    g = defaultdict(list)
    g1w = Counter()
    for r in rs:
        for x in runners(r):
            if x.get(key):
                g[x[key]].append(x)
        if r.get("grade") == "G1":
            for x in at(r, 1):
                g1w[x.get(key)] += 1
    P = {k: rec(v) for k, v in g.items()}
    rank = sorted(P.items(), key=lambda kv: (-kv[1]["w"], -kv[1]["r3"], kv[0]))[:20]
    gp = defaultdict(list)
    for r in prev:
        for x in runners(r):
            if x.get(key):
                gp[x[key]].append(x)
    prev_rank = sorted(((k, rec(v)) for k, v in gp.items()), key=lambda kv: -kv[1]["w"])[:5]
    t = f"| 順位 | {jp_} | 重賞の勝ち | うちG1 | 成績 | 勝率 | 3着内率 | 出走 |\n|---|---|---|---|---|---|---|---|\n"
    for i, (k, v) in enumerate(rank, 1):
        t += f"| {i} | {k} | {v['w']} | {g1w.get(k, 0)} | {fmt(v)} | {v['wr']:.0f}% | {v['r3']:.0f}% | {v['n']} |\n"
    top = rank[0]
    qual = [(k, v) for k, v in P.items() if v["n"] >= 20]
    best3 = max(qual, key=lambda kv: kv[1]["r3"]) if qual else None
    g1top = g1w.most_common(1)[0] if g1w else None
    lead = (f"{year}年のJRAの重賞で最も多く勝った{jp_}は{top[0]}（{top[1]['w']}勝）。"
            + (f"G1の勝ちが最も多いのは{g1top[0]}（{g1top[1]}勝）。" if g1top and g1top[1] >= 2 else "")
            + (f"20回以上出走した{jp_}のなかで3着以内に入る割合が最も高いのは{best3[0]}（{best3[1]['r3']:.0f}%）。" if best3 else "")
            + f"{asof(rs)}までの集計。")
    title = f"{year}年のJRA重賞 {jp_}ランキング｜1位は{top[0]}の{top[1]['w']}勝（{asof(rs)}時点）"
    desc = (f"{year}年のJRAの重賞を、{jp_}ごとの勝ち数・G1の勝ち数・3着内率で並べた。1位は{top[0]}（{top[1]['w']}勝）。前年の上位5人との比較つき。")
    pt = (f"\n## {year - 1}年の上位5人\n\n| 順位 | {jp_} | 重賞の勝ち | 成績 |\n|---|---|---|---|\n"
          + "".join(f"| {i} | {k} | {v['w']} | {fmt(v)} |\n" for i, (k, v) in enumerate(prev_rank, 1))) if prev_rank else ""
    other = "kishu" if key != "jockey" else "chokyoshi"
    body = (f"平地と障害のJRAの重賞（G1・G2・G3）で、{jp_}ごとの成績を数えた。成績の並びは「1着-2着-3着-4着以下」。\n\n"
            f"## {year}年の重賞の勝ち数（上位20人）\n\n{t}{pt}\n{CAUTION}\n\n"
            f"## あわせて読みたい\n\n- [{year}年の重賞 {'調教師' if key == 'jockey' else '騎手'}ランキング](/column/year{year}-{other}/)\n"
            f"- [{year}年のG1全レース結果](/column/year{year}-g1-kekka/)\n\n## 出典\n\n{SRC.format(y=year)}\n")
    return front("kishu" if key == "jockey" else "chokyoshi", 3 if key == "jockey" else 4, title, desc, lead, "g-turf-winter", year), body


# ---------- 5. 1番人気・人気薄 ----------
def ninki(year: int, rs: list[dict], past: dict[int, list[dict]]) -> tuple:
    def p1(rs_):
        return [x for r in rs_ for x in runners(r) if x["pop"] == 1]
    cur = rec(p1(rs))
    roi = 100 * sum(pay(r, "単勝") or 0 for r in rs if any(x["pop"] == 1 for x in at(r, 1))) / (100 * max(1, len(p1(rs))))
    by_g = {g: rec(p1([r for r in rs if r.get("grade") == g])) for g in ("G1", "G2", "G3")}
    ys = sorted(past)[-10:]
    hist = [(y, rec(p1(past[y]))) for y in ys]
    avg_w = mean(v["wr"] for _, v in hist) if hist else 0
    ups = sorted(((x["pop"], r) for r in rs for x in at(r, 1)), key=lambda t: -t[0])[:10]
    lead = (f"{year}年のJRAの重賞で、1番人気は{asof(rs)}までに{cur['n']}回走って{cur['w']}勝（勝率{cur['wr']:.0f}%、3着内率{cur['r3']:.0f}%）。"
            + (f"過去{len(hist)}年の平均の勝率は{avg_w:.0f}%。" if hist else "")
            + f"単勝を毎回買った場合の回収率は{roi:.0f}%。いちばん人気のない勝ち馬は{ups[0][0]}番人気だった。")
    title = f"{year}年のJRA重賞 1番人気の成績｜勝率{cur['wr']:.0f}%、過去{len(hist)}年の平均は{avg_w:.0f}%（{asof(rs)}時点）"
    desc = (f"{year}年のJRAの重賞で1番人気がどれだけ勝ったかを、G1・G2・G3別と過去{len(hist)}年との比較で集計。人気薄で勝った馬のランキングつき。")
    t1 = "| 格 " + THEAD + "\n".join(row(f"{g}の1番人気", by_g[g]) for g in ("G1", "G2", "G3") if by_g[g]["n"]) + "\n" + row("重賞全体", cur)
    t2 = ("| 年 | 1番人気の成績 | 勝率 | 3着内率 |\n|---|---|---|---|\n"
          + "".join(f"| {y}年 | {fmt(v)} | {v['wr']:.0f}% | {v['r3']:.0f}% |\n" for y, v in hist)
          + f"| **{year}年（{asof(rs)}まで）** | {fmt(cur)} | {cur['wr']:.0f}% | {cur['r3']:.0f}% |\n")
    t3 = ("| 順位 | 人気 | 日付 | レース | 勝ち馬 | 単勝 |\n|---|---|---|---|---|---|\n"
          + "".join(f"| {i} | {p}番人気 | {md(r['date'])} | {name(r)}（{r.get('grade', '')}） | {who(at(r, 1), pop=False)} | {yen(pay(r, '単勝'))} |\n"
                    for i, (p, r) in enumerate(ups, 1)))
    body = (f"## 格ごとの1番人気の成績\n\n{t1}\n\n単勝の回収率は、1番人気の単勝を毎回100円ずつ買った場合（{roi:.0f}%）。\n\n"
            f"## 過去の年との比較\n\n{t2}\n## 人気のない馬が勝ったレース\n\n{t3}\n{CAUTION}\n\n"
            f"## あわせて読みたい\n\n- [{year}年の重賞 高配当ランキング](/column/year{year}-kouhaitou/)\n- [{year}年のG1全レース結果](/column/year{year}-g1-kekka/)\n\n"
            f"## 出典\n\n{SRC.format(y=year)}\n")
    return front("ninki", 5, title, desc, lead, "g-turf-winter", year), body


# ---------- 6. 3歳 / 7. 2歳 ----------
CLASSIC = ["桜花賞", "皐月賞", "NHKマイルC", "オークス", "日本ダービー", "秋華賞", "菊花賞"]


def sedai(year: int, rs: list[dict], sched: list[dict], age: int) -> tuple:
    def lim(r):  # その年齢だけのレース（「3歳以上」のように上の年齢も出られるレースは除く）
        c = r.get("cond") or ""
        return c.startswith(f"{age}歳") and "以上" not in c and flat(r)
    only = [r for r in rs if lim(r)]
    up = [r for r in sched if lim(r) and r not in rs]
    tbl = "| 日付 | レース | 格 | 勝ち馬（人気） | 騎手 | 調教師 |\n|---|---|---|---|---|---|\n"
    for r in only:
        w = at(r, 1)
        tbl += f"| {md(r['date'])} | {name(r)} | {r.get('grade', '')} | {who(w)} | {'・'.join(x['jockey'] for x in w)} | {'・'.join(x.get('trainer', '') for x in w)} |\n"
    wins = Counter(x["name"] for r in only for x in at(r, 1))
    multi = [(n, c) for n, c in wins.most_common() if c >= 2]
    sires = ""
    if age == 3:
        cl = [r for r in only if r.get("abbr") in CLASSIC]
        cls = "、".join(f"{r['abbr']}は{who(at(r, 1), pop=False)}" for r in cl)
        mixed = [(r, x) for r in rs if "以上" in (r.get("cond") or "") and flat(r) for x in at(r, 1) if x.get("age") == 3]
        mx = ("\n## 3歳馬が古馬を相手に勝った重賞\n\n| 日付 | レース | 格 | 勝ち馬（人気） |\n|---|---|---|---|\n"
              + "".join(f"| {md(r['date'])} | {name(r)} | {r.get('grade', '')} | {x['name']}（{x['pop']}） |\n" for r, x in mixed)) if mixed else ""
        lead = (f"{year}年の3歳の重賞は、{asof(rs)}までに{len(only)}レースが終わった。クラシックは{cls}が勝った。"
                + (f"3歳の重賞を2勝以上したのは{'、'.join(f'{n}（{c}勝）' for n, c in multi)}。" if multi else "")
                + (f"古馬との重賞を勝った3歳馬は{len(mixed)}頭。" if mixed else ""))
        title = f"{year}年の3歳重賞まとめ｜クラシックの勝ち馬と、古馬を破った3歳馬（{asof(rs)}時点）"
        desc = f"{year}年の3歳限定のJRA重賞{len(only)}レースの勝ち馬と、古馬との重賞で勝った3歳馬を一覧にした。クラシックの結果、2勝以上した馬もまとめた。"
        extra_ = mx
        hero = "g-turf-autumn"
    else:
        nxt = ("\n## これから行われる2歳の重賞\n\n| 日付 | レース | 格 | コース |\n|---|---|---|---|\n"
               + "".join(f"| {jp(r['date'])} | {name(r)} | {r.get('grade', '')} | {r.get('venue', '')}{'ダート' if r.get('surface') == 'ダ' else r.get('surface', '')}{r.get('distance', '')}m |\n" for r in up)) if up else ""
        lead = (f"{year}年の2歳の重賞は、{asof(rs)}までに{len(only)}レースが終わった。"
                + (f"2歳の重賞を2勝したのは{'、'.join(n for n, _ in multi)}。" if multi else "2歳の重賞を2勝した馬はまだいない。")
                + (f"このあと、{'、'.join(name(r) for r in up if r.get('grade') == 'G1')}などが行われる。" if up else ""))
        title = f"{year}年の2歳重賞まとめ｜勝ち馬一覧と来年のクラシック候補（{asof(rs)}時点）"
        desc = f"{year}年の2歳限定のJRA重賞{len(only)}レースの勝ち馬・騎手・調教師を一覧にした。阪神JF・朝日杯FS・ホープフルSなど、これからの2歳G1の日程つき。"
        extra_ = nxt
        hero = "g-turf-autumn"
    mt = ("\n## 重賞を2勝以上した馬\n\n" + "\n".join(f"- {n}：{c}勝（" + "、".join(name(r) for r in only if any(x['name'] == n for x in at(r, 1))) + "）" for n, c in multi) + "\n") if multi else ""
    body = (f"## {year}年の{age}歳の重賞の勝ち馬\n\n（　）の数字は人気。\n\n{tbl}{mt}{extra_}{sires}\n{CAUTION}\n\n"
            f"## あわせて読みたい\n\n- [{year}年のG1全レース結果](/column/year{year}-g1-kekka/)\n"
            + (f"- [{year}年の2歳重賞まとめ](/column/year{year}-2sai/)\n" if age == 3 else f"- [{year}年の3歳重賞まとめ](/column/year{year}-3sai/)\n")
            + f"\n## 出典\n\n{SRC.format(y=year)}\n")
    return front(f"{age}sai", 6 if age == 3 else 7, title, desc, lead, hero, year), body


# ---------- 8. 牝馬 ----------
def fem_only(r: dict) -> bool:
    """牝馬限定のレース（条件が「3歳牝」「4歳以上牝」など）。「3歳牡・牝」は牡馬も牝馬も出られるので限定ではない。"""
    c = (r.get("cond") or "").replace(" ", "")
    return c.endswith("牝") and "牡・牝" not in c


def hinba(year: int, rs: list[dict], past: dict[int, list[dict]]) -> tuple:
    def mixed_f(rs_):
        return [(r, x) for r in rs_ if flat(r) and not fem_only(r) for x in at(r, 1) if x.get("sex") == "牝"]
    def mixed_n(rs_):
        return len([r for r in rs_ if flat(r) and not fem_only(r)])
    cur = mixed_f(rs)
    n = mixed_n(rs)
    hist = [(y, len(mixed_f(past[y])), mixed_n(past[y])) for y in sorted(past)[-10:]]
    lead = (f"{year}年のJRAの重賞で、牡馬と一緒に走るレース（牝馬限定でないレース）を牝馬が勝ったのは、{asof(rs)}までに{n}レース中{len(cur)}レース"
            f"（{100 * len(cur) / max(1, n):.0f}%）。" + (f"過去{len(hist)}年の平均は{mean(100 * a / max(1, b) for _, a, b in hist):.0f}%。" if hist else ""))
    title = f"{year}年 牝馬が牡馬に勝った重賞一覧｜{n}レース中{len(cur)}勝（{asof(rs)}時点）"
    desc = f"{year}年のJRAの重賞のうち、牝馬限定でないレースを牝馬が勝ったケースを一覧にした。過去{len(hist)}年の割合との比較つき。"
    t = ("| 日付 | レース | 格 | 勝ち馬（人気） | 年齢 |\n|---|---|---|---|---|\n"
         + "".join(f"| {md(r['date'])} | {name(r)} | {r.get('grade', '')} | {x['name']}（{x['pop']}） | {x.get('age', '')}歳 |\n" for r, x in cur))
    t2 = ("| 年 | 牝馬が勝った数 | 対象のレース | 割合 |\n|---|---|---|---|\n"
          + "".join(f"| {y}年 | {a} | {b} | {100 * a / max(1, b):.0f}% |\n" for y, a, b in hist)
          + f"| **{year}年（{asof(rs)}まで）** | {len(cur)} | {n} | {100 * len(cur) / max(1, n):.0f}% |\n")
    body = (f"平地のJRAの重賞のうち、出走できる馬を牝馬に限っていないレースだけを数えた（障害は除く）。\n\n"
            f"## {year}年に牝馬が勝った重賞\n\n{t}\n## 過去の年との比較\n\n{t2}\n{CAUTION}\n\n"
            f"## あわせて読みたい\n\n- [{year}年のG1全レース結果](/column/year{year}-g1-kekka/)\n- [有馬記念の年齢・性別の傾向](/column/arima-kinen-nenrei-kishu/)\n\n"
            f"## 出典\n\n{SRC.format(y=year)}\n")
    return front("hinba", 8, title, desc, lead, "g-turf-winter", year), body


# ---------- 9. 枠番・脚質 ----------
def pos4(x: dict):
    c = [int(n) for n in re.findall(r"\d+", x.get("corners") or "")]
    return c[-1] if c else None


def waku(year: int, rs: list[dict], past: dict[int, list[dict]]) -> tuple:
    def frame_g(rs_):
        g = defaultdict(list)
        for r in rs_:
            if flat(r):
                for x in runners(r):
                    if x.get("frame"):
                        g[int(x["frame"])].append(x)
        return g
    def pos_g(rs_):
        g = defaultdict(list)
        for r in rs_:
            if not flat(r):
                continue
            for x in runners(r):
                p = pos4(x)
                if p is None:
                    continue
                k = "4コーナー1番手" if p == 1 else "2〜4番手" if p <= 4 else "5〜9番手" if p <= 9 else "10番手以下"
                g[k].append(x)
        return g
    F = frame_g(rs)
    Fp = frame_g([r for y in sorted(past)[-10:] for r in past[y]])
    P = pos_g(rs)
    Pp = pos_g([r for y in sorted(past)[-10:] for r in past[y]])
    PK = ["4コーナー1番手", "2〜4番手", "5〜9番手", "10番手以下"]
    t1 = ("| 枠番 | 成績 | 勝率 | 3着内率 | 過去10年の3着内率 |\n|---|---|---|---|---|\n"
          + "".join(f"| {k}枠 | {fmt(rec(F[k]))} | {rec(F[k])['wr']:.0f}% | {rec(F[k])['r3']:.0f}% | {rec(Fp[k])['r3']:.0f}% |\n" for k in range(1, 9) if F[k]))
    t2 = ("| 4コーナーの位置 | 成績 | 勝率 | 3着内率 | 過去10年の3着内率 |\n|---|---|---|---|---|\n"
          + "".join(f"| {k} | {fmt(rec(P[k]))} | {rec(P[k])['wr']:.0f}% | {rec(P[k])['r3']:.0f}% | {rec(Pp[k])['r3']:.0f}% |\n" for k in PK if P[k]))
    lead_f = max(range(1, 9), key=lambda k: rec(F[k])["r3"] if F[k] else -1)
    nige = rec(P["4コーナー1番手"])
    lead = (f"{year}年のJRAの平地の重賞で、3着以内に入る割合が最も高い枠は{lead_f}枠（{rec(F[lead_f])['r3']:.0f}%）。"
            f"4コーナーを先頭で回った馬は{nige['n']}頭中{nige['w']}頭が勝ち、3着内率は{nige['r3']:.0f}%（過去10年は{rec(Pp['4コーナー1番手'])['r3']:.0f}%）。{asof(rs)}までの集計。")
    title = f"{year}年のJRA重賞 枠番・脚質の傾向｜逃げ・先行の3着内率と内枠・外枠（{asof(rs)}時点）"
    desc = f"{year}年のJRAの平地の重賞を、枠番と4コーナーの位置（逃げ・先行・差し・追い込み）で分けて集計し、過去10年と比べた。"
    body = (f"平地のJRAの重賞（G1・G2・G3）の全出走馬を集計した。過去10年は{sorted(past)[-10] if len(past) >= 10 else min(past)}〜{year - 1}年。\n\n"
            f"## 枠番別の成績\n\n{t1}\n## 4コーナーの位置別の成績\n\n4コーナーで何番手を走っていたか（JRAの成績の通過順位）で分けた。\n\n{t2}\n{CAUTION}\n\n"
            f"## あわせて読みたい\n\n- [{year}年の重賞 1番人気の成績](/column/year{year}-ninki/)\n- [{year}年のG1全レース結果](/column/year{year}-g1-kekka/)\n\n"
            f"## 出典\n\n{SRC.format(y=year)}\n")
    return front("waku", 9, title, desc, lead, "g-turf-winter", year), body


# ---------- 書き出し ----------
def write(year: int, slug: str, fm: dict, body: str, today: str) -> bool:
    p = COLS / f"year{year}-{slug}.md"
    old_body, date, updated = "", FIRST_DATE, ""
    if p.exists():
        t = p.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", t, re.S)
        if m:
            old_body = m.group(2)
            d = re.search(r"^date:\s*(\S+)", m.group(1), re.M)
            u = re.search(r"^updated:\s*(\S+)", m.group(1), re.M)
            date = d.group(1) if d else date
            updated = u.group(1) if u else ""
            # 題名・説明の日付（◯月◯日更新）だけが変わったときも本文は同じなので、本文で比べる
    if old_body.strip() == body.strip() and p.exists():
        return False
    if p.exists():
        updated = today
    meta = dict(fm)
    meta.update(date=date, draft="false")
    if updated and updated > date:
        meta["updated"] = updated
    keys = ["title", "description", "lead", "date", "updated", "draft", "order", "series", "hero"]
    head = "\n".join(f"{k}: {str(meta[k]).replace(chr(10), ' ')}" for k in keys if k in meta)
    p.write_text(f"---\n{head}\n---\n{body}", encoding="utf-8")
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.now(JST).year)
    a = ap.parse_args()
    y = a.year
    sched = load(y)
    rs = done(sched)
    if len(rs) < 30:
        print("まだレースが少ない", len(rs))
        return
    prev = done(load(y - 1))
    past = {k: done(load(k)) for k in range(y - 10, y)}
    past = {k: v for k, v in past.items() if v}
    today = datetime.now(JST).strftime("%Y-%m-%d")
    arts = [
        ("g1-kekka",) + g1(y, rs, sched),
        ("kouhaitou",) + kouhaitou(y, rs, prev),
        ("kishu",) + people(y, rs, prev, "jockey"),
        ("chokyoshi",) + people(y, rs, prev, "trainer"),
        ("ninki",) + ninki(y, rs, past),
        ("3sai",) + sedai(y, rs, sched, 3),
        ("2sai",) + sedai(y, rs, sched, 2),
        ("hinba",) + hinba(y, rs, past),
        ("waku",) + waku(y, rs, past),
    ]
    n = 0
    for slug, fm, body in arts:
        if write(y, slug, fm, body, today):
            n += 1
            print("wrote", f"year{y}-{slug}.md")
    print("記事:", n)


if __name__ == "__main__":
    main()
