"""JRAのG1の記録を、過去20年あまりの全着順（JRA公式の成績）から集計した記事を作る。AIは呼ばない。

  荒れるG1・堅いG1のランキング / 3連単の高配当ランキング / 騎手・調教師のG1勝利数ランキング /
  同じG1を続けて勝った馬 / 年齢の記録 / 牝馬が牡馬を破ったG1

data/graded_hist（graded_hist.py が集めた2006年以降のJRAの重賞の成績）だけを使う。2007〜2015年は格（G1など）の記録が
欠けているので、同じレースのいちばん近い年の格で補う。毎日の graded ワークフローで作り直し、本文が変わったときだけ updated を今日にする。
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import graded_cols as G

JST = timezone(timedelta(hours=9))
FIRST_DATE = "2026-11-20"
SERIES = "g1kiroku"


def g1_races() -> list[tuple[str, int, dict]]:
    """[(slug, 年, レース)]：平地のG1で、結果が出ているもの。"""
    G._init_names()
    K = G.keyed(G.load_all())
    out = []
    for slug, ys in K.items():
        known = {y: r["grade"] for y, r in ys.items() if r.get("grade")}
        conds = {y: r["cond"] for y, r in ys.items() if r.get("cond")}
        for y, r in ys.items():
            if r.get("surface") == "障":  # 障害のG1は数えない
                continue
            g = r.get("grade") or (known[min(known, key=lambda k: (abs(k - y), k))] if known else "")
            if not r.get("cond") and conds:  # 2006年は出走条件の記録が欠けているので、いちばん近い年の条件で補う
                r["cond"] = conds[min(conds, key=lambda k: (abs(k - y), k))]
            if g == "G1" and G.runners(r) and any(G.fin(x) == 1 for x in G.runners(r)):
                out.append((slug, y, r))
    out.sort(key=lambda t: t[2]["date"])
    return out


def rname(slug: str, r: dict) -> str:
    return G.NAME_BY_SLUG.get(slug) or G.expand(r.get("abbr", ""))


def who(xs: list[dict], pop: bool = True) -> str:
    if not xs:
        return "―"
    return "・".join(f"{x['name']}（{x['pop']}）" if pop else x["name"] for x in xs)


def span(rs) -> str:
    a, b = rs[0][2]["date"], rs[-1][2]["date"]
    return f"{a[:4]}年〜{b[:4]}年{int(b[4:6])}月{int(b[6:8])}日"


CAUTION = ("> 数字はJRA公式の成績から集計した。海外・地方のG1と障害のG1は含まない。2007〜2015年は格の記録が、2006年は出走条件の記録が欠けているため、"
           "同じレースのいちばん近い年の記録で補った。馬券は20歳から購入できる。")
LINKS = ("## あわせて読みたい\n\n- [荒れるG1・堅いG1ランキング](/column/g1-areru-ranking/)\n- [G1の3連単 高配当ランキング](/column/g1-kouhaitou-ranking/)\n"
         "- [G1の騎手ランキング](/column/g1-kishu-ranking/)\n- [G1の調教師ランキング](/column/g1-chokyoshi-ranking/)\n"
         "- [同じG1を続けて勝った馬](/column/g1-renpa/)\n- [G1の年齢の記録](/column/g1-nenrei-kiroku/)\n- [牝馬が牡馬を破ったG1](/column/g1-hinba-kachi/)\n"
         "- [2026年のG1全レース結果](/column/year2026-g1-kekka/)\n")
SRC = "## 出典\n\n- JRA公式「重賞競走一覧」各年の各レースの成績（このサイトが集めたJRAの重賞の全着順）\n"


def links(me: str) -> str:
    return "\n".join(l for l in LINKS.split("\n") if f"/column/{me}/" not in l) + "\n"


# ---------- 1. 荒れるG1・堅いG1 ----------
def areru(rs) -> tuple:
    by = defaultdict(list)
    for slug, y, r in rs:
        by[slug].append((y, r))
    stat = []
    for slug, v in by.items():
        if len(v) < 8:
            continue
        p1 = [x for y, r in v for x in G.runners(r) if x["pop"] == 1]
        w1 = sum(G.fin(x) == 1 for x in p1)
        t3 = [G.pay1(r, "3連単") for y, r in v if G.pay1(r, "3連単")]
        winpop = [x["pop"] for y, r in v for x in G.runners(r) if G.fin(x) == 1]
        med = sorted(t3)[len(t3) // 2] if t3 else 0
        stat.append(dict(slug=slug, name=rname(slug, v[-1][1]), n=len(v), w1=w1, r1=100 * w1 / max(1, len(p1)),
                         r13=100 * sum(G.fin(x) <= 3 for x in p1) / max(1, len(p1)), med=med,
                         low=sum(p >= 4 for p in winpop), maxpop=max(winpop)))
    hard = sorted(stat, key=lambda s: (-s["r1"], s["med"]))
    wild = sorted(stat, key=lambda s: (-s["med"], s["r1"]))
    t = ("| 順位 | レース | 回数 | 1番人気の勝ち | 1番人気の3着内率 | 3連単の中央値 | 4番人気以下の勝ち | 最も人気のない勝ち馬 |\n"
         "|---|---|---|---|---|---|---|---|\n")
    th = t + "".join(f"| {i} | {s['name']} | {s['n']} | {s['w1']}回（{s['r1']:.0f}%） | {s['r13']:.0f}% | {G.man(s['med'])} | {s['low']}回 | {s['maxpop']}番人気 |\n"
                     for i, s in enumerate(hard, 1))
    tw = t + "".join(f"| {i} | {s['name']} | {s['n']} | {s['w1']}回（{s['r1']:.0f}%） | {s['r13']:.0f}% | {G.man(s['med'])} | {s['low']}回 | {s['maxpop']}番人気 |\n"
                     for i, s in enumerate(wild[:10], 1))
    a, b = hard[0], wild[0]
    lead = (f"JRAの平地のG1を、{span(rs)}の結果で比べた。1番人気がいちばん勝っているのは{a['name']}（{a['n']}回で{a['w1']}勝、勝率{a['r1']:.0f}%）。"
            f"3連単の配当の真ん中の値（中央値）がいちばん高い、つまり荒れやすいのは{b['name']}（{G.man(b['med'])}）。")
    title = f"荒れるG1・堅いG1ランキング｜1番人気の勝率1位は{a['name']}、3連単が高いのは{b['name']}（過去20年）"
    desc = f"JRAの平地のG1を、1番人気の勝率と3連単の配当の中央値で並べた。{span(rs)}のJRA公式の成績から集計。堅いのは{a['name']}、荒れやすいのは{b['name']}。"
    body = (f"レースごとに、1番人気の成績と3連単の配当の中央値（真ん中の値）を並べた。中央値は、年に1度の大荒れに引っぱられにくい。"
            f"8回以上行われたG1だけを比べている。（　）の数字は割合。\n\n## 1番人気が強いG1（1番人気の勝率の順）\n\n{th}\n"
            f"## 荒れやすいG1（3連単の中央値の順、上位10）\n\n{tw}\n{CAUTION}\n\n{links('g1-areru-ranking')}\n{SRC}")
    return ("g1-areru-ranking", 1, title, desc, lead), body


# ---------- 2. 高配当 ----------
def kouhaitou(rs) -> tuple:
    out = ""
    best = {}
    for k in ("3連単", "単勝", "馬連"):
        v = sorted(((G.pay1(r, k) or 0, slug, y, r) for slug, y, r in rs if G.pay1(r, k)), key=lambda t: -t[0])[:15]
        best[k] = v[0] if v else None
        out += (f"\n## {k}の高配当トップ15\n\n| 順位 | 配当 | 年 | レース | 1〜3着（人気） |\n|---|---|---|---|---|\n"
                + "".join(f"| {i} | {G.man(p)} | {y} | {rname(s, r)} | {who(G.runners(r) and [x for x in G.runners(r) if G.fin(x) == 1])} → "
                          f"{who([x for x in G.runners(r) if G.fin(x) == 2])} → {who([x for x in G.runners(r) if G.fin(x) == 3])} |\n"
                          for i, (p, s, y, r) in enumerate(v, 1)))
    t3 = [G.pay1(r, "3連単") for _, _, r in rs if G.pay1(r, "3連単")]
    over = sum(v >= 1000000 for v in t3)
    p, s, y, r = best["3連単"]
    lead = (f"JRAの平地のG1で、3連単の最高配当は{y}年の{rname(s, r)}の{G.man(p)}。{span(rs)}の{len(t3)}レースのうち、"
            f"3連単が100万円を超えたのは{over}レース。")
    title = f"G1の高配当ランキング｜3連単の最高は{y}年{rname(s, r)}の{G.man(p)}（過去20年）"
    desc = f"JRAの平地のG1の配当を、3連単・単勝・馬連の高い順に15位まで並べた。{span(rs)}のJRA公式の成績から集計。3連単100万円超えは{over}回。"
    body = f"払戻金は100円あたり。（　）の数字は人気。\n{out}\n{CAUTION}\n\n{links('g1-kouhaitou-ranking')}\n{SRC}"
    return ("g1-kouhaitou-ranking", 2, title, desc, lead), body


# ---------- 3・4. 騎手・調教師 ----------
def people(rs, key: str) -> tuple:
    jp = "騎手" if key == "jockey" else "調教師"
    w = Counter()
    ride = Counter()
    t3 = Counter()
    last = {}
    races = defaultdict(list)
    for slug, y, r in rs:
        for x in G.runners(r):
            k = x.get(key)
            if not k:
                continue
            ride[k] += 1
            if G.fin(x) <= 3:
                t3[k] += 1
            if G.fin(x) == 1:
                w[k] += 1
                last[k] = (y, rname(slug, r), x["name"])
                races[k].append(rname(slug, r))
    rank = sorted(w.items(), key=lambda kv: (-kv[1], -t3[kv[0]]))[:20]
    t = f"| 順位 | {jp} | G1の勝ち | 3着以内 | 出走 | 勝率 | 最近のG1勝ち |\n|---|---|---|---|---|---|---|\n"
    for i, (k, v) in enumerate(rank, 1):
        y, rn, hn = last[k]
        t += f"| {i} | {k} | {v} | {t3[k]} | {ride[k]} | {100 * v / ride[k]:.0f}% | {y}年{rn}（{hn}） |\n"
    top = rank[0]
    most = Counter(races[top[0]]).most_common(1)[0]
    lead = (f"{span(rs)}にJRAの平地のG1を最も多く勝った{jp}は{top[0]}で{top[1]}勝。"
            f"いちばん多く勝ったレースは{most[0]}（{most[1]}勝）。")
    title = f"G1の{jp}ランキング｜最多は{top[0]}の{top[1]}勝（過去20年）"
    desc = f"JRAの平地のG1の勝ち数を{jp}ごとに数え、上位20人を並べた。{span(rs)}のJRA公式の成績から集計。1位は{top[0]}（{top[1]}勝）。"
    body = (f"{span(rs)}のJRAの平地のG1で、{jp}ごとの勝ち数を数えた。\n\n## G1の勝ち数（上位20人）\n\n{t}\n{CAUTION}\n\n"
            f"{links('g1-kishu-ranking' if key == 'jockey' else 'g1-chokyoshi-ranking')}\n{SRC}")
    return (("g1-kishu-ranking", 3) if key == "jockey" else ("g1-chokyoshi-ranking", 4)) + (title, desc, lead), body


# ---------- 5. 連覇 ----------
def renpa(rs) -> tuple:
    by = defaultdict(dict)
    for slug, y, r in rs:
        by[slug][y] = r
    rows = []
    for slug, ys in by.items():
        win = {y: [x["name"] for x in G.runners(r) if G.fin(x) == 1] for y, r in ys.items()}
        for nm in {n for v in win.values() for n in v}:
            yrs = sorted(y for y, v in win.items() if nm in v)
            # 続けて勝った年の並び（行われなかった年は飛ばしてよい）
            run = [yrs[0]]
            for y in yrs[1:]:
                held = [k for k in ys if run[-1] < k < y]
                if not held:
                    run.append(y)
                else:
                    if len(run) >= 2:
                        rows.append((len(run), slug, nm, list(run), ys))
                    run = [y]
            if len(run) >= 2:
                rows.append((len(run), slug, nm, list(run), ys))
    rows.sort(key=lambda t: (-t[0], t[3][0]))
    tb = "| 連続 | 馬名 | レース | 勝った年 |\n|---|---|---|---|\n"
    for n, slug, nm, yrs, ys in rows:
        tb += f"| {n}連覇 | {nm} | {rname(slug, ys[yrs[-1]])} | {'・'.join(str(y) for y in yrs)}年 |\n"
    multi = Counter()
    for slug, y, r in rs:
        for x in G.runners(r):
            if G.fin(x) == 1:
                multi[x["name"]] += 1
    mt = ("| 順位 | 馬名 | JRAのG1の勝ち |\n|---|---|---|\n"
          + "".join(f"| {i} | {n} | {c} |\n" for i, (n, c) in enumerate(sorted(multi.items(), key=lambda kv: -kv[1])[:15], 1)))
    three = [t for t in rows if t[0] >= 3]
    lead = (f"{span(rs)}に、同じJRAのG1を2年以上続けて勝った馬は{len(rows)}例。"
            + (f"3連覇は{'、'.join(f'{t[2]}（{rname(t[1], t[4][t[3][-1]])}）' for t in three)}。" if three else "3連覇した馬はいない。")
            + f"この期間にJRAのG1を最も多く勝ったのは{sorted(multi.items(), key=lambda kv: -kv[1])[0][0]}。")
    title = f"同じG1を続けて勝った馬の一覧｜連覇{len(rows)}例と、G1をたくさん勝った馬（過去20年）"
    desc = f"JRAの平地のG1を2年以上続けて勝った馬（連覇）を一覧にした。{span(rs)}のJRA公式の成績から集計。JRAのG1を多く勝った馬のランキングつき。"
    body = (f"## 同じG1を続けて勝った馬\n\n{tb}\n## JRAのG1をたくさん勝った馬（上位15頭）\n\n{span(rs)}に勝ったJRAの平地のG1の数。海外のG1と、2005年以前に勝ったG1は含まない（ディープインパクトなど）。\n\n{mt}\n"
            f"{CAUTION}\n\n{links('g1-renpa')}\n{SRC}")
    return ("g1-renpa", 5, title, desc, lead), body


# ---------- 6. 年齢 ----------
def nenrei(rs) -> tuple:
    wins = [(x.get("age") or 0, slug, y, r, x) for slug, y, r in rs for x in G.runners(r) if G.fin(x) == 1]
    old = sorted(wins, key=lambda t: (-t[0], -t[2]))[:12]
    by_age = Counter(t[0] for t in wins)
    open3 = [t for t in wins if t[0] == 3 and "以上" in (t[3].get("cond") or "")]
    ta = ("| 年齢 | 勝った回数 |\n|---|---|\n" + "".join(f"| {a}歳 | {c} |\n" for a, c in sorted(by_age.items())))
    to = ("| 年齢 | 年 | レース | 勝ち馬（人気） |\n|---|---|---|---|\n"
          + "".join(f"| {a}歳 | {y} | {rname(s, r)} | {x['name']}（{x['pop']}） |\n" for a, s, y, r, x in old))
    t3 = ("| 年 | レース | 勝ち馬（人気） |\n|---|---|---|\n"
          + "".join(f"| {y} | {rname(s, r)} | {x['name']}（{x['pop']}） |\n" for a, s, y, r, x in sorted(open3, key=lambda t: t[3]["date"], reverse=True)))
    mx = old[0]
    lead = (f"{span(rs)}のJRAの平地のG1で、最年長の勝ち馬は{mx[0]}歳（{mx[2]}年{rname(mx[1], mx[3])}の{mx[4]['name']}）。"
            f"古馬と一緒に走るG1を3歳で勝った例は{len(open3)}回ある。")
    title = f"G1の年齢の記録｜最年長の勝ち馬は{mx[0]}歳、3歳で古馬を破ったG1は{len(open3)}回（過去20年）"
    desc = f"JRAの平地のG1の勝ち馬を年齢で分けた。最年長の勝ち馬、年齢別の勝ち数、3歳で古馬相手のG1を勝った馬を、{span(rs)}のJRA公式の成績から集計。"
    body = (f"## 年齢別の勝ち数\n\n{ta}\n## 年齢の高い勝ち馬\n\n{to}\n## 3歳で古馬を相手に勝ったG1\n\n「3歳以上」のG1を3歳で勝った例。\n\n{t3}\n"
            f"{CAUTION}\n\n{links('g1-nenrei-kiroku')}\n{SRC}")
    return ("g1-nenrei-kiroku", 6, title, desc, lead), body


# ---------- 7. 牝馬 ----------
def fem_only(r: dict) -> bool:
    c = (r.get("cond") or "").replace(" ", "")
    return c.endswith("牝") and "牡・牝" not in c


def hinba(rs) -> tuple:
    mixed = [(slug, y, r) for slug, y, r in rs if not fem_only(r)]
    wins = [(slug, y, r, x) for slug, y, r in mixed for x in G.runners(r) if G.fin(x) == 1 and x.get("sex") == "牝"]
    tw = ("| 年 | レース | 勝ち馬（人気） | 年齢 |\n|---|---|---|---|\n"
          + "".join(f"| {y} | {rname(s, r)} | {x['name']}（{x['pop']}） | {x.get('age', '')}歳 |\n" for s, y, r, x in sorted(wins, key=lambda t: t[2]["date"], reverse=True)))
    cnt = Counter(x["name"] for _, _, _, x in wins)
    by_y = Counter(y for _, y, _, _ in wins)
    top = cnt.most_common(1)[0]
    lead = (f"{span(rs)}に、牝馬限定でないJRAのG1を牝馬が勝ったのは{len(wins)}回（対象{len(mixed)}レース）。"
            f"最も多く勝ったのは{top[0]}（{top[1]}勝）。1年で最も多かったのは{by_y.most_common(1)[0][0]}年の{by_y.most_common(1)[0][1]}回。")
    title = f"牝馬が牡馬を破ったG1一覧｜{len(wins)}回、最多は{top[0]}の{top[1]}勝（過去20年）"
    desc = f"牝馬限定でないJRAのG1を牝馬が勝った例を、{span(rs)}のJRA公式の成績から一覧にした。年ごとの回数と、多く勝った牝馬のランキングつき。"
    ty = "| 年 | 回数 |\n|---|---|\n" + "".join(f"| {y} | {by_y.get(y, 0)} |\n" for y in sorted({y for _, y, _ in rs}))
    tc = "| 馬名 | 勝ち |\n|---|---|\n" + "".join(f"| {n} | {c} |\n" for n, c in cnt.most_common() if c >= 2)
    body = (f"## 年ごとの回数\n\n{ty}\n## 2勝以上した牝馬\n\n{tc}\n## 牝馬が勝った牡馬混合のG1（新しい順）\n\n{tw}\n"
            f"{CAUTION}\n\n{links('g1-hinba-kachi')}\n{SRC}")
    return ("g1-hinba-kachi", 7, title, desc, lead), body


def write(slug: str, order: int, title: str, desc: str, lead: str, body: str, today: str) -> bool:
    p = G.COLS / f"{slug}.md"
    date, updated = FIRST_DATE, ""
    if p.exists():
        t = p.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", t, re.S)
        if m:
            if m.group(2).strip() == body.strip():
                return False
            d = re.search(r"^date:\s*(\S+)", m.group(1), re.M)
            date = d.group(1) if d else date
        updated = today
    meta = {"title": title, "description": desc, "lead": lead, "date": date}
    if updated and updated > date:
        meta["updated"] = updated
    meta.update({"draft": "false", "order": order, "series": SERIES, "hero": "g-turf-autumn"})
    head = "\n".join(f"{k}: {str(v).replace(chr(10), ' ')}" for k, v in meta.items())
    p.write_text(f"---\n{head}\n---\n{body}", encoding="utf-8")
    return True


def main() -> None:
    rs = g1_races()
    today = datetime.now(JST).strftime("%Y-%m-%d")
    n = 0
    for (slug, order, title, desc, lead), body in (areru(rs), kouhaitou(rs), people(rs, "jockey"), people(rs, "trainer"), renpa(rs), nenrei(rs), hinba(rs)):
        if write(slug, order, title, desc, lead, body, today):
            n += 1
            print("wrote", slug)
    print("記事:", n)


if __name__ == "__main__":
    main()
