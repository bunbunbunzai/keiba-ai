"""重賞の「過去10年データ記事」を自動で作る（集計だけで作り、AIは呼ばない）。

元データは graded_hist.py が集めた data/graded_hist/<年>.json（JRA公式の全着順・払戻）。
今日から --days 日以内に行われる JRA の重賞について、レースごとに3本の記事を columns/ に書く：

  <slug>-kako10nen.md     過去10年の結果一覧（勝ち馬・2〜3着・配当・共通点）
  <slug>-ninki-waku.md    人気・枠順・脚質の傾向
  <slug>-nenrei-kishu.md  年齢・性別・騎手・厩舎の傾向

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
    items = [("kako10nen", "過去10年の結果一覧"), ("ninki-waku", "人気・枠順・脚質の傾向"), ("nenrei-kishu", "年齢・性別・騎手・厩舎の傾向")]
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


KINDS = {"kako10nen": kako10, "ninki-waku": ninki, "nenrei-kishu": nenrei}


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
        if slug in MANUAL.get(year, set()) and not (a.force and a.slug):
            print("skip（手書きの特集がある）:", slug)
            continue
        rc = Race(slug, ys, year)
        if rc.n < MIN_RUNS:
            print("skip（過去の成績が足りない）:", slug, rc.n, flush=True)
            continue
        for kind, fn in KINDS.items():
            out = COLS / f"{slug}-{kind}.md"
            fy = front_year(out)
            if fy == 0 and not a.force:
                print("skip（同じ名前の手書き記事がある）:", out.name)
                continue
            if fy == year and not a.force:
                continue
            try:
                md = fn(rc)
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
