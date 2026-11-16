"""重賞の「過去10年データ記事」を自動で作る（集計だけで作り、AIは呼ばない）。

元データは graded_hist.py が集めた data/graded_hist/<年>.json（JRA公式の全着順・払戻）。
今日から --days 日以内に行われる JRA の重賞について、レースごとに4本の記事を columns/ に書く：

  <slug>-kako10nen.md     過去10年の結果一覧（勝ち馬・2〜3着・配当・共通点）
  <slug>-ninki-waku.md    人気・枠順・脚質の傾向
  <slug>-nenrei-kishu.md  年齢・性別・騎手・厩舎の傾向
  <slug>-jinx.md          ジンクス・データの偏り（数字の偏りが大きいものを拾う）

その年の分をすでに書いていれば何もしない（翌年、同じファイルを新しい10年分で書き直す）。
数字はすべて集計から作る。過去の開催が6回に満たないレース、名前から重賞ページ（/graded/<slug>/）を決められないレースは書かない。

  python graded_cols.py --days 16
  python graded_cols.py --slug fukushima-kinen --force
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from common import DATA_DIR

ROOT = DATA_DIR.parent
sys.path.insert(0, str(ROOT / "site"))
import extra  # noqa: E402

JST = timezone(timedelta(hours=9))
HIST = DATA_DIR / "graded_hist"
COLS = ROOT / "columns"
WD = "月火水木金土日"
MIN_RUNS = 6
# 手で書いた特集がある年は自動記事を作らない（同じ内容のページを2つ作らないため）
MANUAL = {2026: {"queen-elizabeth-cup", "mile-championship", "japan-cup", "champions-cup", "arima-kinen"}}
ABBR = [("東スポ杯", "東京スポーツ杯"), ("アメリカJCC", "アメリカジョッキークラブカップ"), ("ジャパンC", "ジャパンカップ"), ("チャンピオンズC", "チャンピオンズカップ"),
        ("ジュベナイルF", "ジュベナイルフィリーズ"), ("フューチュリティS", "フューチュリティステークス"), ("NHKマイルC", "NHKマイルカップ"),
        ("ダービー卿CT", "ダービー卿チャレンジトロフィー"), ("京成杯AH", "京成杯オータムハンデキャップ"), ("スプリングC", "スプリングカップ"),
        ("チャレンジC", "チャレンジカップ"), ("クイーンC", "クイーンカップ"), ("阪神C", "阪神カップ"), ("エプソムC", "エプソムカップ"), ("アーリントンC", "アーリントンカップ"),
        ("フラワーC", "フラワーカップ"), ("エルムS", "エルムステークス")]
HASH_RE = re.compile(r"-[0-9a-f]{8}$")


def expand(abbr: str) -> str:
    n = abbr
    for a, b in ABBR:
        n = n.replace(a, b)
    n = re.sub(r"S$", "ステークス", n)
    n = re.sub(r"C$", "カップ", n)
    return n


def load_all() -> dict[int, list[dict]]:
    out = {}
    for f in sorted(HIST.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        out[int(d["year"])] = d.get("races", [])
    return out


def keyed(all_: dict[int, list[dict]]) -> dict[str, dict[int, dict]]:
    """レースを年をまたいで束ねる：{slug: {年: レース}}。slug は成績ページの正式名から決め、決まらないものは一覧の略称で束ねる。"""
    def slug_of(r):
        t = re.sub(r"\s+障害.*$", "", extra.clean_name(r.get("title") or ""))
        s = extra.graded_slug(t, "x") if t else ""
        return "" if not s or HASH_RE.search(s) else s
    by_abbr: dict[str, str] = {}
    for y in sorted(all_, reverse=True):
        for r in all_[y]:
            r["abbr"] = re.sub(r"^(?:新設)?重賞", "", r["abbr"])
            s = slug_of(r)
            if s:
                by_abbr.setdefault(r["abbr"], s)
    out: dict[str, dict[int, dict]] = defaultdict(dict)
    for y, rs in all_.items():
        for r in rs:
            s = slug_of(r) or by_abbr.get(r["abbr"]) or extra.graded_slug(expand(r["abbr"]), "x")
            if HASH_RE.search(s):
                s = "abbr:" + r["abbr"]
            out[s][y] = r
    return out


# ---------- 集計 ----------
def runners(r: dict) -> list[dict]:
    return [x for x in r.get("rows") or [] if x.get("pop")]


def fin(x) -> int:
    return x["fin"] if isinstance(x.get("fin"), int) else 99


def rec(v: list[dict]) -> dict:
    n = len(v)
    w = sum(fin(x) == 1 for x in v)
    t2 = sum(fin(x) <= 2 for x in v)
    t3 = sum(fin(x) <= 3 for x in v)
    return dict(n=n, w=w, s=t2 - w, t=t3 - t2, o=n - t3, wr=100 * w / n if n else 0, r2=100 * t2 / n if n else 0, r3=100 * t3 / n if n else 0)


def fmt(v: dict) -> str:
    return f"{v['w']}-{v['s']}-{v['t']}-{v['o']}"


def row(label: str, v: dict) -> str:
    return f"| {label} | {fmt(v)} | {v['wr']:.0f}% | {v['r2']:.0f}% | {v['r3']:.0f}% | {v['n']} |"


THEAD = "| 成績 | 勝率 | 連対率 | 3着内率 | 頭数 |\n|---|---|---|---|---|---|\n"


def popb(p: int) -> str:
    return "1番人気" if p == 1 else "2番人気" if p == 2 else "3番人気" if p == 3 else "4〜5番人気" if p <= 5 else "6〜9番人気" if p <= 9 else "10番人気以下"


POPS = ["1番人気", "2番人気", "3番人気", "4〜5番人気", "6〜9番人気", "10番人気以下"]


def pay1(r: dict, kind: str):
    v = (r.get("pay") or {}).get(kind) or []
    return v[0][1] if v else None


def yen(v) -> str:
    return f"{v:,}円" if v else "―"


def man(v: int) -> str:
    """12万3,450円のような読みやすい表記。"""
    if v >= 10000:
        a, b = divmod(v, 10000)
        return f"{a}万{b:,}円" if b else f"{a}万円"
    return f"{v:,}円"


def surf(s: str) -> str:
    return {"芝": "芝", "ダ": "ダート", "障": "障害"}.get(s, s)


def course_of(r: dict) -> str:
    return f"{r.get('venue')}{surf(r.get('surface') or '')}{r.get('distance') or ''}m"


def pos4(x: dict):
    c = [int(n) for n in re.findall(r"\d+", x.get("corners") or "")]
    return c[-1] if c else None


def names(rs: list[dict], pop: bool = True) -> str:
    if not rs:
        return "―"
    return "・".join(f"{x['name']}（{x['pop']}）" if pop else x["name"] for x in rs) + ("※同着" if len(rs) > 1 else "")


class Race:
    def __init__(self, slug: str, years: dict[int, dict], year: int):
        self.slug, self.year = slug, year
        self.now = years[year]
        self.past = {y: r for y, r in years.items() if y < year and runners(r) and r.get("pay")}
        self.ys = sorted(self.past, reverse=True)[:10]
        self.past = {y: self.past[y] for y in self.ys}
        self.name = self._name()
        self.R = [dict(x, year=y) for y in self.ys for x in runners(self.past[y])]
        self.same = [y for y in self.ys if (self.past[y].get("venue"), self.past[y].get("surface"), self.past[y].get("distance"))
                     == (self.now.get("venue"), self.now.get("surface"), self.now.get("distance"))]

    def _name(self) -> str:
        if self.slug in NAME_BY_SLUG:
            return NAME_BY_SLUG[self.slug]
        return expand(self.now["abbr"])

    @property
    def span(self) -> str:
        return f"{self.ys[-1]}〜{self.ys[0]}年"

    @property
    def n(self) -> int:
        return len(self.ys)

    def top(self, y: int, k: int) -> list[dict]:
        return [x for x in runners(self.past[y]) if fin(x) == k]

    def date_txt(self) -> str:
        d = datetime.strptime(self.now["date"], "%Y%m%d")
        return f"{d.year}年{d.month}月{d.day}日（{WD[d.weekday()]}）"

    def grade(self) -> str:
        return self.now.get("grade") or ""

    def src(self) -> str:
        links = "・".join(f"[{y}年]({self.past[y]['url']})" for y in self.ys if self.past[y].get("url"))
        return f"- JRA公式「{self.name}」各年の成績：{links}\n- 今年の日程・条件：JRA公式「[{self.year}年 重賞競走一覧](https://www.jra.go.jp/datafile/seiseki/replay/{self.year}/jyusyo.html)」"

    def venue_note(self) -> str:
        diff = [y for y in self.ys if y not in self.same]
        cur = course_of(self.now)
        if not diff:
            return f"{self.n}回とも{cur}で行われた。"
        g = defaultdict(list)
        for y in diff:
            g[course_of(self.past[y])].append(y)
        parts = "、".join(f"{'・'.join(str(y) for y in sorted(v))}年は{k}" for k, v in g.items())
        return f"今年と同じ{cur}で行われたのは{len(self.same)}回。{parts}で行われた。" if self.same else f"今年は{cur}で行われる。過去は{parts}で行われた。"


NAME_BY_SLUG: dict[str, str] = {}


def _init_names() -> None:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from race_guides import RACES
        for slug, name, *_ in RACES:
            NAME_BY_SLUG[slug] = name
    except Exception:  # noqa: BLE001
        pass
    for k, v in getattr(extra, "GRADED_SLUG", {}).items():
        NAME_BY_SLUG.setdefault(v, k)


def hero(rc: Race) -> str:
    s, d = rc.now.get("surface"), rc.now.get("distance") or 0
    m = int(rc.now["date"][4:6])
    if s == "ダ":
        return "g-dirt-day"
    if s == "芝" and d <= 1400:
        return "g-sprint"
    if s == "芝" and d >= 2500:
        return "g-stayer"
    return "g-turf-winter" if m in (12, 1, 2) else "g-turf-autumn"


def front(rc: Race, kind: str, order: int, title: str, desc: str, lead: str, hero_: str | None = None) -> str:
    today = datetime.now(JST).strftime("%Y-%m-%d")
    meta = {"title": title, "description": desc, "lead": lead, "date": today, "draft": "false", "order": order, "series": "gdata",
            "race": rc.slug, "race_name": rc.name, "race_date": rc.now["date"], "year": rc.year, "kind": kind, "hero": hero_ or hero(rc)}
    return "---\n" + "\n".join(f"{k}: {str(v).replace(chr(10), ' ')}" for k, v in meta.items()) + "\n---\n"


def this_year(rc: Race) -> str:
    r = rc.now
    cond = f"（{r['cond']}）" if r.get("cond") else ""
    return f"{rc.year}年の{rc.name}（{rc.grade()}）は{rc.date_txt().split('年', 1)[1]}、{r['venue']}競馬場の{surf(r['surface'])}{r['distance']}mで行われる{cond}。"


def links(rc: Race, me: str) -> str:
    items = [("kako10nen", "過去10年の結果一覧"), ("ninki-waku", "人気・枠順・脚質の傾向"), ("nenrei-kishu", "年齢・性別・騎手・厩舎の傾向"), ("jinx", "ジンクス")]
    out = [f"- [{rc.name}の{t}](/column/{rc.slug}-{k}/)" for k, t in items if k != me]
    if (DATA_DIR / "race_guides" / f"{rc.slug}.json").exists():
        out.append(f"- [{rc.name}のレースガイドとAI予想](/graded/{rc.slug}/)")
    return "\n".join(out)


CAUTION = ("> 過去の傾向は、これからの結果を約束するものではない。1つのレースの10回分は少ないデータで、強い馬がたまたまそこにいた影響も含まれる。"
           "馬券は20歳から購入できる。")


# ---------- 記事1：過去10年の結果一覧 ----------
def win_pops(rc: Race) -> Counter:
    return Counter(x["pop"] for y in rc.ys for x in rc.top(y, 1))


def pop_sentence(c: Counter) -> str:
    g = [("1番人気", c[1]), ("2〜3番人気", c[2] + c[3]), ("4〜5番人気", c[4] + c[5]), ("6〜9番人気", sum(c[p] for p in range(6, 10))),
         ("10番人気以下", sum(v for p, v in c.items() if p >= 10))]
    return "、".join(f"{k}が{v}頭" for k, v in g if v)


def repeaters(rc: Race) -> list[str]:
    g = defaultdict(list)
    for x in rc.R:
        if fin(x) <= 3:
            g[x["name"]].append(x)
    out = []
    for nm, v in g.items():
        if len(v) >= 2:
            v.sort(key=lambda x: x["year"])
            out.append((len(v), min(fin(x) for x in v), nm + "（" + "、".join(f"{x['year']}年{fin(x)}着" for x in v) + "）"))
    return [t for _, _, t in sorted(out, key=lambda z: (-z[0], z[1]))[:4]]


def kako10(rc: Race) -> str:
    c = win_pops(rc)
    upset = max((x for x in rc.R if fin(x) == 1), key=lambda x: x["pop"])
    t3 = sorted(v for v in (pay1(rc.past[y], "3連単") for y in rc.ys) if v)
    over = sum(v >= 100000 for v in t3)
    lead = (f"{rc.name}の過去{rc.n}回（{rc.span}）の勝ち馬は、{pop_sentence(c)}。"
            + (f"最も人気がなかった勝ち馬は{upset['year']}年の{upset['name']}（{upset['pop']}番人気）。" if upset["pop"] >= 4 else "勝ち馬はすべて3番人気以内だった。")
            + (f"3連単は{man(t3[0])}から{man(t3[-1])}まで開きがあり、10万円を超えたのは{over}回。" if t3 else "") + this_year(rc))
    title = f"{rc.name}過去10年の結果一覧（{rc.span}）｜勝ち馬・人気・枠・配当"
    desc = (f"{rc.name}（{rc.grade()}）{rc.span}の勝ち馬・2着・3着と人気、枠、騎手、勝ち時計、配当をJRA公式の成績から一覧にした。"
            f"勝ち馬は{pop_sentence(c)}。今年は{rc.date_txt()}に{rc.now['venue']}で行われる。")
    t1 = "| 年 | 1着 | 2着 | 3着 |\n|---|---|---|---|\n" + "".join(
        f"| {y} | {names(rc.top(y, 1))} | {names(rc.top(y, 2))} | {names(rc.top(y, 3))} |\n" for y in rc.ys)
    t2 = "| 年 | 勝ち馬 | 性齢 | 枠・馬番 | 騎手 | 勝ち時計 | 開催・馬場 |\n|---|---|---|---|---|---|---|\n"
    for y in rc.ys:
        p = rc.past[y]
        for x in rc.top(y, 1):
            t2 += (f"| {y} | {x['name']} | {x['sex']}{x['age'] or ''} | {x['frame'] or '―'}枠{x['num']}番 | {x['jockey']} | {x['time']} | "
                   f"{p['venue']}{surf(p['surface'])}{p['distance']}m・{p.get('track') or '―'} |\n")
    t3t = "| 年 | 単勝 | 馬連 | 3連複 | 3連単 |\n|---|---|---|---|---|\n" + "".join(
        f"| {y} | {yen(pay1(rc.past[y], '単勝'))} | {yen(pay1(rc.past[y], '馬連'))} | {yen(pay1(rc.past[y], '3連複'))} | {yen(pay1(rc.past[y], '3連単'))} |\n" for y in rc.ys)
    pay_txt = ""
    if t3:
        lo = next(y for y in rc.ys if pay1(rc.past[y], "3連単") == t3[0])
        hi = next(y for y in rc.ys if pay1(rc.past[y], "3連単") == t3[-1])
        pay_txt = (f"3連単の最高は{hi}年の{man(t3[-1])}、最低は{lo}年の{man(t3[0])}。真ん中の値（中央値）は{man(int(median(t3)))}で、"
                   f"10万円を超えたのは{len(t3)}回中{over}回だった。")
    # 共通点
    ages = Counter(x["age"] for y in rc.ys for x in rc.top(y, 1))
    wins = [x for y in rc.ys for x in rc.top(y, 1)]
    inner = sum(1 for x in wins if x["frame"] and x["frame"] <= 4)
    jk = Counter(x["jockey"] for x in wins)
    tr = Counter(x["trainer"] for x in wins)
    bl = [f"- **人気**：{pop_sentence(c)}"]
    if len(ages) > 1:
        bl.append("- **年齢**：" + "、".join(f"{a}歳{n}頭" for a, n in sorted(ages.items()) if a))
    fem = sum(1 for x in wins if x["sex"] == "牝")
    if 0 < fem < len(wins):
        bl.append(f"- **性別**：牝馬が{fem}頭、牡馬・せん馬が{len(wins) - fem}頭")
    if all(x["frame"] for x in wins):
        bl.append(f"- **枠**：1〜4枠から{inner}頭、5〜8枠から{len(wins) - inner}頭")
    multi = [f"{j}騎手が{n}勝" for j, n in jk.most_common() if n >= 2]
    if multi:
        bl.append("- **騎手**：" + "、".join(multi))
    multi_t = [f"{t}厩舎が{n}勝" for t, n in tr.most_common() if n >= 2 and t]
    if multi_t:
        bl.append("- **厩舎**：" + "、".join(multi_t))
    rp = repeaters(rc)
    if rp:
        bl.append("- **続けて好走した馬**：" + "、".join(rp))
    body = ("\n## 勝ち馬と2着・3着（" + rc.span + "）\n\nかっこ内は単勝の人気。\n\n" + t1 + "\n## 勝ち馬の詳細\n\n" + t2 + "\n" + rc.venue_note()
            + "\n\n## 配当\n\n" + t3t + "\n" + pay_txt + "\n\n## 勝ち馬" + str(len(wins)) + "頭の共通点\n\n" + "\n".join(bl)
            + f"\n\n## {rc.year}年に向けて\n\n" + this_year(rc) + "人気や枠、年齢ごとの成績は次の記事にまとめている。\n\n" + links(rc, "kako10nen")
            + "\n\n" + CAUTION + "\n\n## 出典\n\n" + rc.src() + "\n")
    return front(rc, "kako10nen", 1, title, desc, lead) + body


# ---------- 記事2：人気・枠順・脚質 ----------
def ninki(rc: Race) -> str:
    g = defaultdict(list)
    for x in rc.R:
        g[popb(x["pop"])].append(x)
    P = {k: rec(g[k]) for k in POPS}
    p1 = P["1番人気"]
    roi = 100 * sum(pay1(rc.past[x["year"]], "単勝") or 0 for x in g["1番人気"] if fin(x) == 1) / (100 * max(1, len(g["1番人気"])))
    best = max((k for k in POPS[:4]), key=lambda k: (P[k]["r3"], P[k]["wr"]))
    lows = sorted((x for x in rc.R if x["pop"] >= 10 and fin(x) <= 3), key=lambda x: (-x["pop"], -x["year"]))
    t3 = sorted(v for v in (pay1(rc.past[y], "3連単") for y in rc.ys) if v)
    f3 = sorted(v for v in (pay1(rc.past[y], "3連複") for y in rc.ys) if v)
    lead = (f"{rc.name}の1番人気は、過去{rc.n}回で{p1['w']}勝・2着{p1['s']}回・3着{p1['t']}回。単勝を毎回買った場合の回収率は{roi:.0f}%だった。"
            + (f"10番人気以下の馬は3着以内に{len(lows)}回入っている。" if lows else "10番人気以下の馬は、3着以内に1度も入っていない。")
            + (f"3連単の真ん中の値（中央値）は{man(int(median(t3)))}。" if t3 else ""))
    title = f"{rc.name}の人気・枠順・脚質の傾向：1番人気は{p1['w']}勝、3着内率{p1['r3']:.0f}%（過去10年）"
    desc = (f"{rc.name}（{rc.grade()}）{rc.span}の人気別・枠番別・4コーナーの位置別の成績をJRA公式の成績から集計。1番人気は{fmt(p1)}で単勝回収率{roi:.0f}%、"
            f"10番人気以下の3着以内は{len(lows)}回。配当の水準もまとめた。")
    pop_t = "| 人気 " + THEAD.replace("|---|---|---|---|---|---|", "|---|---|---|---|---|---|") + "\n".join(row(k, P[k]) for k in POPS)
    txt = f"3着以内に入る割合が最も高いのは{best}（{P[best]['r3']:.0f}%）。"
    if p1["r3"] < 50:
        txt += f"1番人気の3着内率は{p1['r3']:.0f}%で、半分に届いていない。"
    if lows:
        txt += "10番人気以下で3着以内に入ったのは、" + "、".join(f"{x['year']}年{x['name']}（{x['pop']}番人気{fin(x)}着）" for x in lows[:4]) + ("など。" if len(lows) > 4 else "。")
    p1t = "| 年 | 1番人気 | 着順 | 単勝の払戻 |\n|---|---|---|---|\n"
    for y in rc.ys:
        for x in [x for x in runners(rc.past[y]) if x["pop"] == 1][:1]:
            f_ = fin(x)
            p1t += f"| {y} | {x['name']} | {str(f_) + '着' if f_ < 99 else x['fin']} | {yen(pay1(rc.past[y], '単勝')) if f_ == 1 else '―'} |\n"
    hai = ""
    if t3 and f3:
        hai = ("| 券種 | 最低 | 真ん中の値（中央値） | 最高 |\n|---|---|---|---|\n"
               f"| 3連複 | {yen(f3[0])} | {yen(int(median(f3)))} | {yen(f3[-1])} |\n| 3連単 | {yen(t3[0])} | {yen(int(median(t3)))} | {yen(t3[-1])} |\n")
        fav = Counter(sum(1 for x in runners(rc.past[y]) if fin(x) <= 3 and x["pop"] <= 3) for y in rc.ys)
        hai += ("\n3着以内に入った1〜3番人気の頭数は、" + "、".join(f"{k}頭が{fav[k]}回" for k in (3, 2, 1, 0) if fav[k]) + "。"
                + ("上位人気が総崩れになった年もある。" if fav[0] else "1〜3番人気が1頭も来なかった年はない。"))
    # 枠（今年と同じコースの年だけ。5回に満たなければ全部）
    ys_w = rc.same if len(rc.same) >= 5 else rc.ys
    W = [x for x in rc.R if x["year"] in ys_w and x.get("frame")]
    gw, gw3 = defaultdict(list), defaultdict(list)
    for x in W:
        gw[x["frame"]].append(x)
        gw3["1〜3枠" if x["frame"] <= 3 else "4〜6枠" if x["frame"] <= 6 else "7〜8枠"].append(x)
    waku_t = "| 枠 " + THEAD + "\n".join(row(f"{k}枠", rec(gw[k])) for k in range(1, 9))
    w3 = {k: rec(gw3[k]) for k in ("1〜3枠", "4〜6枠", "7〜8枠")}
    w3_t = "| 枠 " + THEAD + "\n".join(row(k, v) for k, v in w3.items())
    bw = max(w3, key=lambda k: (w3[k]["r3"], w3[k]["wr"]))
    ww = max(w3, key=lambda k: (w3[k]["w"], w3[k]["r3"]))
    waku_txt = ((f"今年と同じ{course_of(rc.now)}で行われた{len(ys_w)}回を集計した。" if ys_w is rc.same and len(rc.same) < rc.n else f"過去{len(ys_w)}回を集計した。" + ("" if len(rc.same) == rc.n else rc.venue_note() + "コースが違う年も含めた数字である。"))
                + f"3着内率が最も高いのは{bw}（{w3[bw]['r3']:.0f}%）、勝ち馬が最も多いのは{ww}（{w3[ww]['w']}頭）。"
                + (f"7〜8枠は延べ{w3['7〜8枠']['n']}頭で勝ち馬がいない。" if w3["7〜8枠"]["n"] and not w3["7〜8枠"]["w"] else "")
                + (f"1〜3枠は延べ{w3['1〜3枠']['n']}頭で勝ち馬がいない。" if w3["1〜3枠"]["n"] and not w3["1〜3枠"]["w"] else ""))
    # 脚質（4コーナーの位置）
    C = [x for x in rc.R if pos4(x)]
    gc = defaultdict(list)
    for x in C:
        p = pos4(x)
        gc["先頭" if p == 1 else "2〜4番手" if p <= 4 else "5〜9番手" if p <= 9 else "10番手以下"].append(x)
    KC = ["先頭", "2〜4番手", "5〜9番手", "10番手以下"]
    kc = {k: rec(gc[k]) for k in KC}
    kyaku = ""
    if len(C) >= 40:
        front_w = kc["先頭"]["w"] + kc["2〜4番手"]["w"]
        tot_w = sum(v["w"] for v in kc.values())
        kyaku = ("\n\n## 4コーナーの位置別の成績（脚質）\n\n最後のコーナーを何番手で回ったかで分けた。\n\n| 4コーナーの位置 " + THEAD
                 + "\n".join(row(k, kc[k]) for k in KC)
                 + f"\n\n勝ち馬{tot_w}頭のうち{front_w}頭は、4コーナーを4番手以内で回っていた。"
                 + (f"10番手以下から勝ったのは{kc['10番手以下']['w']}頭。" if kc["10番手以下"]["w"] else "10番手以下から勝った馬はいない。")
                 + "位置取りはレースの流れで決まるので、レース前には近走の通過順から見当をつけることになる。")
    use = ("このサイトのAI予想は、1レースにつき◎の単勝か複勝を1点だけ買う。◎が1〜2番人気（または単勝4倍未満）なら複勝、3〜5番人気なら単勝、6番人気以下なら買わない"
           "（[単勝と複勝の使い分け](/column/tansho-fukusho/)）。")
    if p1["r3"] >= 70:
        use += f"{rc.name}の1番人気は3着内率{p1['r3']:.0f}%で、複勝なら{rc.n}回中{p1['w'] + p1['s'] + p1['t']}回は払戻があった計算になる。"
    elif p1["r3"] <= 40:
        use += f"{rc.name}の1番人気は3着内率{p1['r3']:.0f}%と信頼しにくく、人気だけで軸を決めにくいレースといえる。"
    w45 = P["4〜5番人気"]["w"] + P["3番人気"]["w"]
    if w45 >= 4:
        use += f"3〜5番人気から{w45}頭が勝っており、少し人気を落とした馬の単勝が合いやすい。"
    body = ("\n## 人気別の成績（" + rc.span + "）\n\n成績は「1着-2着-3着-4着以下」の回数。同着の年は回数が1つ多くなる。\n\n" + pop_t + "\n\n" + txt
            + "\n\n## 1番人気の" + str(rc.n) + "回\n\n" + p1t + (("\n## 配当の水準\n\n" + hai) if hai else "")
            + "\n\n## 枠番別の成績\n\n" + waku_t + "\n\nまとめると次のようになる。\n\n" + w3_t + "\n\n" + waku_txt + kyaku
            + "\n\n## このデータをどう使うか\n\n" + use + "\n\n" + this_year(rc) + "\n\n" + links(rc, "ninki-waku")
            + "\n\n" + CAUTION + "\n\n## 出典\n\n" + rc.src() + "\n")
    return front(rc, "ninki-waku", 2, title, desc, lead, "col-ninki-shoritsu") + body


# ---------- 記事3：年齢・性別・騎手・厩舎 ----------
def nenrei(rc: Race) -> str:
    ga = defaultdict(list)
    for x in rc.R:
        if x.get("age"):
            ga[f"{x['age']}歳" if x["age"] <= 6 else "7歳以上"].append(x)
    A = {k: rec(ga[k]) for k in ("2歳", "3歳", "4歳", "5歳", "6歳", "7歳以上") if ga[k]}
    gs = defaultdict(list)
    for x in rc.R:
        gs["牝馬" if x["sex"] == "牝" else "牡馬・せん馬"].append(x)
    S = {k: rec(gs[k]) for k in ("牡馬・せん馬", "牝馬") if gs[k]}
    gj, gt = defaultdict(list), defaultdict(list)
    for x in rc.R:
        gj[x["jockey"]].append(x)
        if x.get("trainer"):
            gt[x["trainer"]].append(x)

    def rank(g, minn):
        return sorted(((k, rec(v), v) for k, v in g.items() if len(v) >= minn),
                      key=lambda z: (-(z[1]["w"] * 100 + z[1]["s"] * 10 + z[1]["t"]), -z[1]["n"]))
    J = [z for z in rank(gj, 3) if z[1]["w"] + z[1]["s"] + z[1]["t"]][:10] or rank(gj, 2)[:8]
    T = [z for z in rank(gt, 2) if z[1]["w"] + z[1]["s"] + z[1]["t"] >= 2][:8]
    multi_age = len(A) > 1
    parts = []
    if multi_age:
        ba = max(A, key=lambda k: (A[k]["w"], A[k]["r3"]))
        parts.append(f"{rc.name}で最も勝っている年齢は{ba}で、過去{rc.n}回で{A[ba]['w']}勝・3着内率{A[ba]['r3']:.0f}%。")
        zero = [k for k, v in A.items() if v["n"] >= 8 and not v["w"]]
        if zero:
            parts.append("、".join(f"{k}は延べ{A[k]['n']}頭" for k in zero) + "が出走して勝ち馬がいない。")
    if len(S) > 1:
        f_ = S["牝馬"]
        parts.append(f"牝馬は延べ{f_['n']}頭で{f_['w']}勝・3着内率{f_['r3']:.0f}%。")
    if J:
        j0 = J[0]
        parts.append(f"騎手では{j0[0]}騎手が{j0[1]['n']}回騎乗して{j0[1]['w']}勝、3着以内{j0[1]['w'] + j0[1]['s'] + j0[1]['t']}回。")
    lead = "".join(parts) or f"{rc.name}の過去{rc.n}回の騎手別・厩舎別の成績をまとめた。"
    what = "年齢・性別・騎手・厩舎" if multi_age else "性別・騎手・厩舎"
    j0t = f"{J[0][0]}騎手は{J[0][1]['n']}回で{J[0][1]['w']}勝" if J else "騎手別の成績"
    title = f"{rc.name}の{what}の傾向：{(max(A, key=lambda k: (A[k]['w'], A[k]['r3'])) + 'が' + str(max(v['w'] for v in A.values())) + '勝、') if multi_age else ''}{j0t}（過去10年）"
    desc = (f"{rc.name}（{rc.grade()}）{rc.span}の{what}別の成績をJRA公式の成績から集計した。"
            + ("年齢別は" + "、".join(f"{k}{fmt(v)}" for k, v in A.items()) + "。" if multi_age else "")
            + (f"{j0t}。" if J else ""))
    body = ""
    if multi_age:
        body += "\n## 年齢別の成績（" + rc.span + "）\n\n成績は「1着-2着-3着-4着以下」の回数。\n\n| 年齢 " + THEAD + "\n".join(row(k, v) for k, v in A.items()) + "\n\n"
        ws = defaultdict(list)
        for y in rc.ys:
            for x in rc.top(y, 1):
                ws[f"{x['age']}歳" if x["age"] <= 6 else "7歳以上"].append(f"{x['name']}（{y}年）")
        body += "勝ち馬は、" + "。".join(f"{k}が" + "、".join(v) for k, v in sorted(ws.items())) + "。"
        best3 = max(A, key=lambda k: (A[k]["r3"] if A[k]["n"] >= 8 else -1))
        if A[best3]["n"] >= 8:
            body += f"3着以内に入る割合が最も高いのは{best3}（{A[best3]['r3']:.0f}%、延べ{A[best3]['n']}頭）。"
    else:
        only = next(iter(A), "")
        body += f"\n## 出走馬の年齢\n\n{rc.name}は{only}の馬だけが出走するレースなので、年齢による差はない。\n"
    if len(S) > 1:
        fw = [f"{x['name']}（{y}年）" for y in rc.ys for x in rc.top(y, 1) if x["sex"] == "牝"]
        body += ("\n\n## 性別の成績\n\n| 性別 " + THEAD + "\n".join(row(k, v) for k, v in S.items()) + "\n\n"
                 + (("牝馬の勝ち馬は、" + "、".join(fw) + "。") if fw else f"牝馬は延べ{S['牝馬']['n']}頭が出走して、勝ち馬がいない。"))
    if J:
        jt = "| 騎手 | 成績 | 騎乗数 | 3着以内に入った馬 |\n|---|---|---|---|\n"
        for j, v, rs in J:
            tp = "、".join(f"{x['year']}年{x['name']}{fin(x)}着" for x in sorted(rs, key=lambda x: -x["year"]) if fin(x) <= 3) or "―"
            jt += f"| {j} | {fmt(v)} | {v['n']} | {tp} |\n"
        zero = [z for z in rank(gj, 5) if not (z[1]["w"] + z[1]["s"] + z[1]["t"])][:3]
        body += ("\n\n## 騎手別の成績（成績の良い順）\n\n" + jt + "\n" + f"最も成績が良いのは{J[0][0]}騎手（{fmt(J[0][1])}）。"
                 + ("一方、" + "、".join(f"{z[0]}騎手（{z[1]['n']}回騎乗）" for z in zero) + "は3着以内がない。" if zero else ""))
    if T:
        tt = "| 厩舎（調教師） | 成績 | 出走数 | 3着以内に入った馬 |\n|---|---|---|---|\n"
        for t, v, rs in T:
            tp = "、".join(f"{x['year']}年{x['name']}{fin(x)}着" for x in sorted(rs, key=lambda x: -x["year"]) if fin(x) <= 3)
            tt += f"| {t} | {fmt(v)} | {v['n']} | {tp} |\n"
        body += "\n\n## 厩舎別の成績（3着以内が2回以上）\n\n" + tt
    body += (f"\n\n## {rc.year}年に向けて\n\n" + this_year(rc) + "出走馬が決まったら、上の表と見比べてほしい。このサイトのAI予想は、レースの前日夜または当日昼に全頭の評価と印を公開する。\n\n"
             + links(rc, "nenrei-kishu") + "\n\n" + CAUTION + "\n\n## 出典\n\n" + rc.src() + "\n")
    return front(rc, "nenrei-kishu", 3, title, desc, lead) + body


# ---------- 記事4：ジンクス・データの偏り ----------
MANUAL_LINKS = {
    "queen-elizabeth-cup": [("eliza-kako10nen", "過去10年の結果一覧"), ("eliza-ninki-waku", "人気・枠順の傾向"), ("eliza-nenrei-kishu", "年齢・騎手の傾向")],
    "mile-championship": [("mile-kako10nen", "過去10年の結果一覧"), ("mile-ninki-waku", "人気・枠順の傾向"), ("mile-nenrei-kishu", "年齢・騎手の傾向")],
    "japan-cup": [("jc-kako10nen", "過去10年の結果一覧"), ("jc-ninki-haitou", "人気と配当の傾向"), ("jc-waku", "枠順の傾向"), ("jc-nenrei-seibetsu", "年齢・性別の傾向")],
    "champions-cup": [("champions-cup-kako10nen", "過去10年の結果一覧"), ("champions-cup-ninki-waku", "人気・枠順の傾向"), ("champions-cup-nenrei-kishu", "年齢・騎手の傾向")],
    "arima-kinen": [("arima-kinen-kako10nen", "過去10年の結果一覧"), ("arima-kinen-ninki-waku", "人気・枠順の傾向"), ("arima-kinen-nenrei-kishu", "年齢・騎手の傾向")],
}


def hits(v: list[dict], k: int = 3, lim: int = 6) -> str:
    """3着以内（k=1なら勝ち馬）に入った馬を新しい年から並べる。"""
    h = sorted((x for x in v if fin(x) <= k), key=lambda x: -x["year"])
    t = "、".join(f"{x['year']}年{x['name']}" + ("" if k == 1 else f"{fin(x)}着") for x in h[:lim])
    return t + ("ほか" if len(h) > lim else "")


def fuku_roi(rc: Race, v: list[dict]) -> float | None:
    """v の馬の複勝を毎回100円ずつ買ったときの回収率（%）。"""
    if not v:
        return None
    back = 0
    for x in v:
        for c, y, *_ in (rc.past[x["year"]].get("pay") or {}).get("複勝") or []:
            if str(c) == str(x["num"]):
                back += y
    return back / len(v)


def tan_roi(rc: Race, v: list[dict]) -> float | None:
    if not v:
        return None
    back = 0
    for x in v:
        for c, y, *_ in (rc.past[x["year"]].get("pay") or {}).get("単勝") or []:
            if str(c) == str(x["num"]):
                back += y
    return back / len(v)


def streak(flags: list[bool]) -> int:
    n = 0
    for f in flags:
        if not f:
            break
        n += 1
    return n


def jinx_items(rc: Race) -> list[tuple]:
    """(点数, 種類, 見出し, 本文, 題に使う短い言い方) の一覧。点数が高いほど偏りが大きい。"""
    R, n, ys = rc.R, rc.n, rc.ys
    out = []
    wins = [x for x in R if fin(x) == 1]

    def add(score, cat, head, body, short=None):
        out.append((score, cat, head, body, short or head))

    # 人気：軸にしやすい人気
    best = None
    for p in range(1, 7):
        v = [x for x in R if x["pop"] == p]
        if len(v) < n - 1:
            continue
        r = rec(v)
        t3 = r["w"] + r["s"] + r["t"]
        if best is None or (t3, r["w"]) > (best[1], best[2]["w"]):
            best = (p, t3, r, v)
    if best and best[1] >= 0.4 * n:
        p, t3, r, v = best
        fr, tr = fuku_roi(rc, v), tan_roi(rc, v)
        add(10 * t3 / n + (2 if p != 1 else 0) - (4 if t3 < 0.6 * n else 0), "pop", f"{p}番人気が{n}回中{t3}回、3着以内に入っている",
            f"{p}番人気の成績は{fmt(r)}（1着-2着-3着-4着以下）。3着以内に入った馬は{hits(v)}。"
            + (f"{p}番人気の複勝を毎回100円買っていた場合、回収率は{fr:.0f}%、単勝なら{tr:.0f}%だった。" if fr is not None and tr is not None else "")
            + ("人気の中心ではない馬が最も安定しているレースといえる。" if p >= 3 else ""),
            f"{p}番人気が3着以内{t3}回")
    for p in range(2, 10):
        v = [x for x in R if x["pop"] == p]
        r = rec(v)
        if r["w"] >= 3 and (not best or p != best[0] or True):
            tr = tan_roi(rc, v)
            add(6 + 2 * r["w"] + (1 if p >= 4 else 0), f"popwin", f"{p}番人気が{r['w']}勝している",
                f"勝ったのは{hits(v, 1)}。{p}番人気の単勝を毎回100円買っていた場合の回収率は{tr:.0f}%。同じ期間の1番人気は{rec([x for x in R if x['pop'] == 1])['w']}勝だった。",
                f"{p}番人気が{r['w']}勝")
            break
    # 勝ち馬の人気の上限、上位人気の安定
    mx = max((x["pop"] for x in wins if x["pop"]), default=99)
    if mx <= 7 and len(wins) >= 8:
        add(13 - mx - (3 if mx > 5 else 0), "winpop", f"勝ち馬{len(wins)}頭はすべて{mx}番人気以内", f"勝ち馬の人気は新しい年から" + "、".join(f"{x['pop']}番人気" for x in sorted(wins, key=lambda x: -x["year"])) + f"。{mx + 1}番人気以下は延べ{sum(1 for x in R if x['pop'] and x['pop'] > mx)}頭が出走して勝っていない。", f"勝ち馬はすべて{mx}番人気以内")
    top3n = {y: sum(1 for x in R if x["year"] == y and fin(x) <= 3 and x["pop"] and x["pop"] <= 3) for y in ys}
    if n >= 8 and min(top3n.values()) >= 2:
        add(9, "top3", "毎年、1〜3番人気のうち2頭以上が3着以内に入っている", f"3着以内に入った1〜3番人気の頭数は、新しい年から" + "、".join(f"{top3n[y]}頭" for y in ys) + "。上位人気が大きく崩れた年がない。", "1〜3番人気が毎年2頭以上3着以内")
    elif n >= 8 and sum(1 for v in top3n.values() if v == 0) >= 2:
        z = [y for y in ys if top3n[y] == 0]
        add(7 + len(z), "top3", f"1〜3番人気が1頭も3着以内に入らなかった年が{len(z)}回ある", f"{'・'.join(str(y) for y in sorted(z))}年は、1〜3番人気がそろって4着以下だった。", f"1〜3番人気の全滅が{len(z)}回")
    tans = [(y, pay1(rc.past[y], "単勝")) for y in ys if pay1(rc.past[y], "単勝")]
    if len(tans) >= 8 and max(v for _, v in tans) < 1000:
        add(7, "tan", "勝ち馬の単勝が1,000円を超えたことがない", f"単勝の最高は{max(tans, key=lambda t: t[1])[0]}年の{max(v for _, v in tans):,}円。" + f"500円未満が{sum(1 for _, v in tans if v < 500)}回あった。", "単勝1,000円超えなし")
    elif len(tans) >= 8 and sum(1 for _, v in tans if v >= 1000) >= 0.5 * len(tans):
        k = [y for y, v in tans if v >= 1000]
        add(6 + len(k), "tan", f"勝ち馬の単勝が{len(tans)}回中{len(k)}回、1,000円を超えている", f"1,000円を超えたのは{'・'.join(str(y) for y in sorted(k))}年。最高は{max(v for _, v in tans):,}円。", f"単勝1,000円超えが{len(k)}回")
    # 1番人気の連続
    f1 = {y: next((x for x in R if x["year"] == y and x["pop"] == 1), None) for y in ys}
    if all(f1.values()):
        lose = streak([fin(f1[y]) != 1 for y in ys])
        out3 = streak([fin(f1[y]) > 3 for y in ys])
        in3 = streak([fin(f1[y]) <= 3 for y in ys])
        w1 = sum(fin(f1[y]) == 1 for y in ys)
        if w1 == 0:
            add(15, "fav", f"1番人気が{n}回続けて勝っていない", f"過去{n}回、1番人気は1度も勝っていない。着順は新しい年から" + "、".join(f"{fin(f1[y])}着" if fin(f1[y]) < 99 else "着外" for y in ys) + "。", "1番人気は0勝")
        elif lose >= 4:
            last = next(y for y in ys if fin(f1[y]) == 1)
            add(7 + lose, "fav", f"1番人気が{lose}年続けて負けている", f"1番人気が最後に勝ったのは{last}年の{f1[last]['name']}。その後の{lose}回は" + "、".join(f"{y}年{f1[y]['name']}（{fin(f1[y])}着）" for y in ys[:lose]) + "。", f"1番人気は{lose}連敗中")
        elif in3 >= 6:
            add(6 + in3, "fav", f"1番人気が{in3}年続けて3着以内", f"{ys[in3 - 1]}年から{ys[0]}年まで、1番人気は毎年3着以内に入っている（期間中{sum(fin(f1[y]) == 1 for y in ys[:in3])}勝）。", f"1番人気は{in3}年連続で3着以内")
        if out3 >= 3:
            add(8 + out3, "fav2", f"1番人気が{out3}年続けて4着以下", "、".join(f"{y}年{f1[y]['name']}（{fin(f1[y])}着）" for y in ys[:out3]) + "。")
    # 10番人気以下
    big = [x for x in R if x["pop"] and x["pop"] >= 10]
    if len(big) >= 20:
        b3 = [x for x in big if fin(x) <= 3]
        yrs = len({x["year"] for x in b3})
        if not b3:
            add(11, "big", "10番人気以下は1頭も3着以内に入っていない", f"10番人気以下は延べ{len(big)}頭が出走して、3着以内がない。人気薄には厳しいレースになっている。", "10番人気以下は3着以内なし")
        elif yrs >= 0.5 * n:
            add(7 + 10 * yrs / n, "big", f"10番人気以下が{n}回中{yrs}回、3着以内に入っている", f"入ったのは{hits(big)}。延べ{len(big)}頭で3着以内{len(b3)}回。", f"10番人気以下が{yrs}回3着以内")
    # 1・2番人気の決着
    q = 0
    for y in ys:
        top2 = [x for x in R if x["year"] == y and fin(x) <= 2]
        if len(top2) == 2 and {x["pop"] for x in top2} == {1, 2}:
            q += 1
    if q == 0 and n >= 8:
        add(8, "q12", "1番人気と2番人気で1・2着を占めた年がない", f"過去{n}回、1番人気と2番人気がそろって2着以内に入ったことは1度もない。", "1・2番人気での決着なし")
    elif q >= 3:
        add(6 + q, "q12", f"1番人気と2番人気で1・2着を占めた年が{q}回ある", f"{n}回のうち{q}回は、1番人気と2番人気の2頭で1・2着が決まった。", f"1・2番人気での決着が{q}回")
    # 枠・馬番・4角：今年と同じコースの年だけで数える
    yw = rc.same if len(rc.same) >= 6 else (ys if len(rc.same) == 0 and False else [])
    if len(rc.same) == n:
        yw = ys
    W = [x for x in R if x["year"] in yw]
    wn = len(yw)
    note = "" if wn == n else f"（今年と同じ{course_of(rc.now)}で行われた{wn}回の集計）"
    if wn >= 6:
        for f in range(1, 9):
            v = [x for x in W if x["frame"] == f]
            r = rec(v)
            t3 = r["w"] + r["s"] + r["t"]
            if len(v) >= 10 and t3 == 0:
                add(9 + len(v) / 10, "frame0", f"{f}枠は延べ{len(v)}頭が出走して3着以内がない", f"{f}枠の成績は{fmt(r)}{note}。最も良い着順は{min(fin(x) for x in v)}着。", f"{f}枠は3着以内なし")
            elif len(v) >= 10 and r["w"] == 0 and len(v) >= 2 * wn - 2 and f in (1, 8):
                add(6, "frame0", f"{f}枠は延べ{len(v)}頭が出走して勝ち馬がいない", f"{f}枠の成績は{fmt(r)}{note}。")
            if r["w"] >= 3:
                add(6 + 2 * r["w"], "frame", f"{f}枠が{r['w']}勝している", f"{f}枠の成績は{fmt(r)}{note}。勝ったのは{hits(v, 1)}。", f"{f}枠が{r['w']}勝")
        outer = [x for x in W if x["frame"] in (7, 8)]
        ro = rec(outer)
        if len(outer) >= 20 and ro["w"] == 0:
            add(7 + len(outer) / 20, "outer", f"7・8枠は延べ{len(outer)}頭が出走して勝ち馬がいない", f"7・8枠の成績は{fmt(ro)}{note}。" + (f"3着以内は{hits(outer)}。" if ro["s"] + ro["t"] else "3着以内もない。"), "7・8枠は0勝")
        wsame = [x for x in W if fin(x) == 1]
        if len(wsame) >= 8 and all(x["num"] <= 9 for x in wsame) and sum(1 for x in W if x["num"] >= 10) >= 20:
            v10 = [x for x in W if x["num"] >= 10]
            add(8, "digit", f"勝ち馬{len(wsame)}頭はすべて馬番1〜9番", f"馬番10番より外の馬は延べ{len(v10)}頭が出走して、成績は{fmt(rec(v10))}{note}。", "勝ち馬はすべて馬番1けた")
        nums = defaultdict(list)
        for x in W:
            nums[x["num"]].append(x)
        bn = max(nums.items(), key=lambda kv: (rec(kv[1])["w"], rec(kv[1])["r3"]), default=None)
        if bn and rec(bn[1])["w"] >= 3:
            r = rec(bn[1])
            add(7 + 2 * r["w"], "num", f"馬番{bn[0]}番が{r['w']}勝している", f"馬番{bn[0]}番の成績は{fmt(r)}{note}。勝ったのは{hits(bn[1], 1)}。", f"馬番{bn[0]}番が{r['w']}勝")
        else:
            bn = max(nums.items(), key=lambda kv: (rec(kv[1])["w"] + rec(kv[1])["s"] + rec(kv[1])["t"], rec(kv[1])["w"]), default=None)
            if bn:
                r = rec(bn[1])
                t3 = r["w"] + r["s"] + r["t"]
                if t3 >= 5:
                    add(5 + t3, "num", f"馬番{bn[0]}番が{wn}回中{t3}回、3着以内に入っている", f"馬番{bn[0]}番の成績は{fmt(r)}{note}。入ったのは{hits(bn[1])}。", f"馬番{bn[0]}番が3着以内{t3}回")
        ww = [x for x in W if fin(x) == 1]
        ev = sum(1 for x in ww if x["num"] % 2 == 0)
        if ww and max(ev, len(ww) - ev) >= 0.8 * len(ww) and len(ww) >= 8:
            k = "偶数" if ev > len(ww) - ev else "奇数"
            add(7 + max(ev, len(ww) - ev) - 0.8 * len(ww), "parity", f"勝ち馬{len(ww)}頭のうち{max(ev, len(ww) - ev)}頭が{k}の馬番", f"勝ち馬の馬番は新しい年から" + "、".join(f"{x['num']}番" for x in sorted(ww, key=lambda x: -x["year"])) + f"{note}。偶数の馬番は後からゲートに入るぶん有利とも言われるが、ここまで偏る理由としては弱い。")
        zoro = [y for y in yw if len({x["frame"] for x in W if x["year"] == y and fin(x) <= 2}) == 1 and sum(1 for x in W if x["year"] == y and fin(x) <= 2) == 2]
        if len(zoro) >= 2:
            add(5 + 2 * len(zoro), "zoro", f"同じ枠の2頭で1・2着が決まった年が{len(zoro)}回ある", f"{'・'.join(str(y) for y in sorted(zoro))}年は、1着と2着が同じ枠の馬だった（枠連のゾロ目）{note}。")
        P = [x for x in W if pos4(x)]
        pw = [x for x in P if fin(x) == 1]
        if len(pw) >= 6:
            for lim in (3, 5):
                k = sum(1 for x in pw if pos4(x) <= lim)
                if k >= 0.8 * len(pw):
                    add(6 + 10 * k / len(pw) - lim, "pos", f"勝ち馬{len(pw)}頭のうち{k}頭が、4コーナーを{lim}番手以内で回っていた",
                        f"4コーナーの位置は新しい年から" + "、".join(f"{pos4(x)}番手" for x in sorted(pw, key=lambda x: -x["year"])) + f"{note}。後ろから差し切った勝ち馬は少ない。", f"勝ち馬の{k}頭が4角{lim}番手以内")
                    break
            else:
                k = sum(1 for x in pw if pos4(x) >= 8)
                if k >= 0.5 * len(pw):
                    add(6 + 10 * k / len(pw), "pos", f"勝ち馬{len(pw)}頭のうち{k}頭が、4コーナーを8番手より後ろで回っていた",
                        f"4コーナーの位置は新しい年から" + "、".join(f"{pos4(x)}番手" for x in sorted(pw, key=lambda x: -x["year"])) + f"{note}。差し・追い込みが決まりやすい。", f"勝ち馬の{k}頭が4角8番手以下")
            lead = [x for x in P if pos4(x) == 1]
            r = rec(lead)
            if len(lead) >= 6 and r["w"] + r["s"] + r["t"] == 0:
                add(8, "lead", f"4コーナーを先頭で回った馬は{len(lead)}頭とも4着以下", f"逃げた馬（4コーナー先頭）の成績は{fmt(r)}{note}。")
            elif r["w"] >= 3:
                add(6 + 2 * r["w"], "lead", f"4コーナーを先頭で回った馬が{r['w']}勝している", f"4コーナー先頭の馬の成績は{fmt(r)}{note}。勝ったのは{hits(lead, 1)}。", f"逃げ馬が{r['w']}勝")
    # 年齢・性別
    ages = sorted({x["age"] for x in R if x["age"]})
    if len(ages) > 1:
        for a in ages:
            v = [x for x in R if x["age"] == a]
            r = rec(v)
            if r["w"] >= 0.6 * len(wins) and r["w"] >= 5:
                add(5 + r["w"], "age", f"{a}歳が{r['w']}勝している", f"{a}歳の成績は{fmt(r)}（延べ{len(v)}頭）。勝ったのは{hits(v, 1)}。", f"{a}歳が{r['w']}勝")
            if len(v) >= 15 and r["w"] == 0 and a <= 6:
                add(6 + len(v) / 10, "age0", f"{a}歳は延べ{len(v)}頭が出走して勝ち馬がいない", f"{a}歳の成績は{fmt(r)}。" + (f"3着以内は{hits(v)}。" if r["s"] + r["t"] else "3着以内もない。"), f"{a}歳は0勝")
        old = [x for x in R if x["age"] and x["age"] >= 7]
        r = rec(old)
        if len(old) >= 15 and r["w"] + r["s"] + r["t"] == 0:
            add(8 + len(old) / 10, "old", f"7歳以上は延べ{len(old)}頭が出走して3着以内がない", f"7歳以上の成績は{fmt(r)}。最も良い着順は{min(fin(x) for x in old)}着。", "7歳以上は3着以内なし")
        elif len(old) >= 15 and r["w"] == 0:
            add(5 + len(old) / 15, "old", f"7歳以上は延べ{len(old)}頭が出走して勝ち馬がいない", f"7歳以上の成績は{fmt(r)}。3着以内は{hits(old)}。", "7歳以上は0勝")
    fem = [x for x in R if x["sex"] == "牝"]
    if 8 <= len(fem) < 0.9 * len(R):
        r = rec(fem)
        if r["w"] + r["s"] + r["t"] == 0:
            add(8 + len(fem) / 10, "fem", f"牝馬は延べ{len(fem)}頭が出走して3着以内がない", f"牝馬の成績は{fmt(r)}。最も良い着順は{min(fin(x) for x in fem)}着。", "牝馬は3着以内なし")
        elif r["w"] >= 4 and r["wr"] > 1.5 * rec([x for x in R if x["sex"] != "牝"])["wr"]:
            add(6 + r["w"], "fem", f"牝馬が{r['w']}勝している", f"牝馬の成績は{fmt(r)}（延べ{len(fem)}頭）。勝ったのは{hits(fem, 1)}。", f"牝馬が{r['w']}勝")
    # 騎手・厩舎
    jk = defaultdict(list)
    for x in R:
        jk[x["jockey"]].append(x)
    j, v = max(jk.items(), key=lambda kv: (rec(kv[1])["w"], rec(kv[1])["r3"]))
    r = rec(v)
    if r["w"] >= 3:
        add(6 + 2 * r["w"], "jockey", f"{j}騎手が{r['w']}勝している", f"{j}騎手の成績は{fmt(r)}（{len(v)}回騎乗）。勝ったのは{hits(v, 1)}。", f"{j}騎手が{r['w']}勝")
    else:
        j, v = max(jk.items(), key=lambda kv: (rec(kv[1])["w"] + rec(kv[1])["s"] + rec(kv[1])["t"], rec(kv[1])["r3"]))
        r = rec(v)
        t3 = r["w"] + r["s"] + r["t"]
        if t3 >= 3 and r["r3"] >= 50:
            add(4 + t3, "jockey", f"{j}騎手が{len(v)}回騎乗して{t3}回、3着以内に入っている", f"{j}騎手の成績は{fmt(r)}。入ったのは{hits(v)}。", f"{j}騎手は{len(v)}回で3着以内{t3}回")
    cold = [(j, v) for j, v in jk.items() if len(v) >= 6 and rec(v)["w"] + rec(v)["s"] + rec(v)["t"] == 0]
    if cold:
        j, v = max(cold, key=lambda kv: len(kv[1]))
        add(4 + len(v) / 2, "cold", f"{j}騎手は{len(v)}回騎乗して3着以内がない", f"{j}騎手の成績は{fmt(rec(v))}。最も良い着順は{min(fin(x) for x in v)}着で、そのうち3番人気以内だったのは{sum(1 for x in v if x['pop'] and x['pop'] <= 3)}回。")
    tr = defaultdict(list)
    for x in R:
        tr[x["trainer"]].append(x)
    t, v = max(tr.items(), key=lambda kv: (rec(kv[1])["w"], rec(kv[1])["r3"]))
    r = rec(v)
    if r["w"] >= 3:
        add(5 + 2 * r["w"], "trainer", f"{t}厩舎が{r['w']}勝している", f"{t}厩舎の成績は{fmt(r)}（延べ{len(v)}頭）。勝ったのは{hits(v, 1)}。", f"{t}厩舎が{r['w']}勝")
    # リピーター：前の年に3着以内だった馬が、次の年も出たとき
    rep = []
    for y in ys:
        if y - 1 in rc.past:
            prev = {x["name"] for x in R if x["year"] == y - 1 and fin(x) <= 3}
            rep += [x for x in R if x["year"] == y and x["name"] in prev]
    if len(rep) >= 4:
        r = rec(rep)
        t3 = r["w"] + r["s"] + r["t"]
        if r["r3"] >= 50:
            add(5 + t3, "rep", f"前の年に3着以内だった馬は、次の年も{len(rep)}頭中{t3}頭が3着以内", f"前年の1〜3着馬が翌年も出走したときの成績は{fmt(r)}。入ったのは{hits(rep)}。同じ馬が続けて走るレースといえる。", f"前年の好走馬は{len(rep)}頭中{t3}頭が3着以内")
        elif t3 == 0:
            add(8, "rep", f"前の年に3着以内だった馬は、次の年は{len(rep)}頭とも4着以下", f"前年の1〜3着馬が翌年も出走したときの成績は{fmt(r)}。" + "、".join(f"{x['year']}年{x['name']}（{fin(x)}着）" for x in rep[:6]) + "。", "前年の好走馬は翌年3着以内なし")
    # 配当
    t3p = [(y, pay1(rc.past[y], "3連単")) for y in ys if pay1(rc.past[y], "3連単")]
    if len(t3p) >= 8:
        over = [y for y, v in t3p if v >= 100000]
        under = [y for y, v in t3p if v < 10000]
        if len(over) >= 0.5 * len(t3p):
            add(6 + 10 * len(over) / len(t3p), "pay", f"3連単が{len(t3p)}回中{len(over)}回、10万円を超えている", f"10万円を超えたのは{'・'.join(str(y) for y in sorted(over))}年。最高は{man(max(v for _, v in t3p))}。", f"3連単10万円超えが{len(over)}回")
        elif not over:
            add(8, "pay", f"3連単が1度も10万円を超えていない", f"過去{len(t3p)}回の3連単の最高は{man(max(v for _, v in t3p))}。大きく荒れたことがないレースである。", "3連単は10万円超えなし")
        if len(under) >= 0.4 * len(t3p):
            add(5 + 10 * len(under) / len(t3p), "pay2", f"3連単が{len(t3p)}回中{len(under)}回、1万円未満", f"1万円未満だったのは{'・'.join(str(y) for y in sorted(under))}年。", f"3連単1万円未満が{len(under)}回")
    # 馬名（理由のない偏り）
    if len(wins) >= 8:
        ln = Counter(len(x["name"]) for x in wins)
        L, c = ln.most_common(1)[0]
        allL = [x for x in R if len(x["name"]) == L]
        if c >= 4 and c / len(wins) >= 1.6 * len(allL) / len(R):
            add(3 + c, "name", f"勝ち馬{len(wins)}頭のうち{c}頭が、馬名{L}文字", f"{L}文字の馬は延べ{len(allL)}頭（出走馬全体の{100 * len(allL) / len(R):.0f}%）で、成績は{fmt(rec(allL))}。勝ったのは{hits(allL, 1)}。馬名の長さが結果に影響する理由は見当たらないが、数字としては偏っている。", f"勝ち馬の{c}頭が馬名{L}文字")
        ini = Counter(x["name"][0] for x in wins)
        ch, c = ini.most_common(1)[0]
        if c >= 3:
            allC = [x for x in R if x["name"][0] == ch]
            add(2 + 2 * c, "ini", f"馬名が「{ch}」で始まる馬が{c}勝している", f"「{ch}」で始まる馬は延べ{len(allC)}頭で、成績は{fmt(rec(allC))}。勝ったのは{hits(allC, 1)}。" + ("同じ馬主の冠名による偏りで、馬名そのものに意味があるわけではない。" if len({x['name'][:3] for x in allC if fin(x) == 1}) < c else "理由は見当たらないが、数字としては偏っている。"), f"「{ch}」で始まる馬が{c}勝")
    return out


HOOKS = {
    "pop": "今年もこの人気の馬が馬券の軸になるのか。当日のオッズで何番人気になるかに注目したい。",
    "popwin": "今年この人気に支持される馬は、発走直前まで確認しておきたい。",
    "winpop": "今年も上位人気から勝ち馬が出るのか、それとも初めての伏兵が現れるのか。",
    "top3": "今年の上位人気3頭は、どこまで信頼できるか。",
    "tan": "今年の勝ち馬の単勝はいくらになるか。",
    "fav": "今年の1番人気は、この流れを変えられるか。",
    "fav2": "今年の1番人気にとっては、嫌なデータである。",
    "big": "今年も人気薄の出番はあるのか。",
    "q12": "今年の1番人気と2番人気の組み合わせは、買うか切るかの分かれ目になる。",
    "frame0": "今年この枠に入った馬は、データを覆せるか。枠順の発表に注目したい。",
    "frame": "今年この枠を引くのはどの馬か。枠順が出たら最初に確認したい。",
    "outer": "今年、外枠に入った有力馬は割り引くべきか。枠順の発表が1つの山場になる。",
    "digit": "今年、2けたの馬番に入った有力馬は試される。",
    "num": "今年この馬番に入る馬は、それだけで気になる存在になる。",
    "parity": "今年の勝ち馬の馬番はどちらになるか。",
    "zoro": "今年も枠連のゾロ目はあるのか。",
    "pos": "今年も同じ位置から勝ち馬が出るのか。前走までの通過順を見ておきたい。",
    "lead": "今年、先手を取るのはどの馬か。",
    "age": "今年もこの世代から勝ち馬が出るのか。",
    "age0": "今年この年齢で出走する馬は、初めての勝ち馬になれるか。",
    "old": "今年のベテラン勢は、この壁を越えられるか。",
    "fem": "今年出走する牝馬は、このデータにどう向き合うか。",
    "jockey": "今年の騎乗馬が決まったら、まず確認したい騎手である。",
    "cold": "今年こそ、このデータを止められるか。",
    "trainer": "今年の出走馬に、この厩舎の馬がいるかを確認したい。",
    "rep": "去年の上位馬が今年も出てくるなら、見逃せないデータである。",
    "pay": "今年の配当はどちらに転ぶか。",
    "pay2": "今年も堅く収まるのか。",
    "name": "今年の出走馬で、この文字数に当てはまる馬を数えてみるのも面白い。",
    "ini": "今年の出走馬に、当てはまる馬はいるか。",
}


def chance3(n: int, p: float = 0.1) -> float:
    """勝率pの条件が、n回のうち3回以上当たる確率（%）。"""
    from math import comb
    return 100 * (1 - sum(comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(3)))


def jinx(rc: Race) -> str | None:
    items = sorted(jinx_items(rc), key=lambda z: -z[0])
    seen, pick, bodies = set(), [], set()
    for it in items:
        m = re.search(r"勝ったのは([^。]+)。", it[3])
        key = m.group(1) if m and it[1] in ("frame", "num", "lead", "ini", "name") else None
        if it[1] in seen or (key and key in bodies):  # 同じ馬たちを言い換えただけの項目は1つにする
            continue
        seen.add(it[1])
        if key:
            bodies.add(key)
        pick.append(it)
    pick = pick[:9]
    if len(pick) < 3:
        return None
    heads = [it[4] for it in pick[:2]]
    title = f"【{rc.year}】{rc.name}のジンクス{len(pick)}選｜{heads[0]}、{heads[1]}…今年も続くか"
    desc = (f"{rc.name}（{rc.grade()}）の過去{rc.n}回（{rc.span}）に隠れたジンクスを{len(pick)}個。" + "、".join(it[4] for it in pick[:4])
            + f"など、JRA公式の全着順から数えた。{rc.year}年も続くのか、出走馬と見比べたい。")
    lead = (f"{rc.name}には、知っているかどうかで馬券の組み立てが変わりそうな偏りがある。過去{rc.n}回（{rc.span}）で{pick[0][2]}。さらに、{pick[1][2]}。"
            f"ほかにも{len(pick) - 2}個、気になるデータが見つかった。{rc.year}年はどこまで当てはまるのか。")
    body = (f"\n## {rc.name}のジンクス{len(pick)}選（{rc.span}）\n\n" + "\n".join(f"{i}. {it[2]}" for i, it in enumerate(pick, 1))
            + f"\n\n{rc.venue_note()}すべてJRA公式の成績から数えた実際の数字で、偏りの大きい順に並べている。\n")
    for i, it in enumerate(pick, 1):
        body += f"\n## {i}. {it[2]}\n\n{it[3]}{HOOKS.get(it[1], '')}\n"
    body += (f"\n## このジンクス、{rc.year}年も続くか\n\n"
             f"出走馬と枠順が決まったら、上の{len(pick)}個に当てはまる馬を探してみてほしい。複数のジンクスが重なる馬がいれば、それだけで買う理由にも、疑う理由にもなる。\n\n"
             f"ただし、過去{rc.n}回分の結果なので、偶然が混ざっている可能性は十分にある。勝率10%の条件でも、{rc.n}回のうち3回以上当たることは偶然で{chance3(rc.n):.0f}%ほど起きる。"
             "枠や脚質の偏りはコースの形から説明できることがあるが、馬番や馬名の偏りには理由が見当たらない。続くか、止まるかを見届けるのも競馬の楽しみ方の1つである。\n\n"
             "このサイトのAI予想は、ジンクスではなく、馬ごとの近走・コース実績・騎手・馬場から全頭を評価している。ジンクスに当てはまる馬にAIがどんな印を打つのか、レース当日に見比べてほしい。\n")
    if rc.slug in MANUAL_LINKS:
        lk = "\n".join(f"- [{rc.name}の{t}](/column/{k}/)" for k, t in MANUAL_LINKS[rc.slug] if (COLS / f"{k}.md").exists())
        if (DATA_DIR / "race_guides" / f"{rc.slug}.json").exists():
            lk += f"\n- [{rc.name}のレースガイドとAI予想](/graded/{rc.slug}/)"
    else:
        lk = links(rc, "jinx")
    body += (f"\n## {rc.year}年に向けて\n\n" + this_year(rc) + "\n\n" + lk + "\n\n" + CAUTION + "\n\n## 出典\n\n" + rc.src() + "\n")
    return front(rc, "jinx", 4, title, desc, lead, "col-ninki-shoritsu" if False else None) + body


KINDS = {"kako10nen": kako10, "ninki-waku": ninki, "nenrei-kishu": nenrei, "jinx": jinx}


def front_year(p: Path) -> int | None:
    if not p.exists():
        return None
    m = re.search(r"^year:\s*(\d{4})", p.read_text(encoding="utf-8")[:1500], re.M)
    return int(m.group(1)) if m else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=16)
    ap.add_argument("--slug", action="append", default=[])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    _init_names()
    all_ = load_all()
    now = datetime.now(JST)
    year = now.year
    if year not in all_:
        print("今年の重賞一覧がまだ無い")
        return
    K = keyed(all_)
    lo, hi = now.strftime("%Y%m%d"), (now + timedelta(days=a.days)).strftime("%Y%m%d")
    n = 0
    for slug, ys in sorted(K.items(), key=lambda kv: (kv[1].get(year) or {}).get("date", "9")):
        cur = ys.get(year)
        if not cur:
            continue
        if a.slug:
            if slug not in a.slug:
                continue
        elif not (lo <= cur["date"] <= hi):
            continue
        if slug.startswith("abbr:"):
            print("skip（重賞ページの名前が決まらない）:", cur["abbr"], cur["date"], flush=True)
            continue
        manual = slug in MANUAL.get(year, set()) and not (a.force and a.slug)
        rc = Race(slug, ys, year)
        if rc.n < MIN_RUNS:
            print("skip（過去の成績が足りない）:", slug, rc.n, flush=True)
            continue
        for kind, fn in KINDS.items():
            if manual and kind != "jinx":  # 手書きの特集がある年は、特集に無いジンクス記事だけ作る
                continue
            out = COLS / f"{slug}-{kind}.md"
            fy = front_year(out)
            if fy == 0 and not a.force:
                print("skip（同じ名前の手書き記事がある）:", out.name)
                continue
            if fy == year and not a.force:
                continue
            try:
                md = fn(rc)
                if not md:
                    print("skip（書けるだけの偏りが無い）:", out.name)
                    continue
            except Exception as e:  # noqa: BLE001
                print("error", slug, kind, repr(e), flush=True)
                continue
            if a.dry:
                print("would write", out.name, len(md))
            else:
                out.write_text(md, encoding="utf-8")
                print("wrote", out.name, flush=True)
            n += 1
    print("記事:", n)


if __name__ == "__main__":
    main()
