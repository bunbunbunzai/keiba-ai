"""用語集の各ページに足す「実際のレースの数字」（build.py から呼ぶ）。

用語の説明（data/glossary）はどのサイトにもある一般的な内容なので、このサイトが集めた記録から、その用語に関係する数字を足す。
元にする記録は3つで、数字はサイトを作るたびに数え直す：

- H：中央競馬の全レースの結果（data/history/jra。JRA公式の結果。2023年11月〜。約1万レース。着順・馬番・4コーナーの位置・人気・払戻）
- G：JRAの重賞の全着順と払戻（data/graded_hist。今年の分と過去10年。騎手・性齢・斤量・着差・上がり・馬場状態つき）
- S：このサイトがAI予想を出したレース（2026年10月26日〜。中央・地方）の印・買い目・結果と、出馬表（馬体重・前走・騎手・父など）

prepare() で1回だけ集計し、section(slug, term) がその用語のページに入れる HTML を返す（合う数字が無い用語は空）。
どの用語にどの数字を出すかは、いちばん下の BLOCKS で決める。
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from statistics import median

_B = None
H: dict = {}
G: dict = {}
S: dict = {}

JRA_V = ("札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉")
LEFT = ("東京", "中京", "新潟")              # 左回りの競馬場（ほかは右回り）
STEEP = ("中山", "阪神", "中京")             # ゴール前に急な上り坂
FLATV = ("京都", "新潟", "小倉")             # 最後の直線が平坦
FLAT_LONG = {("京都", 3000), ("阪神", 3000), ("京都", 3200), ("阪神", 3200), ("東京", 3400), ("中山", 3600)}  # 2750m以上で平地のコース（ほかは障害）
KINDS = ("単勝", "複勝", "枠連", "馬連", "ワイド", "馬単", "3連複", "3連単")
POS = ("4コーナー1番手", "2〜4番手", "5〜9番手", "10番手以下")  # 重賞の振り返り記事（scraper/year_cols.py）と同じ分け方
GAPS = ("10日以内（連闘）", "11〜38日（中1〜4週）", "39〜73日（中5〜9週）", "74〜179日", "180日以上（半年以上）")
CLASSIC = (("satsuki-sho", "皐月賞"), ("derby", "日本ダービー"), ("kikka-sho", "菊花賞"),
           ("oka-sho", "桜花賞"), ("oaks", "オークス"), ("shuka-sho", "秋華賞"))


def nf(s) -> str:
    return unicodedata.normalize("NFKC", str(s or ""))


class Rec:
    """着順の記録：出走数、1着、2着、3着。"""
    __slots__ = ("n", "w", "s", "t")

    def __init__(self):
        self.n = self.w = self.s = self.t = 0

    def add(self, fin) -> None:
        self.n += 1
        if fin == 1:
            self.w += 1
        elif fin == 2:
            self.s += 1
        elif fin == 3:
            self.t += 1

    @property
    def top3(self) -> int:
        return self.w + self.s + self.t

    def wr(self) -> float:
        return 100 * self.w / self.n if self.n else 0.0

    def r2(self) -> float:
        return 100 * (self.w + self.s) / self.n if self.n else 0.0

    def r3(self) -> float:
        return 100 * self.top3 / self.n if self.n else 0.0


class Cat:
    """レースをまとめた1区分：レース数、1番人気の着順、3連単の払戻。"""
    __slots__ = ("n", "fav", "t3", "lead")

    def __init__(self):
        self.n, self.fav, self.t3, self.lead = 0, Rec(), [], Rec()

    def med3(self) -> int:
        return int(median(self.t3)) if self.t3 else 0


# ---------- 数字の書き方 ----------
def pc(x: float, d: int = 1) -> str:
    return f"{x:.{d}f}%"


def yen(v) -> str:
    return f"{int(v):,}円"


def man(v) -> str:
    """1万円以上は「5836万7,060円」の形。"""
    v = int(v)
    if v >= 10000:
        a, b = divmod(v, 10000)
        return f"{a:,}万{b:,}円" if b else f"{a:,}万円"
    return f"{v:,}円"


def jd(d: str) -> str:
    return f"{int(d[:4])}年{int(d[4:6])}月{int(d[6:8])}日"


def ym(d: str) -> str:
    return f"{int(d[:4])}年{int(d[4:6])}月"


def table(head: list[str], rows: list[list]) -> str:
    esc = _B.esc
    return ("<div class='scroll'><table class='gd'><thead><tr>" + "".join(f"<th>{esc(h)}</th>" for h in head) + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table></div>")


def frame_of(num: int, n: int) -> int:
    """馬番と頭数から枠番（JRAの決まりどおり）。"""
    if n <= 8:
        return num
    if n <= 16:
        single = 16 - n
        return num if num <= single else single + (num - single + 1) // 2
    if n == 17:
        return (num + 1) // 2 if num <= 14 else 8
    return (num + 1) // 2 if num <= 12 else (7 if num <= 15 else 8)


def pos_cat(p) -> str | None:
    if not p:
        return None
    return POS[0] if p == 1 else POS[1] if p <= 4 else POS[2] if p <= 9 else POS[3]


def dist_band(m: int) -> str:
    return "短距離（1400mまで）" if m <= 1400 else "マイル前後（1500〜1700m）" if m <= 1700 else "中距離（1800〜2400m）" if m <= 2400 else "長距離（2500m以上）"


# ---------- H：中央の全レース ----------
def _load_hist(root) -> None:
    h = dict(n=0, jump=0, first="", last="", pop=defaultdict(Rec), pay={k: [] for k in KINDS}, payall={k: [] for k in ("複勝", "ワイド")},
             top={k: (0, None) for k in KINDS}, tan_fav=[0, 0, 0], fuku_fav=[0, 0, 0], fuku100=0, fuku_n=0, fav_fuku_low=0, fav_fuku_n=0,
             tan_low=0, frame=defaultdict(Rec), pos=defaultdict(Rec), surf=defaultdict(Cat), dist=defaultdict(Cat), field=defaultdict(Cat),
             turn=defaultdict(Cat), slope=defaultdict(Cat), sims={}, dead=0, stop=Counter(), runners=0, winpop=Counter(), toku=0,
             top3fav=0, winodds=Counter(), venues=Counter())
    sims = {k: [0, 0, 0] for k in ("box3", "wide3", "nagashi", "form", "multi")}  # 購入額、払戻、的中
    for f in sorted((root / "data" / "history" / "jra").glob("*/*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows = r.get("rows") or []
            pay = r.get("pay") or {}
            for vs in pay.values():
                h["toku"] += sum(1 for _, y in vs if y == 70)
            for x in rows:
                if not str(x[0]).isdigit():
                    h["stop"][str(x[0])] += 1
            if r.get("s") == "障" or (r["m"] >= 2750 and (r["v"], r["m"]) not in FLAT_LONG):
                h["jump"] += 1
                continue
            run = sorted(([int(x[0]), x[1], x[3], x[4]] for x in rows if str(x[0]).isdigit()), key=lambda x: x[0])
            if len(run) < 3 or any(x[3] is None for x in run):
                continue
            h["n"] += 1
            h["first"] = min(h["first"] or r["d"], r["d"])
            h["last"] = max(h["last"], r["d"])
            h["venues"][r["v"]] += 1
            n = r.get("n") or len(rows)
            h["runners"] += len(run) + sum(1 for x in rows if x[0] == "中止")
            h["dead"] += sum(1 for x in run if x[0] == 1) > 1
            by_pop = {x[3]: x for x in run}
            for fin, num, p4, pop in run:
                h["pop"][pop].add(fin)
                if isinstance(num, int):
                    h["frame"][frame_of(num, n)].add(fin)
                c = pos_cat(p4)
                if c:
                    h["pos"][c].add(fin)
            w = run[0]
            h["winpop"][w[3]] += 1
            top3 = run[:3]
            pops = [x[3] for x in top3]
            h["top3fav"] += all(p <= 3 for p in pops)
            for k in KINDS:
                v = [(c, y) for c, y in pay.get(k) or [] if y]
                if not v:
                    continue
                h["pay"][k].append(v[0][1])
                if k in h["payall"]:
                    h["payall"][k] += [y for _, y in v]
                for c, y in v:
                    if y > h["top"][k][0]:
                        h["top"][k] = (y, (r["d"], r["v"], r["r"], c))
            tan = pay.get("単勝") or []
            fuku = {str(c): y for c, y in pay.get("複勝") or []}
            h["fuku_n"] += len(fuku)
            h["fuku100"] += sum(1 for y in fuku.values() if y == 100)
            h["tan_low"] += bool(tan) and tan[0][1] <= 110
            if tan:
                o = tan[0][1]
                h["winodds"]["1倍台" if o < 200 else "2.0〜4.9倍" if o < 500 else "5.0〜9.9倍" if o < 1000 else "10.0〜29.9倍" if o < 3000 else "30倍以上"] += 1
            fav = by_pop.get(1)
            if fav:
                h["tan_fav"][0] += 100
                h["tan_fav"][1] += tan[0][1] if tan and fav[0] == 1 else 0
                h["tan_fav"][2] += fav[0] == 1
                fy = fuku.get(str(fav[1]), 0) if fav[0] <= 3 else 0
                h["fuku_fav"][0] += 100
                h["fuku_fav"][1] += fy
                h["fuku_fav"][2] += fy > 0
                if fy:
                    h["fav_fuku_n"] += 1
                    h["fav_fuku_low"] += fy <= 110
            t3 = (pay.get("3連単") or [[None, 0]])[0][1]
            for key, group in ((r.get("s"), "surf"), (dist_band(r["m"]), "dist"),
                               ("10頭以下" if n <= 10 else "11〜14頭" if n <= 14 else "15頭以上", "field"),
                               ("左回り" if r["v"] in LEFT else "右回り", "turn"),
                               ("坂" if r["v"] in STEEP else "平坦" if r["v"] in FLATV else "", "slope")):
                if not key:
                    continue
                c = h[group][key]
                c.n += 1
                if fav:
                    c.fav.add(fav[0])
                if t3:
                    c.t3.append(t3)
                for fin, num, p4, pop in run:
                    if p4 == 1:
                        c.lead.add(fin)
            # --- 人気だけで機械的に買い続けた場合（各点100円） ---
            p3 = (pay.get("3連複") or [[None, 0]])[0][1]
            uren = (pay.get("馬連") or [[None, 0]])[0][1]
            if p3 and len(run) >= 5:   # 3連複 1〜5番人気のボックス（10点）
                s = sims["box3"]; s[0] += 1000
                if all(p <= 5 for p in pops):
                    s[1] += p3; s[2] += 1
            wide = {tuple(sorted(str(c).split("-"), key=int)): y for c, y in pay.get("ワイド") or [] if re.fullmatch(r"\d+-\d+", str(c))}
            if wide and all(k in by_pop for k in (1, 2, 3)):   # ワイド 1〜3番人気のボックス（3点）
                s = sims["wide3"]; s[0] += 300
                got = 0
                nums = [by_pop[k][1] for k in (1, 2, 3)]
                for i in range(3):
                    for j in range(i + 1, 3):
                        got += wide.get(tuple(sorted((str(nums[i]), str(nums[j])), key=int)), 0)
                s[1] += got; s[2] += got > 0
            if uren and len(run) >= 6:   # 馬連 1番人気から2〜6番人気へ流し（5点）
                s = sims["nagashi"]; s[0] += 500
                if 1 in pops[:2] and all(p <= 6 for p in pops[:2]):
                    s[1] += uren; s[2] += 1
            if t3 and len(run) >= 7:   # 3連単フォーメーション 1着：1番人気、2着：2〜4番人気、3着：2〜7番人気（15点）
                s = sims["form"]; s[0] += 1500
                if pops[0] == 1 and 2 <= pops[1] <= 4 and 2 <= pops[2] <= 7:
                    s[1] += t3; s[2] += 1
            if t3 and len(run) >= 5:   # 3連単 1番人気を軸にしたマルチ、相手は2〜5番人気（36点）
                s = sims["multi"]; s[0] += 3600
                if 1 in pops and all(p <= 5 for p in pops):
                    s[1] += t3; s[2] += 1
    h["sims"] = sims
    for k in KINDS:
        h["pay"][k].sort()
    H.clear(); H.update(h)


# ---------- G：JRAの重賞 ----------
def _done(r: dict) -> bool:
    return any(isinstance(x.get("fin"), int) for x in r.get("rows") or [])


def _runners(r: dict) -> list[dict]:
    return [x for x in r.get("rows") or [] if x.get("pop")]


def _fin(x: dict) -> int:
    return x["fin"] if isinstance(x.get("fin"), int) else 99


def _flat(r: dict) -> bool:
    return not str(r.get("grade") or "").startswith("J")


def _pay1(r: dict, kind: str) -> int:
    v = (r.get("pay") or {}).get(kind) or []
    return int(v[0][1]) if v and v[0][1] else 0


_GUIDE: dict = {}


def _guide(slug: str) -> dict:
    if slug not in _GUIDE:
        _GUIDE[slug] = _B.load_json(_B.ROOT / "data" / "race_guides" / f"{slug}.json") or {}
    return _GUIDE[slug]


def _rname(slug: str, r: dict) -> str:
    return _guide(slug).get("name") or re.sub(r"\s+障害.*$", "", r.get("name") or "") or r.get("abbr") or ""


def _wcond(slug: str) -> str:
    """負担重量の決め方（レースガイドの「負担重量」から）。"""
    g = _guide(slug)
    t = next((str(f.get("v") or "") for f in g.get("facts") or [] if "負担重量" in str(f.get("k") or "")), "")
    return next((k for k in ("ハンデ", "別定", "定量", "馬齢") if k in t), "")


def _load_graded(K: dict, today: str) -> None:
    year = int(today[:4])
    cur = [(s, ys[year]) for s, ys in K.items() if year in ys and _done(ys[year])]
    past = [(s, r) for s, ys in K.items() for y, r in ys.items() if year - 10 <= y < year and _done(r) and r.get("pay")]
    g = dict(year=year, n=len(cur), asof=max((r["date"] for _, r in cur), default=""), flat=sum(_flat(r) for _, r in cur),
             grade=defaultdict(Cat), pay={k: [] for k in KINDS}, jockey=defaultdict(Rec), trainer=defaultdict(Rec),
             sexw=Counter(), agerec=defaultdict(Rec), sexrec=defaultdict(Rec), kg=defaultdict(Rec), margin=Counter(), agari=Rec(), agari_n=0,
             pos=defaultdict(Rec), track=defaultdict(Cat), cond=defaultdict(Cat), classic=[], jump=[], stop=Counter(),
             span=(year - 10, year), n10=len(past) + len(cur), g1prior=[0, 0, 0], lowwin=None, winners=0)
    names = {}
    for slug, r in cur:
        run = _runners(r)
        nm = names[slug] = _rname(slug, r)
        for x in r.get("rows") or []:
            if not isinstance(x.get("fin"), int):
                g["stop"][str(x.get("fin"))] += 1
        fav = next((x for x in run if x.get("pop") == 1), None)
        c = g["grade"][r.get("grade") or ""]
        c.n += 1
        if fav:
            c.fav.add(_fin(fav))
        if _pay1(r, "3連単"):
            c.t3.append(_pay1(r, "3連単"))
        for k in KINDS:
            if _pay1(r, k):
                g["pay"][k].append((_pay1(r, k), nm, r["date"]))
        win = [x for x in run if _fin(x) == 1]
        for x in win:
            g["winners"] += 1
            g["sexw"][x.get("sex") or ""] += 1
            if g["lowwin"] is None or x["pop"] > g["lowwin"][0]:
                g["lowwin"] = (x["pop"], x["name"], nm, _pay1(r, "単勝"))
        if not _flat(r):
            g["jump"].append((r["date"], nm, r.get("grade"), win[0] if win else None, _pay1(r, "3連単")))
            continue
        fast = min((float(x["last3f"]) for x in run if re.fullmatch(r"\d+\.\d", str(x.get("last3f") or ""))), default=None)
        for x in run:
            f_ = _fin(x)
            g["jockey"][x.get("jockey") or ""].add(f_)
            g["trainer"][x.get("trainer") or ""].add(f_)
            if x.get("age"):
                g["agerec"][min(int(x["age"]), 7)].add(f_)
            if x.get("sex"):
                g["sexrec"][x["sex"]].add(f_)
            try:
                kg = float(x.get("kg"))
                g["kg"]["54kg以下" if kg <= 54 else "55〜56kg" if kg <= 56 else "57kg" if kg <= 57 else "58kg以上"].add(f_)
            except (TypeError, ValueError):
                pass
            cs = [int(n) for n in re.findall(r"\d+", x.get("corners") or "")]
            pc_ = pos_cat(cs[-1]) if cs else None
            if pc_:
                g["pos"][pc_].add(f_)
            if fast is not None and str(x.get("last3f")) == f"{fast:.1f}":
                g["agari"].add(f_)
        g["agari_n"] += fast is not None
        two = [x for x in run if _fin(x) == 2]
        if two:
            m = nf(two[0].get("margin")).strip()
            g["margin"]["ハナ" if m == "ハナ" else "アタマ" if m == "アタマ" else "クビ" if m == "クビ" else "1/2〜3/4馬身" if m in ("1/2", "3/4")
                        else "1〜2馬身" if re.fullmatch(r"1( \d/\d)?|2", m) else "同着" if m == "同着" else "2馬身半以上"] += 1
    # 今年のクラシック（3歳の三冠レース）
    for slug, label in CLASSIC:
        r = (K.get(slug) or {}).get(year)
        if r and _done(r):
            w = next((x for x in _runners(r) if _fin(x) == 1), None)
            if w:
                g["classic"].append((label, r["date"], w, _pay1(r, "単勝"), _pay1(r, "3連単")))
    # 馬場状態・負担重量の決め方は数が少ないので、過去10年と今年を合わせて数える（平地だけ）
    for slug, r in past + cur:
        if not _flat(r):
            continue
        run = _runners(r)
        fav = next((x for x in run if x.get("pop") == 1), None)
        for key, group in ((r.get("track") or "", "track"), (_wcond(slug), "cond")):
            if not key:
                continue
            c = g[group][key]
            c.n += 1
            if fav:
                c.fav.add(_fin(fav))
            if _pay1(r, "3連単"):
                c.t3.append(_pay1(r, "3連単"))
    # 今年の平地G1の勝ち馬は、その前（150日以内）にJRAの重賞を走っていたか
    runs = defaultdict(list)
    for slug, ys in K.items():
        for y in (year - 1, year):
            r = ys.get(y)
            if r and _done(r):
                for x in _runners(r):
                    runs[x["name"]].append((r["date"], _fin(x)))
    for slug, r in cur:
        if r.get("grade") != "G1":
            continue
        for x in _runners(r):
            if _fin(x) != 1:
                continue
            g["g1prior"][0] += 1
            d0 = datetime.strptime(r["date"], "%Y%m%d")
            prev = sorted((d, f) for d, f in runs.get(x["name"], []) if d < r["date"] and (d0 - datetime.strptime(d, "%Y%m%d")).days <= 150)
            if prev:
                g["g1prior"][1] += 1
                g["g1prior"][2] += prev[-1][1] <= 3
    # 失格になった馬（集めた全部の年から）
    allr = [(s_, y, r) for s_, ys in K.items() for y, r in ys.items() if _done(r)]
    g["all_n"] = len(allr)
    g["all_span"] = (min((y for _, y, _ in allr), default=year), year)
    g["dq"] = [(y, _rname(s_, r), x.get("name") or "", x.get("pop")) for s_, y, r in allr for x in r.get("rows") or [] if x.get("fin") == "失格"]
    G.clear(); G.update(g)


# ---------- S：このサイトの予想記録と出馬表 ----------
def _days(a: str, b: str) -> int | None:
    def p(s):
        m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", nf(s))
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    x, y = p(a), p(b)
    return (y - x).days if x and y else None


def _jkey(s) -> str:
    return re.sub(r"[\s▲△☆★◇]", "", nf(s))


def _load_site(by_date: dict, sg: dict) -> None:
    B = _B
    s = dict(first="", last="", races=0, jra=0, nar=0, sg=sg, hon=defaultdict(Rec), cls=defaultdict(lambda: [Cat(), Rec()]),
             wcond=defaultdict(lambda: [Cat(), Rec()]), bw=defaultdict(Rec), bw_w=[], gap=defaultdict(lambda: [Rec(), Rec()]),
             tataki=[Rec(), Rec()], jch={"同じ騎手": [Rec(), Rec()], "乗り替わり": [Rec(), Rec()]}, genryo=defaultdict(Rec),
             sire=defaultdict(Rec), sire_nar=defaultdict(Rec), owner=defaultdict(Rec), trainer=defaultdict(Rec), tozai=defaultdict(Rec),
             jockey=defaultdict(Rec), narcls=defaultdict(Rec), night=defaultdict(Rec), banei=[Rec(), 0, 0], tennyu=[Rec(), Rec()],
             top={k: (0, None) for k in KINDS}, dg=[], meet={}, bets=Counter(), bet_races=0, skip=0,
             toku=defaultdict(lambda: [Cat(), Rec()]), toku_late=[0, 0], perday=Counter(), post=["99:99", "00:00"])
    for d in sorted(by_date):
        if d < B.STATS_FROM:
            continue
        for p in by_date[d]:
            race, res, sc = p.get("_race") or {}, p.get("_result") or {}, p.get("_score") or {}
            fins = {x.get("number"): (int(x["finish"]) if str(x.get("finish") or "").isdigit() else (99 if x.get("finish") == "中止" else None))
                    for x in res.get("rows") or []}
            if sum(1 for v in fins.values() if v and v <= 3) < 3:
                continue
            jra = str(p.get("race_id", "")).startswith("jra")
            venue = B.venue_of(p)
            s["races"] += 1
            s["jra" if jra else "nar"] += 1
            s["perday"][d] += 1
            pt = race.get("post_time") or ""
            if re.fullmatch(r"\d{1,2}:\d{2}", pt):
                s["post"] = [min(s["post"][0], pt.zfill(5)), max(s["post"][1], pt.zfill(5))]
            s["first"] = s["first"] or d
            s["last"] = max(s["last"], d)
            pays = res.get("payouts") or {}
            for k in KINDS:
                for x in pays.get(k) or []:
                    if x.get("yen") and int(x["yen"]) > s["top"][k][0]:
                        s["top"][k] = (int(x["yen"]), (d, p))
            hon = (p.get("marks") or {}).get("◎")
            skip = p.get("confidence") == "見送り" or hon is None or sc.get("voided")
            hf = None if skip else fins.get(hon)
            name = nf(p.get("race_name") or race.get("race_name") or "")
            title = nf(race.get("title_text") or "") + " " + name
            fav_n = next((x.get("number") for x in res.get("rows") or [] if x.get("popularity") == 1), None)
            favf = fins.get(fav_n) if fav_n is not None else None
            t3 = next((int(x["yen"]) for x in pays.get("3連単") or [] if x.get("yen")), 0)

            def cat(pair, key):
                c, h = pair[key]
                c.n += 1
                if favf:
                    c.fav.add(favf)
                if t3:
                    c.t3.append(t3)
                if hf:
                    h.add(hf)
            if hf:
                s["hon"]["中央" if jra else "地方"].add(hf)
                s["hon"]["芝" if race.get("surface") == "芝" else "ダート" if race.get("surface") == "ダ" else "その他"].add(hf)
            grade = B.extra.grade_of(race, p.get("race_name") or race.get("race_name") or race.get("title_text") or "") or ""
            if jra:
                m = re.search(r"新馬|未勝利|1勝クラス|2勝クラス|3勝クラス|オープン", title)
                k = "オープン・重賞" if grade else (m.group(0) if m else "")
                if k == "オープン":
                    k = "オープン・重賞"
                if k:
                    cat(s["cls"], k)
                wm = re.search(r"ハンデ|別定|定量|馬齢", title)
                if wm:
                    cat(s["wcond"], wm.group(0))
                # レース名のあるレース（特別競走）と、条件の名前だけのレース（一般競走）
                tk = "一般競走" if re.search(r"新馬|未勝利|クラス$|メイクデビュー", nf(race.get("race_name") or "")) else "特別競走"
                cat(s["toku"], tk)
                if tk == "特別競走":
                    s["toku_late"][0] += 1
                    s["toku_late"][1] += B.race_no(p) >= 9
                if race.get("meeting"):
                    s["meet"][(d, venue)] = race["meeting"]
            else:
                if venue.startswith("帯広"):
                    if hf:
                        s["banei"][0].add(hf)
                    if sc.get("stake"):
                        s["banei"][1] += sc["stake"]; s["banei"][2] += sc.get("return") or 0
                elif hf:
                    cm = re.search(r"(?<![A-Za-z])([ABC])(?=[0-9一二三四五六七八九十\-ー ]|級|$)", name)
                    if cm and not grade:
                        s["narcls"][cm.group(1)].add(hf)
                    s["night"]["17時より前" if (race.get("post_time") or "99") < "17:00" else "17時以降（ナイター）"].add(hf)
                if re.match(r"(Jpn|JPN|G)\s*[123]$", nf(grade)):
                    w = next((x for x in res.get("rows") or [] if str(x.get("finish")) == "1"), {})
                    s["dg"].append((d, p, nf(grade), w.get("name") or B.horse_name(p, w.get("number")), None if skip else hon, hf))
            if not skip and d >= B.RULE_FROM:
                s["bet_races"] += 1
                for b in p.get("bets") or []:
                    s["bets"][b.get("type")] += 1
            elif skip:
                s["skip"] += 1
            banei = venue.startswith("帯広")
            xchg = bool(re.search(r"交流|JRA|指定", name + nf(race.get("conditions"))))  # 中央の馬も出る交流のレース
            for h in race.get("horses") or []:
                f_ = fins.get(h.get("number"))
                if not f_:
                    continue
                i = 0 if jra else 1
                # 馬体重の増減（ばんえいは体重が倍ほど違うので除く）
                bw = nf(h.get("body_weight_change"))
                m = re.search(r"\(([+-]?\d+)\)", bw) if jra else re.fullmatch(r"\d{3,4}([+-]\d+)", bw.replace("±0", "+0"))
                if m and not banei:
                    ch = int(m.group(1))
                    s["bw"]["10kg以上減" if ch <= -10 else "4〜9kg減" if ch <= -4 else "3kg以内の増減" if ch <= 3 else "4〜9kg増" if ch <= 9 else "10kg以上増"].add(f_)
                    w_ = h.get("body_weight") if jra else int(re.match(r"\d+", bw).group(0))
                    if f_ == 1 and w_:
                        s["bw_w"].append(int(w_))
                past = h.get("past") or []
                if past and not banei:
                    gap = _days(past[0].get("date"), race.get("date") or d)
                    if gap is not None and gap >= 0:
                        k = GAPS[0] if gap <= 10 else GAPS[1] if gap <= 38 else GAPS[2] if gap <= 73 else GAPS[3] if gap < 180 else GAPS[4]
                        s["gap"][k][i].add(f_)
                        if len(past) >= 2 and gap <= 73:
                            g2 = _days(past[1].get("date"), past[0].get("date"))
                            if g2 is not None and g2 >= 90:
                                s["tataki"][i].add(f_)
                    pj, cj = _jkey(past[0].get("jockey")), _jkey(h.get("jockey_raw") or h.get("jockey"))
                    if pj and cj:
                        s["jch"]["同じ騎手" if pj == cj else "乗り替わり"][i].add(f_)
                    if not jra and not grade and not xchg:
                        pv = nf(past[0].get("venue"))
                        s["tennyu"][0 if pv.startswith("J") and pv[1:] in JRA_V else 1].add(f_)
                if jra:
                    s["genryo"][h.get("jockey_mark") or "印なし"].add(f_)
                    pr = h.get("profile") or {}
                    if pr.get("父"):
                        s["sire"][nf(pr["父"]).strip()].add(f_)
                    if pr.get("馬主名"):
                        s["owner"][nf(pr["馬主名"]).strip()].add(f_)
                    tn = nf(pr.get("調教師名") or "")
                    tz = re.search(r"栗東|美浦", tn)
                    if tz:
                        s["tozai"][tz.group(0)].add(f_)
                    if h.get("trainer"):
                        s["trainer"][re.sub(r"\s+", "", nf(h["trainer"]))].add(f_)
                    if h.get("jockey"):
                        s["jockey"][re.sub(r"\s+", "", nf(h["jockey"]))].add(f_)
                elif h.get("sire") and not banei:
                    s["sire_nar"][nf(h["sire"]).strip()].add(f_)
    led = B.ledger()
    s["led"] = (len(led), sum(int(r["stake"]) for r in led), sum(int(r["return"]) for r in led), sum(1 for r in led if int(r["return"] or 0) > 0))
    now = [r for r in led if r["date"] >= B.RULE_FROM]
    s["rule"] = (len(now), sum(int(r["stake"]) for r in now), sum(int(r["return"]) for r in now), sum(1 for r in now if int(r["return"] or 0) > 0))
    S.clear(); S.update(s)


def prepare(B, by_date: dict, sg: dict, K: dict) -> None:
    global _B
    _B = B
    _load_hist(B.ROOT)
    _load_graded(K or {}, B.TODAY)
    _load_site(by_date, sg or {})


# ---------- 元にした記録の言い方 ----------
def h_scope() -> str:
    return f"中央競馬の平地の全レース{H['n']:,}件（{ym(H['first'])}〜{ym(H['last'])}）"


def g_scope() -> str:
    return f"{G['year']}年のJRAの重賞{G['n']}レース（{int(G['asof'][4:6])}月{int(G['asof'][6:8])}日まで）"


def s_scope() -> str:
    return f"このサイトがAI予想を出した{S['races']:,}レース（中央{S['jra']:,}・地方{S['nar']:,}。{jd(S['first'])}〜{int(S['last'][4:6])}月{int(S['last'][6:8])}日）"


SRC = {"H": lambda: h_scope() + "の結果（JRAの発表）", "G": lambda: g_scope() + "の全着順と払戻（JRAの発表）",
       "G10": lambda: f"{G['span'][0]}〜{G['span'][1]}年のJRAの平地の重賞の全着順と払戻（JRAの発表）",
       "GA": lambda: f"{G['all_span'][0]}〜{G['all_span'][1]}年のJRAの重賞の全着順（JRAの発表）",
       "S": lambda: s_scope() + "の印・結果・出馬表"}


def _race_link(d: str, p: dict) -> str:
    return f"<a href='{_B.race_path(d, p)}'>{_B.esc(jd(d))} {_B.esc(_B.race_label(p))}</a>"


def _ok(*conds) -> bool:
    return all(conds)


# ---------- ひとつひとつの数字のまとまり（(HTML, 元にした記録) を返す。数が足りなければ None） ----------
BANDS = {
    "単勝": ((200, "200円未満（2倍未満）"), (500, "200〜490円"), (1000, "500〜990円"), (3000, "1,000〜2,990円"), (10 ** 9, "3,000円以上（30倍以上）")),
    "複勝": ((150, "150円未満"), (200, "150〜190円"), (300, "200〜290円"), (500, "300〜490円"), (10 ** 9, "500円以上")),
    "枠連": ((500, "500円未満"), (1000, "500〜990円"), (3000, "1,000〜2,990円"), (10000, "3,000〜9,990円"), (10 ** 9, "1万円以上")),
    "馬連": ((1000, "1,000円未満"), (3000, "1,000〜2,990円"), (10000, "3,000〜9,990円"), (50000, "1万〜4万9,990円"), (10 ** 9, "5万円以上")),
    "ワイド": ((300, "300円未満"), (500, "300〜490円"), (1000, "500〜990円"), (3000, "1,000〜2,990円"), (10 ** 9, "3,000円以上")),
    "馬単": ((1000, "1,000円未満"), (3000, "1,000〜2,990円"), (10000, "3,000〜9,990円"), (50000, "1万〜4万9,990円"), (10 ** 9, "5万円以上")),
    "3連複": ((1000, "1,000円未満"), (5000, "1,000〜4,990円"), (10000, "5,000〜9,990円"), (100000, "1万〜9万9,990円"), (10 ** 9, "10万円以上")),
    "3連単": ((10000, "1万円未満"), (50000, "1万〜4万9,990円"), (100000, "5万〜9万9,990円"), (1000000, "10万〜99万9,990円"), (10 ** 9, "100万円以上")),
}


def _where(t) -> str:
    d, v, r, c = t
    return f"{jd(d)}の{v}{r}R"


def b_pay(kind: str):
    v = H["payall"].get(kind) or H["pay"][kind]
    if len(v) < 500:
        return None
    v = sorted(v)
    top, at = H["top"][kind]
    rows, lo = [], 0
    for hi, label in BANDS[kind]:
        n = sum(1 for y in v if lo <= y < hi)
        rows.append([label, f"{n:,}", pc(100 * n / len(v))])
        lo = hi
    unit = "的中1つあたり" if kind in ("複勝", "ワイド") else "1レースあたり"
    out = (f"<h3>{kind}の払戻はどのくらいか</h3><p>{h_scope()}で、{kind}の払戻（100円あたり・{unit}）のまん中の値（中央値）は{yen(median(v))}だった。"
           f"いちばん高かったのは{_where(at)}の{man(top)}。</p>"
           + table(["払戻（100円あたり）", "回数", "割合"], rows))
    src = ["H"]
    gp = sorted(G["pay"].get(kind) or [])
    if len(gp) >= 20:
        (mn, mn_r, _), (mx, mx_r, _) = gp[0], gp[-1]
        out += (f"<p>{g_scope()}に限ると、{kind}の中央値は{yen(median([y for y, *_ in gp]))}。最高は{_B.esc(mx_r)}の{man(mx)}、最低は{_B.esc(mn_r)}の{yen(mn)}だった。</p>")
        src.append("G")
    ai = {"単勝": "◎の単勝だけ（1点）", "複勝": "◎の複勝だけ（1点）", "ワイド": "◎-〇のワイド1点", "馬連": "◎-〇の馬連1点"}.get(kind)
    b = (S["sg"].get("hon") or {}).get(ai) if ai else None
    if b and b.n >= 100:
        what = f"◎の{kind}" if kind in ("単勝", "複勝") else f"◎と〇の{kind}1点"
        out += (f"<p>このサイトのAIの印で{what}を毎レース100円ずつ買った場合は、{b.n:,}レースで{b.hit:,}回的中（的中率{pc(100 * b.hit / b.n)}）、"
                f"回収率は{_B.roi_txt(b.stake, b.ret)}になる（{jd(S['first'])}から）。</p>")
        src.append("S")
    return out, src


def b_payall():
    rows = []
    for k in KINDS:
        v = sorted(H["payall"].get(k) or H["pay"][k])
        if len(v) < 500:
            return None
        rows.append([k, yen(median(v)), pc(100 * sum(1 for y in v if y >= 10000) / len(v)), man(H["top"][k][0])])
    return (f"<h3>券種ごとの払戻の大きさ</h3><p>{h_scope()}の払戻（100円あたり）を券種ごとに並べた。当てにくい券種ほど、払戻は大きくなる。</p>"
            + table(["券種", "中央値", "1万円以上の割合", "最高"], rows)
            + "<p>中央値は、払戻を小さい順に並べたときのまん中の値。ごく一部の高額な払戻に引っぱられないので、ふだんの大きさが分かる。</p>"), ["H"]


def b_fav():
    t, f = H["tan_fav"], H["fuku_fav"]
    n = t[0] // 100
    if n < 500:
        return None
    return (f"<h3>1番人気を買い続けた場合</h3><p>{h_scope()}で、1番人気の馬の単勝を毎レース100円ずつ買った場合、的中は{t[2]:,}回（{pc(100 * t[2] / n)}）で、"
            f"回収率は{_B.roi_txt(t[0], t[1])}。複勝なら的中は{f[2]:,}回（{pc(100 * f[2] / n)}）で、回収率は{_B.roi_txt(f[0], f[1])}だった。"
            "よく当たるが、払戻が小さいので、買い続けると少しずつ減っていく。</p>"), ["H"]


def b_pop():
    P = H["pop"]
    if P[1].n < 500:
        return None
    rows = []
    for label, ks in (("1番人気", [1]), ("2番人気", [2]), ("3番人気", [3]), ("4番人気", [4]), ("5番人気", [5]), ("6〜9番人気", range(6, 10)), ("10番人気以下", range(10, 19))):
        r = Rec()
        for k in ks:
            r.n += P[k].n; r.w += P[k].w; r.s += P[k].s; r.t += P[k].t
        rows.append([label, f"{r.n:,}", pc(r.wr()), pc(r.r2()), pc(r.r3())])
    out = (f"<h3>人気別の成績</h3><p>{h_scope()}の全出走馬を、単勝の人気で分けた。勝率は1着、連対率は2着以内、複勝率は3着以内に入った割合。</p>"
           + table(["人気", "出走数", "勝率", "連対率", "複勝率"], rows))
    src = ["H"]
    favs = Rec()
    for c in G["grade"].values():
        favs.n += c.fav.n; favs.w += c.fav.w; favs.s += c.fav.s; favs.t += c.fav.t
    if favs.n >= 30:
        out += (f"<p>{g_scope()}では、1番人気は{favs.w}勝・2着{favs.s}回・3着{favs.t}回（勝率{pc(favs.wr(), 0)}、複勝率{pc(favs.r3(), 0)}）。</p>")
        src.append("G")
    return out, src


def _mark_rows() -> list[list]:
    a = (_B.MARK_STATS or {}).get("全体")
    if not a or a["races"] < 100:
        return []
    rows = []
    for m in list(_B.MARKS) + ["無印"]:
        n = a["horses"].get(m, 0)
        if n < 30:
            continue
        w, s_, t = (a["fin"][m][i] for i in (1, 2, 3))
        rows.append([{"◎": "◎（本命）", "〇": "〇（対抗）", "▲": "▲（単穴）", "△": "△（連下）", "☆": "☆（穴）", "無印": "印なし"}[m], f"{n:,}",
                     pc(100 * w / n), pc(100 * (w + s_) / n), pc(100 * (w + s_ + t) / n)])
    return rows


def b_marks():
    rows = _mark_rows()
    if not rows:
        return None
    a = _B.MARK_STATS["全体"]
    return (f"<h3>このサイトのAIの印ごとの成績</h3><p>結果が出た{a['races']:,}レース（{jd(S['first'])}から。中央・地方）で、AIが付けた印ごとに着順を数えた。"
            "外れたレースも全部入っている。</p>" + table(["印", "頭数", "勝率", "連対率", "複勝率"], rows)
            + "<p>印の付け方は<a href='/about/'>予想の方法</a>、毎日の成績は<a href='/results/'>成績</a>に載せている。</p>"), ["S"]


def b_ai_roi():
    n, st, rt, hit = S["led"]
    if n < 100:
        return None
    out = (f"<h3>このサイトのAI予想の的中率と回収率</h3><p>買い目を出した{n:,}レース（{jd(S['first'])}から。外れも含む）で、1つでも当たったレースは{hit:,}（的中率{pc(100 * hit / n)}）、"
           f"すべての買い目を100円ずつ買った場合の回収率は{_B.roi_txt(st, rt)}。" + ("100%を下回っていて、買い続けると減る成績である。" if rt < st else ""))
    n2, st2, rt2, hit2 = S["rule"]
    if n2 >= 50:
        out += (f"今の買い方（◎の単勝か複勝を1点。{int(_B.RULE_FROM[4:6])}月{int(_B.RULE_FROM[6:8])}日から）に限ると、{n2:,}レースで的中率{pc(100 * hit2 / n2)}、回収率{_B.roi_txt(st2, rt2)}。")
    out += "</p><p>的中率が高くても、払戻が小さければ回収率は100%に届かない。くわしくは<a href='/results/'>成績</a>と<a href='/limits/'>AI予想の限界</a>へ。</p>"
    return out, ["S"]


def _bucket_rows(group: str, keys: list[tuple[str, str]]) -> list[list]:
    g = S["sg"].get(group) or {}
    rows = []
    for key, label in keys:
        b = g.get(key)
        if b and b.n >= 20:
            rows.append([label, f"{b.n:,}", pc(100 * b.hit / b.n), _B.roi_txt(b.stake, b.ret)])
    return rows


def _mono(rows: list[list]) -> bool:
    """表の上の行ほど回収率が高いか（期待値の高い順に並んだ表用）。"""
    v = [float(r[-1].rstrip("%")) for r in rows if r[-1].endswith("%")]
    return all(a >= b for a, b in zip(v, v[1:]))


def b_ai_value():
    rows = _bucket_rows("val_win", [("期待値1.5以上（◎単勝1点）", "1.5以上"), ("期待値1.0〜1.5（◎単勝1点）", "1.0〜1.5"),
                                    ("期待値0.7〜1.0（◎単勝1点）", "0.7〜1.0"), ("期待値0.7未満（◎単勝1点）", "0.7未満")])
    if len(rows) < 3:
        return None
    return ("<h3>期待値で分けると、実際の回収率はどうだったか</h3><p>このサイトでは、AIが見積もった勝つ確率に単勝オッズを掛けた数字を期待値として出している（1.0より大きければ、計算の上では得な馬券）。"
            f"◎の単勝を100円ずつ買った場合を、その期待値で分けた（{jd(S['first'])}から）。</p>" + table(["◎の期待値", "レース数", "的中率", "回収率"], rows)
            + "<p>" + ("期待値が高いほど回収率も高い、とはなっていない。AIの見積もりが強気すぎるレースがあるためで、" if not _mono(rows) else "いまのところ、期待値が高い区分ほど回収率も高い。")
            + "<a href='/strategy/'>買い方別の回収率</a>で毎日確かめている。</p>"), ["S"]


def b_ai_pop():
    w = _bucket_rows("pop_win", [("◎が1番人気（単勝1点）", "◎が1番人気"), ("◎が2〜3番人気（単勝1点）", "◎が2〜3番人気"),
                                 ("◎が4〜6番人気（単勝1点）", "◎が4〜6番人気"), ("◎が7番人気以下（単勝1点）", "◎が7番人気以下")])
    if len(w) < 3:
        return None
    return (f"<h3>AIの◎を人気で分けた場合</h3><p>このサイトのAIの◎の単勝を100円ずつ買った場合を、◎の馬の人気で分けた（{jd(S['first'])}から。人気は予想を出した時点）。</p>"
            + table(["◎の人気", "レース数", "的中率", "回収率"], w)), ["S"]


SIM_LABEL = {
    "box3": ("3連複 1〜5番人気のボックス", 10), "wide3": ("ワイド 1〜3番人気のボックス", 3), "nagashi": ("馬連 1番人気から2〜6番人気へ流し", 5),
    "form": ("3連単フォーメーション（1着：1番人気、2着：2〜4番人気、3着：2〜7番人気）", 15), "multi": ("3連単 1番人気を軸にしたマルチ（相手は2〜5番人気）", 36),
}


def b_sims(keys: tuple, head: str, lead: str):
    rows = []
    for k in keys:
        st, rt, hit = H["sims"][k]
        label, pts = SIM_LABEL[k]
        n = st // (pts * 100)
        if n < 500:
            return None
        rows.append([label, f"{pts}点", pc(100 * hit / n), _B.roi_txt(st, rt)])
    return (f"<h3>{head}</h3><p>{lead}{h_scope()}で、人気順だけで決めた買い目を毎レース各点100円ずつ買った場合を計算した。</p>"
            + table(["買い方", "1レースの点数", "的中率", "回収率"], rows)
            + "<p>点数を増やすと当たる回数は増えるが、買う金額も増える。"
            + ("どの買い方も回収率は100%に届いていない（馬券の売上から、払戻に回らない分が先に引かれるため）。" if all(H["sims"][k][1] < H["sims"][k][0] for k in keys) else "")
            + "</p>"), ["H"]


def b_win5():
    f = H["pop"][1]
    if f.n < 500:
        return None
    p = f.w / f.n
    w3 = sum(H["winpop"][k] for k in (1, 2, 3)) / sum(H["winpop"].values())
    return (f"<h3>5レース続けて当てる難しさ</h3><p>{h_scope()}では、1番人気が勝った割合は{pc(100 * p)}。この割合のまま、5レースすべてで1番人気が勝つ確率を計算すると"
            f"約{100 * p ** 5:.2f}%（およそ{round(1 / p ** 5):,}回に1回）になる。</p><p>勝ち馬が1〜3番人気のどれかだった割合は{pc(100 * w3)}。"
            f"5レースとも1〜3番人気を全部買うと3×3×3×3×3＝243点（24,300円）で、5レースとも当たる確率は約{100 * w3 ** 5:.1f}%になる。"
            "WIN5の対象は各競馬場のメインレースなどで、頭数が多く力の差が小さいレースが多いので、実際はこれより難しくなりやすい。</p>"), ["H"]


def b_ganpon():
    if H["fuku_n"] < 1000:
        return None
    return (f"<h3>元返しはどのくらい起きるか</h3><p>{h_scope()}で、複勝の払戻が100円（元返し）だったのは{H['fuku100']:,}回。複勝の的中{H['fuku_n']:,}件のうち"
            f"{pc(100 * H['fuku100'] / H['fuku_n'], 2)}にあたる。単勝の払戻が110円以下だったレースは{H['tan_low']:,}回あった。</p>"
            f"<p>1番人気が3着以内に入った{H['fav_fuku_n']:,}回のうち、その複勝の払戻が110円以下（100円か110円）だったのは{H['fav_fuku_low']:,}回（{pc(100 * H['fav_fuku_low'] / max(1, H['fav_fuku_n']))}）。"
            "元返しや、当たってもほとんど増えない払戻は、人気が1頭に集中したレースで起きる。</p>"), ["H"]


def b_tokubarai():
    t, at = H["top"]["3連単"]
    return (f"<h3>特払いはどのくらい起きるか</h3><p>中央競馬の全レース{H['n'] + H['jump']:,}件（{ym(H['first'])}〜{ym(H['last'])}。障害を含む）の、8つの券種の払戻を調べたところ、"
            f"特払い（100円につき70円）は{H['toku']}回だった。</p><p>この期間でいちばん高かった3連単は{_where(at)}の{man(t)}だが、このレースでも的中した馬券はあり、特払いにはなっていない。"
            "いまは3連単のように組み合わせの多い券種でも売上が大きいので、特払いはめったに起きない。</p>"), ["H"]


def b_stop():
    c = H["stop"]
    n = H["n"] + H["jump"]
    if n < 500:
        return None
    back = c["取消"] + c["除外"]
    out = (f"<h3>出走取消・競走除外・競走中止の数</h3><p>中央競馬の全レース{n:,}件（{ym(H['first'])}〜{ym(H['last'])}。障害を含む）で、出走取消は{c['取消']:,}頭、競走除外は{c['除外']:,}頭、"
           f"競走中止は{c['中止']:,}頭だった。取消と除外を合わせると{back:,}頭で、およそ{round(n / max(1, back))}レースに1頭の割合になる。</p>"
           "<p>取消と除外はレースが始まる前の出来事なので、その馬の馬券は買った金額がそのまま戻る（返還）。競走中止はレースが始まってからの出来事なので、返還は無い。</p>")
    return out, ["H"]


def _pos_rows(src: dict) -> list[list]:
    return [[k, f"{src[k].n:,}", pc(src[k].wr()), pc(src[k].r3())] for k in POS if src[k].n >= 30]


def b_pos(lead: str = ""):
    rows = _pos_rows(H["pos"])
    if len(rows) < 4:
        return None
    out = (f"<h3>4コーナーの位置と着順</h3><p>{lead}{h_scope()}の出走馬を、最後のコーナー（4コーナー）を何番手で回ったかで分けた。</p>"
           + table(["4コーナーの位置", "出走数", "勝率", "複勝率"], rows)
           + "<p>前にいた馬ほどよく勝っている。ただし、強い馬ほど前の位置を取れるという面もあり、「前に行けば勝てる」という意味ではない。</p>")
    src = ["H"]
    g = G["pos"]
    if g[POS[0]].n >= 50:
        out += (f"<p>{G['year']}年のJRAの平地の重賞では、4コーナーを先頭で回った馬は{g[POS[0]].n}頭のうち{g[POS[0]].w}頭が勝った（勝率{pc(g[POS[0]].wr(), 0)}、複勝率{pc(g[POS[0]].r3(), 0)}）。"
                f"10番手以下だった馬は{g[POS[3]].n}頭で{g[POS[3]].w}勝（複勝率{pc(g[POS[3]].r3(), 0)}）。"
                f"<a href='/column/year{G['year']}-waku/'>{G['year']}年の重賞の枠番・脚質の傾向</a>にくわしく載せている。</p>")
        src.append("G")
    return out, src


def b_agari():
    a = G["agari"]
    if G["agari_n"] < 30:
        return None
    return (f"<h3>上がり3ハロンがいちばん速かった馬の着順</h3><p>{G['year']}年のJRAの平地の重賞{G['agari_n']}レース（{int(G['asof'][4:6])}月{int(G['asof'][6:8])}日まで）で、"
            f"そのレースの上がり3ハロンがいちばん速かった馬（同じタイムの馬を含めて{a.n}頭）は、{a.w}勝・2着{a.s}回・3着{a.t}回。"
            f"勝率は{pc(a.wr(), 0)}、複勝率は{pc(a.r3(), 0)}だった。</p><p>上がりがいちばん速くても3着以内に入れなかった馬は{a.n - a.top3}頭いる。"
            "後ろの位置から速い上がりを出しても、前の馬に届かないことがあるためで、上がりのタイムは4コーナーの位置とあわせて見ると意味が分かりやすい。</p>"), ["G"]


def b_margin():
    m = G["margin"]
    n = sum(m.values())
    if n < 30:
        return None
    rows = [[k, f"{m[k]}", pc(100 * m[k] / n, 0)] for k in ("ハナ", "アタマ", "クビ", "1/2〜3/4馬身", "1〜2馬身", "2馬身半以上", "同着") if m[k]]
    close = m["ハナ"] + m["アタマ"] + m["クビ"]
    return (f"<h3>1着と2着の着差</h3><p>{G['year']}年のJRAの平地の重賞{n}レース（{int(G['asof'][4:6])}月{int(G['asof'][6:8])}日まで）の、1着と2着の差を数えた。"
            f"クビ差より小さい決着（ハナ・アタマ・クビ）は{close}レースで、全体の{pc(100 * close / n, 0)}を占める。</p>" + table(["1着と2着の差", "レース数", "割合"], rows)), ["G"]


def _cat_rows(cats: dict, order: tuple, minn: int = 20) -> list[list]:
    return [[k, f"{cats[k].n:,}", pc(cats[k].fav.wr()), pc(cats[k].fav.r3()), man(cats[k].med3())] for k in order if cats[k].n >= minn]


CAT_HEAD = ["", "レース数", "1番人気の勝率", "1番人気の複勝率", "3連単の中央値"]


def b_going():
    rows = _cat_rows(G["track"], ("良", "稍重", "重", "不良"), 10)
    if len(rows) < 3:
        return None
    return (f"<h3>馬場状態ごとの重賞の結果</h3><p>{G['span'][0]}〜{G['span'][1]}年のJRAの平地の重賞を、発表された馬場状態で分けた。"
            "1番人気がどのくらい来たかと、3連単の払戻のまん中の値を並べている。</p>" + table(["馬場状態"] + CAT_HEAD[1:], rows)
            + "<p>重・不良はレースの数が少ないので、数字は目安として見てほしい。</p>"), ["G10"]


def b_surface():
    rows = _cat_rows(H["surf"], ("芝", "ダ"))
    if len(rows) < 2:
        return None
    rows = [["芝" if r[0] == "芝" else "ダート"] + r[1:] for r in rows]
    out = (f"<h3>芝とダートの結果のちがい</h3><p>{h_scope()}を、芝とダートに分けた。</p>" + table(["コース"] + CAT_HEAD[1:], rows))
    src = ["H"]
    hs = S["hon"]
    if hs["芝"].n >= 50 and hs["ダート"].n >= 50:
        out += (f"<p>このサイトのAIの◎は、芝で{hs['芝'].n:,}レース中{hs['芝'].w:,}勝（勝率{pc(hs['芝'].wr())}、複勝率{pc(hs['芝'].r3())}）、"
                f"ダートで{hs['ダート'].n:,}レース中{hs['ダート'].w:,}勝（勝率{pc(hs['ダート'].wr())}、複勝率{pc(hs['ダート'].r3())}）。"
                f"地方競馬はほとんどがダートなので、ダートの数が多い（{jd(S['first'])}から）。</p>")
        src.append("S")
    return out, src


def b_dist():
    order = ("短距離（1400mまで）", "マイル前後（1500〜1700m）", "中距離（1800〜2400m）", "長距離（2500m以上）")
    rows = _cat_rows(H["dist"], order)
    if len(rows) < 4:
        return None
    return (f"<h3>距離ごとの結果のちがい</h3><p>{h_scope()}を、距離で4つに分けた。</p>" + table(["距離"] + CAT_HEAD[1:], rows)
            + f"<p>長距離のレースは{H['dist'][order[3]].n:,}件と少ないので、数字は目安として見てほしい。コースごとの傾向は<a href='/course/'>コース別のページ</a>で見られる。</p>"), ["H"]


def b_turn():
    rows = _cat_rows(H["turn"], ("右回り", "左回り"))
    if len(rows) < 2:
        return None
    lead = [("右回り", H["turn"]["右回り"].lead), ("左回り", H["turn"]["左回り"].lead)]
    return (f"<h3>右回りと左回りの結果</h3><p>JRAの10の競馬場のうち、左回りは東京・中京・新潟の3つで、ほかの7つ（札幌・函館・福島・中山・京都・阪神・小倉）は右回り。"
            f"{h_scope()}を回りで分けた。</p>" + table(["回り"] + CAT_HEAD[1:], rows)
            + "<p>4コーナーを先頭で回った馬の勝率は、" + "、".join(f"{k}で{pc(r.wr())}" for k, r in lead)
            + "。回りそのものより、直線の長さや坂といった競馬場ごとの形のちがいが結果に出やすい。</p>"), ["H"]


def b_slope():
    a, b = H["slope"]["坂"], H["slope"]["平坦"]
    if a.n < 300 or b.n < 300:
        return None
    return (f"<h3>坂のある競馬場と平坦な競馬場</h3><p>{h_scope()}のうち、ゴール前に急な上り坂がある中山・阪神・中京の{a.n:,}レースと、"
            f"最後の直線が平坦な京都・新潟・小倉の{b.n:,}レースを比べた。</p>"
            + table(["競馬場", "レース数", "4コーナー先頭の馬の勝率", "同じ馬の複勝率", "1番人気の勝率"],
                    [["中山・阪神・中京（ゴール前に急坂）", f"{a.n:,}", pc(a.lead.wr()), pc(a.lead.r3()), pc(a.fav.wr())],
                     ["京都・新潟・小倉（直線が平坦）", f"{b.n:,}", pc(b.lead.wr()), pc(b.lead.r3()), pc(b.fav.wr())]])
            + "<p>坂だけでなく直線の長さもちがうので、差のすべてが坂のせいとは言えない。競馬場ごとの傾向は<a href='/venue/'>競馬場ガイド</a>にまとめている。</p>"), ["H"]


def b_frame(lead: str = ""):
    F = H["frame"]
    if F[1].n < 500:
        return None
    rows = [[f"{k}枠", f"{F[k].n:,}", pc(F[k].wr()), pc(F[k].r3())] for k in range(1, 9)]
    inner, outer = Rec(), Rec()
    for k in (1, 2, 3):
        inner.n += F[k].n; inner.w += F[k].w; inner.s += F[k].s; inner.t += F[k].t
    for k in (6, 7, 8):
        outer.n += F[k].n; outer.w += F[k].w; outer.s += F[k].s; outer.t += F[k].t
    diff = inner.r3() - outer.r3()
    return (f"<h3>枠番ごとの成績</h3><p>{lead}{h_scope()}の全出走馬を、枠番で分けた。</p>" + table(["枠番", "出走数", "勝率", "複勝率"], rows)
            + f"<p>1〜3枠をまとめると勝率{pc(inner.wr())}・複勝率{pc(inner.r3())}、6〜8枠は勝率{pc(outer.wr())}・複勝率{pc(outer.r3())}。"
            + ("全体で見ると差は小さく、" if abs(diff) < 2 else f"全体では{'内' if diff > 0 else '外'}の枠のほうが少し良いが、")
            + "内と外のどちらが走りやすいかはコースと馬場の状態で変わる。7・8枠は頭数の多いレースで馬が3頭入ることがあるので、出走数が多い。"
            "コースごとの傾向は<a href='/course/'>コース別のページ</a>で見られる。</p>"), ["H"]


def b_grade():
    rows = []
    for k in ("G1", "G2", "G3"):
        c = G["grade"].get(k)
        if c and c.n >= 5:
            rows.append([k, f"{c.n}", f"{c.fav.w}勝・2着{c.fav.s}回・3着{c.fav.t}回", pc(c.fav.r3(), 0), man(c.med3())])
    if len(rows) < 3:
        return None
    out = (f"<h3>{G['year']}年の重賞を格ごとに見る</h3><p>{g_scope()}のうち、平地のG1・G2・G3を分けた。</p>"
           + table(["格", "レース数", "1番人気の成績", "1番人気の複勝率", "3連単の中央値"], rows))
    lw = G.get("lowwin")
    if lw:
        out += (f"<p>いちばん人気が無くて勝ったのは、{_B.esc(lw[2])}の{_B.link_horse(lw[1])}（{lw[0]}番人気、単勝{yen(lw[3])}）。"
                f"<a href='/column/year{G['year']}-g1-kekka/'>{G['year']}年のG1の全結果</a>も載せている。</p>")
    return out, ["G"]


def b_classic():
    if not G["classic"]:
        return None
    rows = [[label, f"{int(d[4:6])}月{int(d[6:8])}日", f"{w['name']}（{w['pop']}番人気）", w.get("jockey") or "", yen(tan) if tan else "-", man(t3) if t3 else "-"]
            for label, d, w, tan, t3 in G["classic"]]
    return (f"<h3>{G['year']}年の3歳クラシックの結果</h3><p>3歳の牡馬の三冠は皐月賞・日本ダービー・菊花賞、牝馬の三冠は桜花賞・オークス・秋華賞。"
            f"{G['year']}年に行われた分の勝ち馬を並べた。</p>" + table(["レース", "日付", "勝ち馬", "騎手", "単勝", "3連単"], rows)), ["G"]


def b_jump():
    if len(G["jump"]) < 3:
        return None
    rows = [[f"{int(d[4:6])}月{int(d[6:8])}日", f"{nm}（{g}）", f"{w['name']}（{w['pop']}番人気）" if w else "-", man(t3) if t3 else "-"]
            for d, nm, g, w, t3 in sorted(G["jump"])]
    return (f"<h3>{G['year']}年の障害の重賞の結果</h3><p>JRAの障害の重賞は、J・G1からJ・G3までの格がある。{G['year']}年に行われた{len(rows)}レースの勝ち馬と3連単の払戻を並べた。</p>"
            + table(["日付", "レース", "勝ち馬", "3連単"], rows)), ["G"]


def b_prior():
    n, a, b = G["g1prior"]
    if n < 8:
        return None
    return (f"<h3>G1の勝ち馬は、その前にどこを走っていたか</h3><p>{G['year']}年のJRAの平地のG1の勝ち馬{n}頭（{int(G['asof'][4:6])}月{int(G['asof'][6:8])}日まで）のうち、"
            f"その前の150日以内にJRAの重賞を走っていた馬は{a}頭で、そのうち{b}頭はその重賞で3着以内だった。</p>"
            f"<p>残りの{n - a}頭は、重賞ではないレース・海外や地方のレースからの出走か、5か月以上の休み明けだった。レースごとの前走の傾向は、"
            "<a href='/graded/'>重賞のページ</a>の過去データに載せている。</p>"), ["G"]


def b_wcond():
    order = ("ハンデ", "別定", "定量", "馬齢")
    rows = _cat_rows(G["cond"], order, 30)
    if len(rows) < 3:
        return None
    rows = [[{"ハンデ": "ハンデ戦", "別定": "別定", "定量": "定量", "馬齢": "馬齢"}[r[0]]] + r[1:] for r in rows]
    return (f"<h3>負担重量の決め方ごとの重賞の結果</h3><p>{G['span'][0]}〜{G['span'][1]}年のJRAの平地の重賞を、いまの負担重量の決め方（ハンデ・別定・定量・馬齢）で分けた。</p>"
            + table(["負担重量の決め方"] + CAT_HEAD[1:], rows)
            + "<p>" + ("力の差を斤量でならすハンデ戦は、1番人気が来る割合がいちばん低く、払戻がいちばん大きい。"
                       if all(G["cond"]["ハンデ"].fav.r3() <= G["cond"][k].fav.r3() and G["cond"]["ハンデ"].med3() >= G["cond"][k].med3() for k in order if G["cond"][k].n >= 30) else "")
            + "途中で決め方が変わったレースも、いまの決め方で数えている。</p>"), ["G10"]


def b_kg():
    order = ("54kg以下", "55〜56kg", "57kg", "58kg以上")
    k = G["kg"]
    rows = [[o, f"{k[o].n}", f"{k[o].w}", pc(k[o].wr()), pc(k[o].r3())] for o in order if k[o].n >= 20]
    if len(rows) < 3:
        return None
    return (f"<h3>斤量ごとの成績（{G['year']}年の重賞）</h3><p>{G['year']}年のJRAの平地の重賞（{int(G['asof'][4:6])}月{int(G['asof'][6:8])}日まで）の全出走馬を、背負った斤量で分けた。</p>"
            + table(["斤量", "出走数", "勝利", "勝率", "複勝率"], rows)
            + "<p>斤量は、性別・年齢と、レースによっては実績で決まる。"
            + ("重い斤量を背負うのは実績のある馬なので、斤量が重い馬ほど成績が悪い、という形にはなっていない。" if k["58kg以上"].n >= 20 and k["58kg以上"].r3() >= k["54kg以下"].r3() else "")
            + "「斤量が重いと不利」は、同じ馬が軽いときと比べた話である。</p>"), ["G"]


def b_class():
    order = ("新馬", "未勝利", "1勝クラス", "2勝クラス", "3勝クラス", "オープン・重賞")
    rows = []
    for k in order:
        c, h = S["cls"][k]
        if c.n >= 15 and c.fav.n >= 15:
            rows.append([k, f"{c.n}", pc(c.fav.wr(), 0), pc(c.fav.r3(), 0), pc(h.wr(), 0) if h.n >= 15 else "-", pc(h.r3(), 0) if h.n >= 15 else "-"])
    if len(rows) < 4:
        return None
    return (f"<h3>クラスごとの結果（中央競馬）</h3><p>このサイトがAI予想を出した中央競馬の{S['jra']:,}レース（{jd(S['first'])}から）を、クラスで分けた。"
            "1番人気は最終の人気、◎はこのサイトのAIの本命。</p>" + table(["クラス", "レース数", "1番人気の勝率", "1番人気の複勝率", "AIの◎の勝率", "AIの◎の複勝率"], rows)
            + "<p>レースの数がまだ少ないので、数字は毎日少しずつ動く。</p>"), ["S"]


def b_narclass():
    c = S["narcls"]
    rows = [[f"{k}クラス", f"{c[k].n:,}", pc(c[k].wr()), pc(c[k].r3())] for k in "ABC" if c[k].n >= 30]
    if len(rows) < 2:
        return None
    return (f"<h3>地方競馬のクラスごとの、AIの◎の成績</h3><p>このサイトがAI予想を出した地方競馬のレース（{jd(S['first'])}から。ばんえいと重賞を除く）のうち、レース名からA・B・Cのクラスが分かるものを数えた。</p>"
            + table(["クラス", "レース数", "◎の勝率", "◎の複勝率"], rows)
            + "<p>クラスの名前と分け方は主催者ごとにちがうので、同じ「B」でも競馬場によって馬の力はちがう。</p>"), ["S"]


def b_night():
    n = S["night"]
    a, b = n["17時より前"], n["17時以降（ナイター）"]
    if a.n < 50 or b.n < 50:
        return None
    return (f"<h3>昼のレースと夜のレース（地方競馬）</h3><p>このサイトがAI予想を出した地方競馬のレース（{jd(S['first'])}から。ばんえいを除く）を、発走時刻で分けた。</p>"
            + table(["発走時刻", "レース数", "AIの◎の勝率", "AIの◎の複勝率"],
                    [["17時より前", f"{a.n:,}", pc(a.wr()), pc(a.r3())], ["17時以降", f"{b.n:,}", pc(b.wr()), pc(b.r3())]])
            + "<p>夜のレースは、その日の昼までの結果とオッズを見てから予想を出している。</p>"), ["S"]


def b_banei():
    r, st, rt = S["banei"]
    if r.n < 30:
        return None
    return (f"<h3>ばんえい競馬でのAIの成績</h3><p>このサイトは帯広のばんえい競馬も毎日予想している。◎を付けた{r.n:,}レース（{jd(S['first'])}から）で、"
            f"◎は{r.w:,}勝（勝率{pc(r.wr())}、複勝率{pc(r.r3())}）、買い目の回収率は{_B.roi_txt(st, rt)}。</p>"
            "<p>ばんえいは通過順や上がりの記録が無く、平地のレースと同じ見方ができない。このサイトのAIが苦手にしている条件のひとつで、<a href='/limits/'>AI予想の限界</a>にも書いている。</p>"), ["S"]


def b_jranar():
    a, b = S["hon"]["中央"], S["hon"]["地方"]
    if a.n < 50 or b.n < 50:
        return None
    rows = [["中央（JRA）", f"{a.n:,}", pc(a.wr()), pc(a.r3())], ["地方", f"{b.n:,}", pc(b.wr()), pc(b.r3())]]
    src = S["sg"].get("src") or {}
    for row, key in zip(rows, ("中央（JRA）だけ", "地方だけ")):
        bk = src.get(key)
        row.append(_B.roi_txt(bk.stake, bk.ret) if bk and bk.n >= 50 else "-")
    return (f"<h3>中央と地方での、AIの成績</h3><p>{s_scope()}を、中央と地方に分けた。</p>"
            + table(["", "◎を付けたレース", "◎の勝率", "◎の複勝率", "買い目の回収率"], rows)
            + "<p>中央には芝とダートの両方があり、地方はほとんどがダートである。競馬場ごとの成績は<a href='/venue/'>競馬場ガイド</a>にある。</p>"), ["S"]


def b_bw():
    order = ("10kg以上減", "4〜9kg減", "3kg以内の増減", "4〜9kg増", "10kg以上増")
    b = S["bw"]
    rows = [[k, f"{b[k].n:,}", pc(b[k].wr()), pc(b[k].r3())] for k in order if b[k].n >= 50]
    if len(rows) < 4:
        return None
    out = (f"<h3>馬体重の増減と着順</h3><p>このサイトがAI予想を出したレース（{jd(S['first'])}から。中央・地方。ばんえいを除く）の出走馬を、前走からの馬体重の増減で分けた。</p>"
           + table(["前走からの増減", "出走数", "勝率", "複勝率"], rows))
    if len(S["bw_w"]) >= 100:
        out += f"<p>勝った馬{len(S['bw_w']):,}頭の馬体重は、平均{sum(S['bw_w']) / len(S['bw_w']):.0f}kg、いちばん軽い馬で{min(S['bw_w'])}kg、いちばん重い馬で{max(S['bw_w'])}kgだった。</p>"
    return out, ["S"]


def _two(pair) -> list[str]:
    a, b = pair
    return [f"{a.n:,}" if a.n else "-", pc(a.r3()) if a.n >= 30 else "-", f"{b.n:,}" if b.n else "-", pc(b.r3()) if b.n >= 30 else "-"]


def b_gap(focus: str = ""):
    g = S["gap"]
    rows = [[k] + _two(g[k]) for k in GAPS if g[k][0].n + g[k][1].n >= 30]
    if len(rows) < 4:
        return None
    out = (f"<h3>前走からの間隔と着順</h3><p>このサイトがAI予想を出したレース（{jd(S['first'])}から。ばんえいを除く）の出走馬を、前走からの日数で分けた。"
           "中央と地方では出走の間隔がちがうので、分けて載せる。</p>" + table(["前走からの間隔", "中央：出走数", "中央：複勝率", "地方：出走数", "地方：複勝率"], rows))
    t = S["tataki"]
    if t[0].n + t[1].n >= 50:
        out += ("<p>休み明け（3か月以上あけた出走）の次のレース、いわゆる叩き2戦目だった馬は、"
                + "、".join(f"{lab}で{r.n:,}頭・複勝率{pc(r.r3())}" for lab, r in (("中央", t[0]), ("地方", t[1])) if r.n >= 30) + "だった。</p>")
    out += "<p>出走数が少ない区分の数字は、数頭の結果で大きく動く。</p>"
    return out, ["S"]


def b_jchange():
    j = S["jch"]
    rows = [[k] + _two(j[k]) for k in ("同じ騎手", "乗り替わり")]
    if j["乗り替わり"][0].n + j["乗り替わり"][1].n < 200:
        return None
    return (f"<h3>乗り替わりと着順</h3><p>このサイトがAI予想を出したレース（{jd(S['first'])}から。ばんえいを除く）の出走馬を、前走と同じ騎手か、乗り替わりかで分けた。</p>"
            + table(["", "中央：出走数", "中央：複勝率", "地方：出走数", "地方：複勝率"], rows)
            + "<p>" + ("前走で好走した馬は同じ騎手が続けて乗ることが多いので、「同じ騎手」のほうが成績は良くなっている。乗り替わりそのものが不利という意味ではない。"
                       if all(j["同じ騎手"][i].r3() > j["乗り替わり"][i].r3() for i in (0, 1)) else "同じ騎手が続けて乗るのは前走で好走した馬に多いので、乗り替わりそのものの有利・不利とは分けて考えたい。")
            + "</p>"), ["S"]


def b_genryo():
    g = S["genryo"]
    label = {"▲": "▲（3kg減）", "△": "△（2kg減）", "☆": "☆（1kg減）", "★": "★（4kg減）", "◇": "◇（2kg減）", "印なし": "減量なし"}
    rows = [[label[k], f"{g[k].n:,}", f"{g[k].w:,}", pc(g[k].wr()), pc(g[k].r3())] for k in ("★", "▲", "△", "◇", "☆", "印なし") if g[k].n >= 30]
    if len(rows) < 4:
        return None
    return (f"<h3>減量の記号ごとの成績（中央競馬）</h3><p>このサイトがAI予想を出した中央競馬の{S['jra']:,}レース（{jd(S['first'])}から）で、出馬表の騎手名に付いた記号ごとに着順を数えた。"
            "★と◇は女性騎手に付く記号。</p>" + table(["記号", "騎乗数", "勝利", "勝率", "複勝率"], rows)
            + "<p>減量のある騎手は経験が浅く、人気のない馬に乗ることも多い。記号ごとの騎乗数がまだ少ないので、数字は目安として見てほしい。</p>"), ["S"]


def _leaders(d: dict, n: int = 5, minn: int = 5) -> list[list]:
    v = sorted(((r.w, r.top3, -r.n, k) for k, r in d.items() if k and r.n >= minn), reverse=True)[:n]
    return [[k, f"{d[k].w}", f"{d[k].n}", pc(d[k].r3(), 0)] for w, t, _, k in v if w > 0]


def b_sire():
    rows = _leaders(S["sire"], 8, 10)
    if len(rows) < 5:
        return None
    out = (f"<h3>父（種牡馬）ごとの勝利数</h3><p>このサイトがAI予想を出した中央競馬の{S['jra']:,}レース（{jd(S['first'])}から）で、勝ち星の多い父を並べた。</p>"
           + table(["父", "勝利", "出走数", "複勝率"], rows))
    nar = _leaders({k: v for k, v in S["sire_nar"].items() if len(k) < 10}, 5, 10)  # 元の出馬表は長い名前が10文字で切れているので、切れたかもしれない名前は出さない
    if len(nar) >= 5:
        out += f"<p>同じ期間の地方競馬（{S['nar']:,}レース。ばんえいを除く）で勝ち星が多かった父は、" + "、".join(f"{r[0]}（{r[1]}勝）" for r in nar) + "。地方はほとんどがダートのレースなので、中央とは顔ぶれがちがう。</p>"
    return out, ["S"]


def b_owner():
    rows = _leaders(S["owner"], 8, 10)
    if len(rows) < 5:
        return None
    club = sum(1 for r in rows[:5] if re.search(r"レーシング|ファーム|レースホース|サラブレッド|ホースクラブ", r[0]))
    return (f"<h3>馬主ごとの勝利数</h3><p>このサイトがAI予想を出した中央競馬の{S['jra']:,}レース（{jd(S['first'])}から）で、勝ち星の多い馬主を並べた。"
            + ("上位には、1頭を大勢で持つ仕組みのクラブ法人が多い。" if club >= 3 else "") + "</p>" + table(["馬主", "勝利", "出走数", "複勝率"], rows)), ["S"]


def b_trainer():
    t = S["tozai"]
    rows = _leaders(S["trainer"], 6, 8)
    if t["栗東"].n < 200 or t["美浦"].n < 200 or len(rows) < 4:
        return None
    return (f"<h3>栗東と美浦、勝ち星の多い調教師</h3><p>JRAの厩舎は、関西の栗東（滋賀県）と関東の美浦（茨城県）のトレーニングセンターに分かれている。"
            f"このサイトがAI予想を出した中央競馬の{S['jra']:,}レース（{jd(S['first'])}から）では、栗東の馬が{t['栗東'].n:,}頭出走して{t['栗東'].w:,}勝（勝率{pc(t['栗東'].wr())}、複勝率{pc(t['栗東'].r3())}）、"
            f"美浦の馬が{t['美浦'].n:,}頭出走して{t['美浦'].w:,}勝（勝率{pc(t['美浦'].wr())}、複勝率{pc(t['美浦'].r3())}）だった。</p>"
            + table(["調教師", "勝利", "出走数", "複勝率"], rows)
            + f"<p>重賞に限った調教師の成績は<a href='/column/year{G['year']}-chokyoshi/'>{G['year']}年の重賞の調教師別成績</a>に載せている。</p>"), ["S"]


def b_jockey():
    rows = _leaders(G["jockey"], 6, 5)
    if len(rows) < 5:
        return None
    out = (f"<h3>{G['year']}年の重賞で勝ち星の多い騎手</h3><p>{G['year']}年のJRAの平地の重賞（{int(G['asof'][4:6])}月{int(G['asof'][6:8])}日まで）の勝利数の上位。</p>"
           + table(["騎手", "勝利", "騎乗数", "複勝率"], rows))
    src = ["G"]
    all_ = _leaders(S["jockey"], 5, 10)
    if len(all_) >= 5:
        out += (f"<p>重賞以外も含めた中央競馬の全レース（{jd(S['first'])}から、{S['jra']:,}レース）では、" + "、".join(f"{r[0]}騎手（{r[1]}勝）" for r in all_)
                + f"の順。騎手ごとのAIの印との相性は<a href='/jockey/'>騎手別のページ</a>で見られる。</p>")
        src.append("S")
    return out, src


def b_sexage(focus: str = "sex"):
    sx, ag = G["sexrec"], G["agerec"]
    if sx["牡"].n < 100:
        return None
    w = G["sexw"]
    rows_s = [[k, f"{sx[k].n:,}", f"{sx[k].w}", pc(sx[k].wr()), pc(sx[k].r3())] for k in ("牡", "牝", "せん") if sx[k].n >= 10]
    rows_a = [[f"{k}歳" + ("以上" if k == 7 else ""), f"{ag[k].n:,}", f"{ag[k].w}", pc(ag[k].wr()), pc(ag[k].r3())] for k in sorted(ag) if ag[k].n >= 10]
    scope = f"{G['year']}年のJRAの平地の重賞（{int(G['asof'][4:6])}月{int(G['asof'][6:8])}日まで）の全出走馬"
    a = (f"<h3>性別ごとの成績（{G['year']}年の重賞）</h3><p>{scope}を、性別で分けた。牝馬だけのレースも含む。</p>"
         + table(["性別", "出走数", "勝利", "勝率", "複勝率"], rows_s)
         + f"<p>牝馬と牡馬がいっしょに走る重賞の成績は<a href='/column/year{G['year']}-hinba/'>{G['year']}年の重賞の牝馬の成績</a>に載せている。</p>")
    b = (f"<h3>年齢ごとの成績（{G['year']}年の重賞）</h3><p>{scope}を、年齢で分けた。2歳・3歳だけのレースも含む。</p>"
         + table(["年齢", "出走数", "勝利", "勝率", "複勝率"], rows_a))
    return (b + a if focus == "age" else a + b), ["G"]


def b_tennyu():
    a, b = S["tennyu"]
    if a.n < 50:
        return None
    return (f"<h3>中央から地方に来た馬の成績</h3><p>このサイトがAI予想を出した地方競馬のレース（{jd(S['first'])}から。ばんえいと重賞を除く）で、前走が中央競馬だった馬は{a.n:,}頭。"
            f"そのうち{a.w:,}頭が勝ち、勝率は{pc(a.wr())}、複勝率は{pc(a.r3())}だった。前走も地方だった馬（{b.n:,}頭）は、勝率{pc(b.wr())}、複勝率{pc(b.r3())}。</p>"
            "<p>中央から移ってきた最初のレースは、地方での記録が無いので力を比べにくい。このサイトのAIは、こうした近走の記録が足りない馬が多いレースを「見送り」にすることがある。</p>"), ["S"]


def b_kaisai():
    if not S["meet"]:
        return None
    last = max(d for d, _ in S["meet"])
    ms = sorted((v, m) for (d, v), m in S["meet"].items() if d == last)
    if not ms:
        return None
    v0, m0 = ms[0]
    mm = re.fullmatch(r"(\d+)回(.+?)(\d+)日", nf(m0))
    mean = f"「{m0}」は、その年の{mm.group(2)}競馬場の{mm.group(1)}回目の開催の{mm.group(3)}日目という意味になる。" if mm else ""
    return (f"<h3>実際の表記の例</h3><p>{jd(last)}の中央競馬は、" + "、".join(f"{v}が「{m}」" for v, m in ms) + f"だった。{mean}</p>"
            "<p>開催が進むと芝が傷んで、走りやすい場所が変わることがある。このサイトでは、その日の午前の結果から馬場の傾向を判定して、午後の予想に使っている。</p>"), ["S"]


def b_ana():
    wp = H["winpop"]
    n = sum(wp.values())
    if n < 500:
        return None
    six, ten = sum(v for k, v in wp.items() if k >= 6), sum(v for k, v in wp.items() if k >= 10)
    tan = H["pay"]["単勝"]
    big = sum(1 for y in tan if y >= 5000)
    t, at = H["top"]["単勝"]
    out = (f"<h3>人気の無い馬はどのくらい勝つか</h3><p>{h_scope()}で、勝ち馬が6番人気以下だったレースは{six:,}（{pc(100 * six / n)}）、10番人気以下だったレースは{ten:,}（{pc(100 * ten / n)}）。"
           f"単勝の払戻が5,000円以上（50倍以上）だったのは{big:,}レースで、いちばん高かったのは{_where(at)}の{man(t)}だった。</p>")
    src = ["H"]
    lw = G.get("lowwin")
    if lw:
        out += f"<p>{G['year']}年のJRAの重賞でいちばん人気が無くて勝ったのは、{_B.esc(lw[2])}の{_B.link_horse(lw[1])}（{lw[0]}番人気、単勝{yen(lw[3])}）。</p>"
        src.append("G")
    b = (S["sg"].get("pop_win") or {}).get("◎が7番人気以下（単勝1点）")
    if b and b.n >= 30:
        out += f"<p>このサイトのAIが7番人気以下の馬に◎を付けたのは{b.n:,}レースで、勝ったのは{b.hit:,}回（単勝の回収率{_B.roi_txt(b.stake, b.ret)}）。</p>"
        src.append("S")
    return out, src


def b_katai():
    v = H["pay"]["3連単"]
    if len(v) < 500:
        return None
    n = len(v)
    lo, hi = sum(1 for y in v if y < 10000), sum(1 for y in v if y >= 100000)
    rows = _cat_rows(H["field"], ("10頭以下", "11〜14頭", "15頭以上"))
    return (f"<h3>堅く決まるレースと荒れるレースの割合</h3><p>{h_scope()}で、3連単の払戻が1万円未満（堅い決着）だったのは{lo:,}レース（{pc(100 * lo / n)}）、"
            f"10万円以上（荒れた決着）だったのは{hi:,}レース（{pc(100 * hi / n)}）。1〜3着を1〜3番人気の3頭が占めたレースは{H['top3fav']:,}（{pc(100 * H['top3fav'] / H['n'])}）だった。</p>"
            + table(["出走頭数"] + CAT_HEAD[1:], rows)
            + ("<p>頭数が多いレースほど、1番人気が来る割合は下がり、払戻は大きくなっている。</p>"
               if H["field"]["10頭以下"].fav.r3() > H["field"]["11〜14頭"].fav.r3() > H["field"]["15頭以上"].fav.r3()
               and H["field"]["10頭以下"].med3() < H["field"]["11〜14頭"].med3() < H["field"]["15頭以上"].med3() else "")), ["H"]


def b_odds():
    w = H["winodds"]
    n = sum(w.values())
    if n < 500:
        return None
    rows = [[k, f"{w[k]:,}", pc(100 * w[k] / n)] for k in ("1倍台", "2.0〜4.9倍", "5.0〜9.9倍", "10.0〜29.9倍", "30倍以上")]
    return (f"<h3>勝った馬の単勝オッズ</h3><p>{h_scope()}の勝ち馬を、単勝のオッズ（払戻を100で割った数）で分けた。</p>"
            + table(["勝ち馬の単勝オッズ", "レース数", "割合"], rows)
            + f"<p>勝ち馬の{pc(100 * (w['1倍台'] + w['2.0〜4.9倍']) / n, 0)}は単勝5倍未満で、10倍以上の馬が勝ったレースは{pc(100 * (w['10.0〜29.9倍'] + w['30倍以上']) / n, 0)}あった。"
            "オッズは買った人の割合で決まる数字で、強さそのものではない。</p>"), ["H"]


def b_kaime():
    n = S["bet_races"]
    if n < 50:
        return None
    b = S["bets"]
    tot = sum(b.values())
    return (f"<h3>このサイトの買い目</h3><p>このサイトのAIは、{int(_B.RULE_FROM[4:6])}月{int(_B.RULE_FROM[6:8])}日からは1レースにつき◎の単勝か複勝の1点だけを買い目にしている"
            f"（◎が1〜2番人気なら複勝、3〜5番人気なら単勝、6番人気以下は買わない）。この期間に結果が出た{n:,}レースの買い目は合わせて{tot:,}点で、"
            + "、".join(f"{k}が{v:,}点" for k, v in b.most_common() if k) + "。</p>"
            "<p>それより前は3連複やワイドを組み合わせていたが、点数を増やしても回収率が上がらなかったので絞った。買い方ごとの成績は<a href='/strategy/'>買い方別の回収率</a>で比べられる。</p>"), ["S"]


def b_tekichu():
    g = S["sg"].get("hon") or {}
    t, f = g.get("◎の単勝だけ（1点）"), g.get("◎の複勝だけ（1点）")
    if not t or not f or t.n < 100:
        return None
    return (f"<h3>的中率と回収率は別のもの</h3><p>このサイトのAIの◎で比べる（{t.n:,}レース、{jd(S['first'])}から）。◎の単勝を100円ずつ買うと、的中率は{pc(100 * t.hit / t.n)}で回収率は{_B.roi_txt(t.stake, t.ret)}。"
            f"◎の複勝を100円ずつ買うと、的中率は{pc(100 * f.hit / f.n)}で回収率は{_B.roi_txt(f.stake, f.ret)}。</p>"
            f"<p>複勝は単勝の約{(f.hit / f.n) / max(1e-9, t.hit / t.n):.1f}倍当たる"
            + ("が、回収率はどちらも100%に届いていない。" if t.ret < t.stake and f.ret < f.stake else "。")
            + "当たる回数が多いことと、お金が増えることは別である。</p>"), ["S"]


def b_dg():
    v = sorted(S["dg"], key=lambda t: t[0])
    v = [t for t in v if not str(t[1].get("race_id", "")).startswith("jra")]
    if len(v) < 3:
        return None
    rows = []
    for d, p, g, win, hon, hf in v[-12:]:
        lab = _B.race_label(p)
        rows.append([f"{int(d[4:6])}月{int(d[6:8])}日", lab if re.search(r"Jpn|JPN|G\s*[123ⅠⅡⅢ]", nf(lab)) else f"{lab}（{g}）", win or "-",
                     (f"◎{_B.horse_name(p, hon)}は" + (f"{hf}着" if hf and hf < 99 else "着順なし")) if hon is not None else "見送り"])
    hit = sum(1 for *_, hon, hf in v if hf == 1)
    bet = sum(1 for *_, hon, hf in v if hon is not None)
    return (f"<h3>このサイトが予想したダートグレード競走</h3><p>地方の競馬場で行われた、G・Jpnの格が付く交流重賞のうち、このサイトがAI予想を出した{len(v)}レース（{jd(S['first'])}から）の勝ち馬と、AIの◎の着順。"
            f"◎を付けた{bet}レースで、◎が勝ったのは{hit}回だった。</p>" + table(["日付", "レース", "勝ち馬", "AIの◎"], rows)), ["S"]


def b_dq():
    if G.get("all_n", 0) < 500:
        return None
    dq = G["dq"]
    a, b = G["all_span"]
    out = (f"<h3>重賞で失格になった馬</h3><p>このサイトが集めたJRAの重賞の成績（{a}〜{b}年、{G['all_n']:,}レース）で、失格になった馬は{len(dq)}頭"
           + ("だった。" if not dq else "だけ：" + "、".join(f"{y}年の{_B.esc(nm)}の{_B.link_horse(h)}" + (f"（{p}番人気）" if p else "") for y, nm, h, p in dq) + "。") + "</p>"
           "<p>降着は、変更したあとの着順で成績が残るので、この記録からは数えられない。JRAでは2013年から、「妨害が無ければ被害を受けた馬が先にゴールできた」と認められた場合に降着とする決まりになっている。</p>")
    return out, ["GA"]


def b_tokubetsu():
    a, b = S["toku"]["特別競走"], S["toku"]["一般競走"]
    if a[0].n < 30 or b[0].n < 30:
        return None
    row = lambda k, x: [k, f"{x[0].n}", pc(x[0].fav.wr(), 0), pc(x[0].fav.r3(), 0), man(x[0].med3())]
    return (f"<h3>特別競走と一般競走の結果（中央競馬）</h3><p>このサイトがAI予想を出した中央競馬の{S['jra']:,}レース（{jd(S['first'])}から）を、レース名の付いた特別競走（重賞を含む）と、"
            "「3歳以上1勝クラス」のように条件の名前だけの一般競走に分けた。</p>" + table(["", "レース数", "1番人気の勝率", "1番人気の複勝率", "3連単の中央値"], [row("特別競走", a), row("一般競走", b)])
            + f"<p>特別競走{S['toku_late'][0]}レースのうち{S['toku_late'][1]}レースは、その日の9レース以降に行われた。</p>"), ["S"]


def b_netto():
    pd = S["perday"]
    if len(pd) < 14:
        return None
    v = sorted(pd.values())
    return (f"<h3>1日に行われるレースの数</h3><p>このサイトがAI予想を出したのは、{jd(S['first'])}からの{len(pd)}日間で{S['races']:,}レース（中央{S['jra']:,}・地方{S['nar']:,}）。"
            f"1日あたり平均{sum(v) / len(v):.0f}レースで、多い日は{v[-1]}レースあった。発走時刻は、いちばん早いレースで{int(S['post'][0][:2])}時{S['post'][0][3:]}分、"
            f"いちばん遅いレースで{int(S['post'][1][:2])}時{S['post'][1][3:]}分。</p>"
            "<p>中央競馬は土日と祝日の昼、地方競馬は平日と夜にも行われるので、ネット投票ならほぼ毎日、朝から夜まで買える。買いすぎを防ぐために、使う金額を先に決めておきたい。"
            "その日のレースとAI予想は<a href='/'>今日の予想</a>に並べている。</p>"), ["S"]


def b_nouse(what: str):
    a = (_B.MARK_STATS or {}).get("全体")
    extra_ = ""
    if a and a["horses"].get("◎", 0) >= 100:
        n = a["horses"]["◎"]
        w, s_, t = (a["fin"]["◎"][i] for i in (1, 2, 3))
        extra_ = f"それを見ないで付けた◎の成績は、{n:,}レースで勝率{pc(100 * w / n)}、複勝率{pc(100 * (w + s_ + t) / n)}（{jd(S['first'])}から）。"
    return (f"<h3>このサイトのAIは{what}を見ていない</h3><p>このサイトのAI予想が使っているのは、出馬表、各馬の近5走の内容、騎手と厩舎の成績、当日の馬体重とオッズ、"
            f"その日の午前の結果から判定した馬場の傾向である。{what}は、このサイトが集めている記録に入っていないので、予想には入っていない。{extra_}</p>"
            f"<p>{what}を自分で確かめる人は、その見立てをAIの印に足して考えると、このサイトに無い材料を補える。"
            "何を見て何を見ていないかは<a href='/about/'>予想の方法</a>と<a href='/limits/'>AI予想の限界</a>に書いている。</p>"), ["S"]


def b_example(kind: str):
    """実際のページの例（出馬表の見方・過去の結果の見方）。いちばん新しい、結果の出たJRAのG1のページへ。"""
    import weekly  # noqa: PLC0415
    best = None
    for slug, items in weekly.PREDS.items():
        for d, p, name, g in items:
            if g == "G1" and str(p.get("race_id", "")).startswith("jra") and (p.get("_result") or {}).get("rows") and (best is None or d > best[0]):
                best = (d, p, name, slug)
    if not best:
        return None
    d, p, name, slug = best
    path = _B.race_path(d, p)
    if kind == "card":
        return (f"<h3>実際のページで見る</h3><p>{jd(d)}の{_B.esc(name)}の<a href='{path}'>レースページ</a>には、枠番・馬番・馬名・騎手・オッズに、AIの評価点と印、1頭ずつの短評を並べている。"
                "出馬表の基本の項目に、予想の材料がどう重なるかを見られる。</p><p>これから行われる重賞の出走馬と枠順は、<a href='/weekend/'>今週末の競馬まとめ</a>から見られる。</p>"), ["S"]
    return (f"<h3>実際の結果で見る</h3><p>{jd(d)}の{_B.esc(name)}の<a href='{path}'>レースページ</a>には、着順・人気・払戻と、レース前にAIが付けた印と評価点を並べている。"
            f"レース前の見立てと結果を比べると、どこが合っていてどこが外れたかが分かる。</p><p>同じレースの過去20年の結果は<a href='/graded/{slug}/'>{_B.esc(name)}のページ</a>にまとめている。</p>"), ["S"]


# ---------- どの用語に、どの数字を出すか ----------
def _p(kind):
    return lambda: b_pay(kind)


STYLE_LEAD = {
    "kyakushitsu": "脚質のちがいは、最後のコーナーでの位置に表れる。", "nige": "逃げた馬は、4コーナーも先頭で回ることが多い。", "senko": "先行した馬は、4コーナーを2〜4番手あたりで回る。",
    "sashi": "差しの馬は、4コーナーを中団（5〜9番手あたり）で回る。", "oikomi": "追い込みの馬は、4コーナーを後方（10番手以下）で回る。",
    "makuri": "まくった馬は、3〜4コーナーで位置を上げて、4コーナーでは前のほうにいる。", "ichitori": "位置取りの結果は、最後のコーナーでの順位に表れる。",
    "tenkai": "展開の有利・不利は、どの位置にいた馬が勝ったかに表れる。", "pace": "ペースが速いと後ろの馬、遅いと前の馬に有利になりやすい。全体でならすと次のようになる。",
    "tsukajun": "通過順のうち、最後のコーナー（4コーナー）の順位で分けてみる。", "deokure": "出遅れると、後ろの位置からのレースになる。後ろにいた馬の成績は次のとおり。",
    "furi": "不利を受けやすいのは、馬群の中や後ろにいる馬である。位置ごとの成績は次のとおり。", "chokusen": "最後の直線に入るときの位置（4コーナーの順位）で分けてみる。",
}

BLOCKS: dict[str, list] = {
    # 馬券の種類と買い方
    "tansho": [_p("単勝"), b_fav], "fukusho": [_p("複勝"), b_fav], "wakuren": [_p("枠連")], "umaren": [_p("馬連")], "wide": [_p("ワイド")],
    "umatan": [_p("馬単")], "sanrenpuku": [_p("3連複")], "sanrentan": [_p("3連単")], "win5": [b_win5],
    "box": [lambda: b_sims(("wide3", "box3"), "ボックスで買い続けた場合", "ボックスは、選んだ馬の組み合わせを全部買う買い方。")],
    "formation": [lambda: b_sims(("form", "box3"), "フォーメーションで買い続けた場合", "フォーメーションは、着順ごとに馬を選んで組み合わせる買い方。")],
    "nagashi": [lambda: b_sims(("nagashi", "wide3"), "流しで買い続けた場合", "流しは、軸の馬を決めて、相手を何頭か選ぶ買い方。")],
    "multi": [lambda: b_sims(("multi", "form"), "マルチで買い続けた場合", "マルチは、軸の馬が1〜3着のどこに来てもよい形で買う買い方。")],
    "jiku": [b_pop, b_marks], "aite": [b_marks],
    # オッズ・払戻・成績
    "fukushoritsu": [b_pop, b_marks], "rentairitsu": [b_pop, b_marks], "shoritsu": [b_pop, b_marks], "ganpon": [b_ganpon], "haraimodoshi": [b_payall],
    "henkan": [b_stop], "kaime": [b_kaime], "kaishuritsu-gen": [b_ai_roi, b_fav], "kitaichi": [b_ai_value], "kojoritsu": [b_fav,
        lambda: b_sims(("wide3", "nagashi", "box3", "form", "multi"), "買い方を変えても100%には届かない", "")],
    "ninki": [b_pop, b_ai_pop], "odds": [b_odds, b_payall], "tekichuritsu": [b_tekichu, b_ai_roi],
    "ten": [lambda: b_sims(("wide3", "nagashi", "box3", "form", "multi"), "点数と的中率・回収率", "")], "tokubarai": [b_tokubarai],
    # 展開と脚質
    **{k: [(lambda k=k: b_pos(STYLE_LEAD[k]))] for k in STYLE_LEAD}, "agari": [b_agari], "chakusa": [b_margin], "hana": [b_margin],
    # コースと馬場
    "baba": [b_going], "omo-baba": [b_going], "banei": [b_banei],
    "course-gawari": [lambda: b_frame("コース替わりで内側の芝の状態が変わると、内の枠と外の枠の走りやすさも変わる。まず、全体をならした数字を見る。")], "dirt": [b_surface], "shiba": [b_surface],
    "jiba": [b_jranar], "kaisai": [b_kaisai], "kyori": [b_dist], "migimawari": [b_turn], "nighter": [b_night], "saka": [b_slope],
    "shogai": [b_jump], "uchiwaku": [b_frame],
    # レースの種類とクラス
    "barei-race": [b_wcond], "betsutei": [b_wcond], "teiryo": [b_wcond], "handicap": [b_wcond, b_kg], "chiho-class": [b_narclass],
    "class-jra": [b_class], "misho": [b_class], "shinba": [b_class], "open": [b_class], "tokubetsu": [b_tokubetsu, b_class], "listed": [b_class],
    "g1": [b_grade], "jushou": [b_grade], "jpn": [b_dg], "koryu": [b_dg], "sankan": [b_classic], "trial": [b_prior],
    # 馬・体調・血統
    "bataiju": [b_bw], "chichi": [b_sire], "ketto": [b_sire], "chokyo": [lambda: b_nouse("調教の内容")], "kaeshiuma": [lambda: b_nouse("返し馬の様子")],
    "paddock": [lambda: b_nouse("パドックでの様子")], "kinryo": [b_kg, b_wcond], "kyoso-ba": [lambda: b_sexage("age")], "seire": [lambda: b_sexage("sex")],
    "rento": [b_gap], "tataki": [b_gap], "yasumiake": [b_gap], "tennyu": [b_tennyu], "torikeshi": [b_stop], "kouchaku": [b_dq],
    # 人と予想
    "ai-yoso": [b_ai_roi, b_marks], "data-yoso": [b_pop, b_ai_roi], "ukeoi": [b_tekichu, b_ai_roi], "ana": [b_ana], "banushi": [b_owner],
    "chokyoshi": [b_trainer], "genryo": [b_genryo], "honmei": [b_marks, b_ai_pop], "shirushi-gen": [b_marks], "katai": [b_katai], "kishu": [b_jockey],
    "norikawari": [b_jchange], "netto": [b_netto], "kako-kekka": [lambda: b_example("result")], "shutsuba": [lambda: b_example("card")],
}

CSS = """
.gdat h3{margin:20px 0 6px}.gdat h3:first-of-type{margin-top:6px}.gdat table.gd{font-size:14px}.gdat table.gd td,.gdat table.gd th{white-space:nowrap}
.gdat table.gd td:first-child,.gdat table.gd th:first-child{white-space:normal;min-width:7em}
"""


def section(slug: str, term: str) -> tuple[str, str]:
    """用語のページに入れる「実際のレースの数字」の HTML と、その中身の文字（更新の判定用）。出せる数字が無ければ ("", "")。"""
    if _B is None:
        return "", ""
    parts, srcs = [], []
    for fn in BLOCKS.get(slug) or []:
        try:
            out = fn()
        except Exception as e:  # noqa: BLE001  数字が1つ作れなくても、用語のページは出す
            print("glossdata:", slug, repr(e))
            out = None
        if out:
            parts.append(out[0])
            srcs += [x for x in out[1] if x not in srcs]
    if not parts:
        return "", ""
    asof = _B.fmt_date(_B.TODAY)
    src = "／".join(SRC[k]() for k in srcs)
    html = (f"<section class='card gdat'><h2>実際のレースの数字で見る「{_B.esc(term)}」</h2>" + "".join(parts)
            + f"<p class='meta'>元にした記録：{src}。{asof}時点の集計で、サイトを更新するたびに数え直している。"
            "数字は過去の結果で、これからの的中や利益を約束するものではない。馬券は20歳から。</p></section>")
    return html, re.sub(r"<[^>]+>", "", "".join(parts))
