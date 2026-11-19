"""JRAの馬ページの全頭データ（data/horse_info。horse_info.py が集める）から、毛色・馬名の意味・セリのデータ記事を作る。AIは呼ばない。

対象は、集めたなかで3歳以上の馬のうち、出馬表を集めた期間（いちばん古い〜新しい出馬表の日）にJRAのレースを実際に走った馬
（取消・除外だけの馬は除く）。数が少ないとき（1,000頭未満）は作らない。
重賞の勝ちは data/graded_hist（JRAの重賞の全着順）から数え、馬ページの成績に同じ日の1着があるものだけを本人の勝ちとみなす
（昔の同名の馬と取り違えないため）。

  python horse_info_cols.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from common import DATA_DIR

ROOT = DATA_DIR.parent
COLS = ROOT / "columns"
JST = timezone(timedelta(hours=9))
FIRST_DATE = "2026-11-20"
SERIES = "umadata"
MIN_HORSES = 1000
COATS = ["鹿毛", "黒鹿毛", "青鹿毛", "青毛", "栗毛", "栃栗毛", "芦毛", "白毛"]
JRA = {"札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"}
# 11月20日時点で、JRAに所属する3歳以上の白毛の馬として確かめた馬（白毛の記事で紹介）。期間中に走っていない馬を文中で補う
KNOWN_WHITE = {"カルパ": "ソダシの弟", "ゴージャス": "ゴールドシップの子", "シュネーグロッケン": ""}
NONE = "取引市場の記録なし"


def ymd(s: str) -> str:
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s or "")
    return f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}" if m else ""


def jp(d: str) -> str:
    return f"{int(d[4:6])}月{int(d[6:8])}日"


def load() -> tuple[list[dict], str, str]:
    raw = []
    for f in sorted((DATA_DIR / "horse_info").glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        age = re.sub(r"\D", "", d.get("profile", {}).get("馬齢", ""))
        if age and int(age) >= 3 and d.get("last_card"):
            raw.append(d)
    if not raw:
        return [], "", ""
    a, b = min(h["last_card"] for h in raw), max(h["last_card"] for h in raw)
    ran = lambda r: r.get("venue") in JRA and a <= ymd(r.get("date", "")) <= b and ((r.get("finish") or "").isdigit() or r.get("finish") in ("中止", "失格"))
    return [h for h in raw if any(ran(r) for r in h.get("runs", []))], a, b


def jra_runs(h: dict) -> list[dict]:
    """JRAのレースで着順のついたものだけ（地方・海外のレース、取消・除外・中止は除く）。"""
    return [r for r in h.get("runs", []) if r.get("venue") in JRA and (r.get("finish") or "").isdigit()]


def rec(hs: list[dict]) -> dict:
    st = sum(len(jra_runs(h)) for h in hs)
    w = sum(sum(r["finish"] == "1" for r in jra_runs(h)) for h in hs)
    t3 = sum(sum(r["finish"] in ("1", "2", "3") for r in jra_runs(h)) for h in hs)
    return dict(n=len(hs), st=st, w=w, wr=100 * w / st if st else 0, r3=100 * t3 / st if st else 0)


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "―"


def graded_wins(hs: list[dict]) -> dict[str, list[tuple[str, str, str]]]:
    """馬名 → [(日付, レース名, 格)]：2016年以降のJRAの重賞（障害を含む）の1着。馬ページの成績に同じ日の1着がある馬だけ。"""
    try:
        import graded_cols as G
        all_ = G.load_all()
    except Exception:  # noqa: BLE001
        return {}
    wins = defaultdict(list)
    for y, rs in all_.items():
        if y < 2016:
            continue
        for r in rs:
            for x in r.get("rows") or []:
                if x.get("fin") == 1:
                    wins[x["name"]].append((r["date"], re.sub(r"^(?:新設)?重賞", "", r.get("abbr", "")).replace("(", "（").replace(")", "）"), r.get("grade", "")))
    out = {}
    for h in hs:
        mine = {ymd(r.get("date", "")) for r in h.get("runs", []) if r.get("finish") == "1"}
        v = sorted({w for w in wins.get(h["name"], []) if w[0] in mine})
        if v:
            out[h["name"]] = v
    return out


def g1n(v: list[tuple[str, str, str]]) -> int:
    return sum(g in ("G1", "J・G1") for _, _, g in v)


def main_wins(v: list[tuple[str, str, str]], k: int = 2) -> str:
    rank = {"G1": 0, "J・G1": 0, "G2": 1, "J・G2": 1, "G3": 2, "J・G3": 2}
    best = sorted(v, key=lambda w: (rank.get(w[2], 3), w[0]))[:k]
    return "、".join(f"{n}（{g}・{d[:4]}年）" for d, n, g in best)


def short_wins(v: list[tuple[str, str, str]]) -> str:
    best = main_wins(v, 1).split("（")[0]
    return f"{best}など重賞{len(v)}勝" if len(v) > 1 else f"重賞の{best}を勝った"


def caution(a: str, b: str, n: int, rate: bool) -> str:
    s = (f"> 対象は{jp(a)}〜{jp(b)}にJRAのレースを走った3歳以上の馬{n:,}頭で、JRAの競走馬情報を1頭ずつ確かめた。"
         "いま走っている馬だけを数えているので、引退した馬や2歳の馬は入っていない。")
    if rate:
        s += "勝率・3着内率は、これまでのJRAのレースだけで数えた（地方・海外のレースは除く）。重賞はJRAの重賞（障害を含む）。"
    return s


def sexage(h: dict) -> str:
    return f"{h['profile'].get('性別', '')}{h['profile'].get('馬齢', '').replace('歳', '')}"


# ---------- 毛色 ----------
def spread_txt(g: dict) -> str:
    """100頭以上いる毛色どうしの勝率の差を、数字に合わせて書く。"""
    big = {c: rec(v)["wr"] for c, v in g.items() if len(v) >= 100}
    if len(big) < 2:
        return ""
    hi, lo = max(big, key=big.get), min(big, key=big.get)
    d = big[hi] - big[lo]
    return (f"100頭以上いる毛色のなかで、JRAのレースの勝率がいちばん高いのは{hi}（{big[hi]:.1f}%）、いちばん低いのは{lo}（{big[lo]:.1f}%）で、"
            f"差は{d:.1f}ポイント。毛色は親から受け継ぐもので（芦毛の馬は、父か母が必ず芦毛）、毛色ごとに血統の顔ぶれが違う。"
            "この程度の差を、毛色そのものの差とはいえない。頭数の少ない毛色の数字は、1頭の成績で大きく動く。\n\n")


def keiro(hs: list[dict], a: str, b: str, gw: dict) -> tuple:
    g = defaultdict(list)
    for h in hs:
        g[h["profile"].get("毛色") or "不明"].append(h)
    n = len(hs)
    order = [c for c in COATS if g.get(c)] + [c for c in g if c not in COATS]
    missing = [c for c in COATS if not g.get(c)]
    t = "| 毛色 | 頭数 | 割合 | 勝率（JRAのレース） | 3着内率 | 重賞を勝った馬 |\n|---|---|---|---|---|---|\n"
    for c in order:
        v = rec(g[c])
        t += f"| {c} | {len(g[c]):,}頭 | {pct(len(g[c]), n)} | {v['wr']:.1f}% | {v['r3']:.1f}% | {sum(1 for h in g[c] if h['name'] in gw)}頭（{pct(sum(1 for h in g[c] if h['name'] in gw), len(g[c]))}） |\n"
    ranks = sorted(order, key=lambda c: -len(g[c]))
    rare = [c for c in ranks if len(g[c]) / n < 0.03]
    white = sorted(g.get("白毛", []), key=lambda h: h["name"])
    blue = sorted(g.get("青毛", []), key=lambda h: (-h["record"]["wins"], h["name"]))[:8]
    row = lambda h: (f"| {h['name']} | {sexage(h)} | {h['profile'].get('父', '')} × {h['profile'].get('母', '')} | "
                     f"{h['record']['starts']}戦{h['record']['wins']}勝 |\n")
    head = "| 馬名 | 性齢 | 父 × 母 | 戦績 |\n|---|---|---|---|\n"
    wt = (head + "".join(row(h) for h in white)) if white else "この期間に走った馬には、白毛の馬はいなかった。\n"
    other_white = [k for k in KNOWN_WHITE if k not in {h["name"] for h in white}]
    if other_white:
        wt += ("\n11月20日時点でJRAに所属する3歳以上の白毛の馬には、ほかに"
               + "、".join(f"{k}（{KNOWN_WHITE[k]}）" if KNOWN_WHITE[k] else k for k in other_white)
               + "がいる。この期間はレースに出ていないので、上の数には入っていない（[白毛の現役馬に一票を](/column/arima2026-oshi-shiroge/)）。\n")
    bt = (head + "".join(row(h) for h in blue)) if blue else ""
    top, second = ranks[0], ranks[1]
    nw = len(white)
    rare_txt = ""
    if rare:
        rare_txt = "割合が3%に満たない珍しい毛色は、" + "と".join(f"{c}（{len(g[c])}頭）" for c in rare) + "。"
    if missing:
        rare_txt += "、".join(missing) + "の馬は1頭もいなかった。"
    if "栃栗毛" in COATS and len(g.get("栃栗毛", [])) <= 3:
        rare_txt += ("栃栗毛はもともと少ない毛色で、2016年に生まれてJRAでデビューした4,694頭を数えた集計でも、栃栗毛は9頭だった"
                     "（[SPAIA](https://spaia.jp/column/horserace/8523)）。")
    white_lead = f"白毛は{nw}頭だけ" if nw else "白毛は1頭もいなかった"
    lead = (f"{jp(a)}〜{jp(b)}にJRAのレースを走った3歳以上の馬{n:,}頭の毛色を、JRAの競走馬情報で1頭ずつ数えた。"
            f"いちばん多いのは{top}で{pct(len(g[top]), n)}、次が{second}で{pct(len(g[second]), n)}。{white_lead}"
            + (f"で、{'・'.join(missing)}は1頭もいなかった。" if missing else "だった。"))
    title = f"競走馬の毛色の割合と種類｜JRAを走った{n:,}頭では{top}が{pct(len(g[top]), n)}、白毛は{nw}頭"
    desc = (f"競走馬の毛色は鹿毛・黒鹿毛・青鹿毛・青毛・栗毛・栃栗毛・芦毛・白毛の8種類。{jp(a)}〜{jp(b)}にJRAのレースを走った3歳以上の{n:,}頭の毛色を数え、"
            "割合と毛色ごとの勝率、白毛・青毛の馬の一覧をまとめた。")
    body = ("## 競走馬の毛色は8種類\n\nJRAに登録される競走馬（サラブレッド）の毛色は、鹿毛・黒鹿毛・青鹿毛・青毛・栗毛・栃栗毛・芦毛・白毛の8種類。"
            "毛色は、JRAの競走馬情報の各馬のページに載っている。\n\n"
            f"## 毛色ごとの頭数と割合\n\n{t}\n{rare_txt}\n\n"
            + spread_txt(g) +
            "## 毛色の見分け方\n\n"
            "- **鹿毛（かげ）**：茶色（赤みがかった褐色）の体に、たてがみ・尾・脚の先が黒\n"
            "- **黒鹿毛（くろかげ）**：鹿毛より黒みが強い。目のまわりやわきの下などは茶色\n"
            "- **青鹿毛（あおかげ）**：ほぼ全身が黒く、目や鼻のまわりがわずかに茶色\n"
            "- **青毛（あおげ）**：体もたてがみも黒\n"
            "- **栗毛（くりげ）**：体は黄色っぽい茶色。たてがみや尾は、体より濃い色から白っぽい色まである\n"
            "- **栃栗毛（とちくりげ）**：栗毛より黒みがかった茶色。ただし黒にはならない\n"
            "- **芦毛（あしげ）**：もとの毛色に白い毛がまざり、年をとるにつれて白くなっていく\n"
            "- **白毛（しろげ）**：生まれたときから体の大半が白い。芦毛とは別の毛色\n\n"
            f"## 白毛の馬（{nw}頭）\n\n{wt}\n"
            + (f"## 青毛の馬（勝ち数の多い順に{len(blue)}頭）\n\n{bt}\n" if bt else "")
            + caution(a, b, n, True) + "\n\n"
            "## あわせて読みたい\n\n- [白毛の現役馬に一票を（有馬記念ファン投票）](/column/arima2026-oshi-shiroge/)\n- [競走馬の名前の付け方と意味](/column/bamei-imi-data/)\n"
            "- [セリで買われた競走馬の成績](/column/seri-data/)\n\n"
            "## 出典\n\n- JRA「競走馬情報」の各馬のページ（毛色・戦績）\n- 毛色の説明：[JRAのサラブレッドの毛色の解説](https://www.jra.go.jp/kouza/thoroughbred/color/)\n"
            "- 重賞の成績：JRA「レース結果」（このサイトが集めたJRAの重賞の全着順）\n")
    return "keiro-wariai", 1, title, desc, lead, body


# ---------- 馬名の意味 ----------
ABBR_LANG = {"仏": "フランス語", "伊": "イタリア語", "独": "ドイツ語", "西": "スペイン語", "英": "英語", "羅": "ラテン語", "葡": "ポルトガル語",
             "蘭": "オランダ語", "露": "ロシア語", "希": "ギリシャ語", "中": "中国語", "韓": "韓国語"}
ALIAS = {"ハングル": "韓国語", "サンスクリット": "サンスクリット語", "広東語": "中国語", "中国語": "中国語", "韓国語": "韓国語", "英語": "英語"}


def langs(m: str) -> set[str]:
    out = set()
    for t in re.findall(r"[(（]([^()（）]{1,3})[)）]", m):
        t = t[:-1] if t.endswith("語") else t
        if t in ABBR_LANG:
            out.add(ABBR_LANG[t])
    out.update(re.findall(r"([ァ-ヴー]{2,}語)", m))
    out.update(v for k, v in ALIAS.items() if k in m)
    return out


def crowns(hs: list[dict]) -> tuple[dict, dict]:
    """冠名：意味が「冠名」で始まる馬を馬主ごとに分け、名前の頭2文字が同じ馬（2頭以上）の共通部分を冠名とみなす。馬主をまたぐ同じ冠名は合算。"""
    own = defaultdict(list)
    for h in hs:
        if re.match(r"\s*冠名", h["profile"].get("馬名意味", "")):
            own[h["profile"].get("馬主名", "")].append(h)
    out, by_owner = defaultdict(list), defaultdict(dict)
    for o, v in own.items():
        cl = defaultdict(list)
        for h in v:
            cl[h["name"][:2]].append(h)
        for xs in cl.values():
            p = os.path.commonprefix([h["name"] for h in xs])
            if len(xs) >= 2 and len(p) >= 2:
                out[p].extend(xs)
                by_owner[o][p] = xs
    return out, by_owner


def bamei(hs: list[dict], a: str, b: str, gw: dict) -> tuple:
    n = len(hs)
    means = [(h, h["profile"].get("馬名意味", "")) for h in hs if h["profile"].get("馬名意味")]
    crown = [h for h, m in means if "冠名" in m]
    owners = {h["profile"].get("馬主名", "") for h in crown}
    mom = [(h, m) for h, m in means if re.search(r"(?<!祖)母名|母の名", m)]
    dad = [(h, m) for h, m in means if re.search(r"(?<![母祖])父名|(?<!母の)父の名", m)]
    momdad = [(h, m) for h, m in means if re.search(r"母父|母の父", m)]
    lang = Counter()
    for h, m in means:
        lang.update(langs(m))
    cr, by_owner = crowns(hs)
    top_cr = sorted(((p, xs) for p, xs in cr.items() if len(xs) >= 5), key=lambda t: (-len(t[1]), t[0]))[:12]
    splits = []
    for o, d in by_owner.items():
        if len(d) != 2 or not re.search(r"\((株|有)\)", o):
            continue
        (p1, x1), (p2, x2) = d.items()
        fem = lambda xs: all(h["profile"].get("性別") == "牝" for h in xs)
        mal = lambda xs: all(h["profile"].get("性別") != "牝" for h in xs)
        if min(len(x1), len(x2)) >= 3 and ((fem(x1) and mal(x2)) or (fem(x2) and mal(x1))):
            f, m_ = (p1, p2) if fem(x1) else (p2, p1)
            splits.append((re.sub(r"\((株|有)\)", "", o), m_, f, len(x1) + len(x2)))
    ln = Counter(len(h["name"]) for h in hs)
    n9 = ln.get(9, 0)
    nine = sorted((h for h, m in means if len(h["name"]) == 9 and "冠名" not in m), key=lambda h: (-len(gw.get(h["name"], [])), hashlib.md5(h["name"].encode()).hexdigest()))[:6]
    short = sorted((h for h in hs if len(h["name"]) <= 2), key=lambda h: h["name"])[:10]
    famous = lambda xs: sorted(xs, key=lambda t: (-len(gw.get(t[0]["name"], [])), len(t[1]), t[0]["name"]))
    ex = lambda xs: "\n".join(f"- **{h['name']}**" + (f"（{short_wins(gw[h['name']])}）" if h["name"] in gw else "") + f"：{m}" for h, m in xs)
    t1 = "| 言語 | 頭数 |\n|---|---|\n" + "".join(f"| {k} | {v} |\n" for k, v in lang.most_common(12))
    t2 = "| 文字数 | 頭数 | 割合 |\n|---|---|---|\n" + "".join(f"| {k}文字 | {v:,} | {pct(v, n)} |\n" for k, v in sorted(ln.items()))
    t3 = ("| 冠名 | 頭数 | 例 |\n|---|---|---|\n"
          + "".join(f"| {p} | {len(xs)} | {'、'.join(sorted(h['name'] for h in xs)[:3])} |\n" for p, xs in top_cr))
    top_lang = lang.most_common(3)
    lead = (f"{jp(a)}〜{jp(b)}にJRAのレースを走った3歳以上の馬{n:,}頭の「馬名の意味」を、JRAの競走馬情報で調べた。"
            f"意味に「冠名」と書かれた馬は{len(crown):,}頭（{pct(len(crown), n)}）で、いちばん多い冠名は「{top_cr[0][0]}」の{len(top_cr[0][1])}頭。"
            f"上限の9文字の名前は{n9}頭（{pct(n9, n)}）あった。")
    title = f"競走馬の名前の付け方と意味｜JRAを走った{n:,}頭を調べたら冠名つきは{pct(len(crown), n)}、9文字は{pct(n9, n)}"
    desc = (f"競走馬の名前はどう付けられているのか。{jp(a)}〜{jp(b)}にJRAのレースを走った3歳以上の{n:,}頭の「馬名の意味」から、"
            "冠名の割合と多い冠名、父母の名前からの連想、使われる外国語、文字数を数えた。")
    split_txt = "".join(f"{o}の馬は、牡馬・せん馬が「{m_}」、牝馬が「{f}」で始まる（今回の{k}頭は、すべてこの分け方どおりだった）。"
                        for o, m_, f, k in splits)
    body = ("## 競走馬の名前のきまり\n\nJRAの競走馬の名前は、カタカナで2〜9文字。馬主が名前を決め、どんな意味かを添えて届け出る。"
            "いま登録されている馬と同じ名前や、G1を勝った馬などの名前は使えない。JRAの競走馬情報には、届け出た「馬名の意味」が載っている。\n\n"
            "## 冠名（かんめい）\n\n冠名は、同じ馬主の馬に共通して付ける言葉。「メイショウ」「サトノ」のように名前の頭に付けることが多い。"
            f"今回の{n:,}頭のうち、馬名の意味に「冠名」と書かれている馬は{len(crown):,}頭（{pct(len(crown), n)}）。"
            f"冠名を付けた馬の持ち主（馬主）は、個人と法人を合わせて{len(owners)}。\n\n"
            f"### 頭数の多い冠名\n\n意味が「冠名＋◯◯」の馬を馬主ごとに分け、名前の頭の共通部分を冠名として数えた（5頭以上）。\n\n{t3}\n"
            + (split_txt + "\n\n" if split_txt else "")
            + "## 父や母の名前から連想した名前\n\n"
            f"「母名より連想」のように、意味に母の名前が出てくる馬は{len(mom)}頭、父の名前は{len(dad)}頭、母の父の名前は{len(momdad)}頭。"
            "親の名前の一部を受け継いだり、親の名前から連想した言葉を付けたりする。\n\n"
            + (f"{ex(famous(mom)[:4])}\n\n" if mom else "")
            + "## 使われている外国語\n\n"
            "馬名の意味に「(仏)」「(伊)」や「ラテン語」のように言語名が書かれているものを数えた。"
            "英語の言葉には、ふつう言語名が書かれないので、この表にはほとんど出てこない。\n\n"
            f"{t1}\n"
            + (f"言語名が書かれたなかでは{top_lang[0][0]}がいちばん多く、{'、'.join(k for k, _ in top_lang[1:])}と続く。\n\n" if len(top_lang) >= 3 else "")
            + f"## 名前の文字数\n\n{t2}\n"
            f"上限の9文字の名前は{n9}頭（{pct(n9, n)}）。いちばん多いのは{max(ln, key=ln.get)}文字だった。\n\n"
            + (f"冠名を使っていない9文字の名前の例：{'、'.join(h['name'] for h in nine)}\n\n" if nine else "")
            + (f"2文字の名前と、その意味：\n\n" + "\n".join(f"- **{h['name']}**：{h['profile'].get('馬名意味', '')}" for h in short) + "\n\n" if short else "")
            + caution(a, b, n, False) + "\n\n"
            "## あわせて読みたい\n\n- [名前が面白い現役馬（有馬記念ファン投票）](/column/arima2026-oshi-namae/)\n- [競走馬の毛色の割合と種類](/column/keiro-wariai/)\n"
            "- [セリで買われた競走馬の成績](/column/seri-data/)\n\n## 出典\n\n- JRA「競走馬情報」の各馬のページ（馬名意味・馬主名）\n"
            "- 重賞の成績：JRA「レース結果」（このサイトが集めたJRAの重賞の全着順）\n")
    return "bamei-imi-data", 2, title, desc, lead, body


# ---------- セリ ----------
def market(h: dict) -> str:
    m = (h["profile"].get("取引市場") or "").strip()
    return re.sub(r"^\d{4}年\s*", "", m) if m else NONE


def sale_age(h: dict) -> int | None:
    t = re.match(r"(\d{4})", h["profile"].get("取引市場") or "")
    by = re.match(r"(\d{4})", h["profile"].get("生年月日") or "")
    return int(t.group(1)) - int(by.group(1)) if t and by else None


def foreign(h: dict) -> bool:
    s = h["profile"].get("産地", "")
    return bool(s) and not re.search(r"[町市村郡県道]|日高", s)


def seri(hs: list[dict], a: str, b: str, gw: dict) -> tuple:
    n = len(hs)
    g = defaultdict(list)
    for h in hs:
        g[market(h)].append(h)
    sold = [h for h in hs if market(h) != NONE]
    rows = sorted(((k, v) for k, v in g.items() if len(v) >= 15), key=lambda kv: -len(kv[1]))
    gwr = lambda v: sum(1 for h in v if h["name"] in gw)
    t = "| 取引された市場 | 頭数 | 割合 | 勝率（JRAのレース） | 3着内率 | 重賞を勝った馬 |\n|---|---|---|---|---|---|\n"
    for k, v in rows:
        r = rec(v)
        t += f"| {k} | {len(v):,}頭 | {pct(len(v), n)} | {r['wr']:.1f}% | {r['r3']:.1f}% | {gwr(v)}頭（{pct(gwr(v), len(v))}） |\n"
    sel, none = g.get("セレクトセール", []), g.get(NONE, [])
    sr, nr = rec(sel), rec(none)
    ages = Counter(sale_age(h) for h in sel)
    fr = [h for h in hs if foreign(h)]
    fr_none = sum(1 for h in fr if market(h) == NONE)
    winners = sorted((h for h in sel if h["name"] in gw), key=lambda h: (-g1n(gw[h["name"]]), -len(gw[h["name"]]), h["name"]))
    when = lambda h: {0: "当歳", 1: "1歳", 2: "2歳"}.get(sale_age(h), "")
    wt = ("| 馬名 | 性齢 | 取引 | JRAの重賞の勝ち | 主な勝ち |\n|---|---|---|---|---|\n"
          + "".join(f"| {h['name']} | {sexage(h)} | {h['profile'].get('取引市場', '')[:5]}（{when(h)}） | {len(gw[h['name']])}勝 | {main_wins(gw[h['name']])} |\n"
                    for h in winners[:12])) if winners else ""
    big = [(k, v) for k, v in rows if len(v) >= 50 and k != NONE]
    best_k, best_v = max(big, key=lambda kv: gwr(kv[1]) / len(kv[1])) if big else ("", [])
    best_txt = (f"50頭以上いる市場で、重賞を勝った馬の割合がいちばん高いのは{best_k}（{len(best_v)}頭のうち{gwr(best_v)}頭、{pct(gwr(best_v), len(best_v))}）。"
                if best_k and best_k != "セレクトセール" else "")
    lead = (f"{jp(a)}〜{jp(b)}にJRAのレースを走った3歳以上の馬{n:,}頭のうち、JRAの記録でセリ（市場）で取引されたことが分かるのは{len(sold):,}頭（{pct(len(sold), n)}）。"
            f"セレクトセール出身は{len(sel)}頭で、重賞を勝ったことがある馬は{gwr(sel)}頭（{pct(gwr(sel), len(sel))}）。"
            f"取引市場の記録がない馬では{pct(gwr(none), len(none))}だった。")
    title = f"セリで買われた競走馬の成績｜セレクトセール出身{len(sel)}頭のうち重賞勝ちは{gwr(sel)}頭、市場ごとの勝率を比較"
    desc = (f"{jp(a)}〜{jp(b)}にJRAのレースを走った3歳以上の{n:,}頭を、取引された市場（セレクトセール、北海道サマーセールなど）で分けて、"
            "勝率・3着内率と重賞を勝った馬の割合を比べた。セレクトセール出身の重賞勝ち馬の一覧つき。")
    body = ("## セリ（市場取引）とは\n\n競走馬の多くは、牧場から馬主に売られる。売り方には、セリ（市場）で値段を競り合う方法と、"
            "セリを通さずに牧場と馬主が直接取引する方法（庭先取引）がある。馬主が自分の牧場で生産した馬もいる。"
            "JRAの競走馬情報には、セリで取引された馬の「取引市場」が書かれている。書かれていない馬は、この記事では「取引市場の記録なし」とした。\n\n"
            f"## 市場ごとの成績\n\n15頭以上いる市場だけを並べた。\n\n{t}\n"
            f"セレクトセール出身の馬は、勝率が{sr['wr']:.1f}%、重賞を勝ったことがある馬が{pct(gwr(sel), len(sel))}。"
            f"取引市場の記録がない馬は、勝率{nr['wr']:.1f}%、重賞を勝った馬は{pct(gwr(none), len(none))}だった。"
            + best_txt + "\n\n"
            "ただし、この表はいま走っている馬だけの数字。市場ごとに馬の年齢や走っているクラスが違ううえ、"
            "記録がない馬には、セリを通らずに取引された馬や、馬主が自分の牧場で生産した馬"
            + (f"、海外で生まれた馬（今回の{len(fr)}頭のうち{fr_none}頭は記録なし）" if fr else "")
            + "などがまとめて入っている。数字の差が、そのまま市場の差というわけではない。\n\n"
            + (f"## セレクトセールの「当歳」と「1歳」\n\nセレクトセールでは、1歳の馬と、その年に生まれた子馬（当歳）が取引される。"
               f"今回のセレクトセール出身{len(sel)}頭のうち、1歳で取引されたのは{ages.get(1, 0)}頭、生まれた年（当歳）に取引されたのは{ages.get(0, 0)}頭だった。\n\n"
               if sel else "")
            + (f"## セレクトセール出身の重賞勝ち馬（{len(winners)}頭）\n\n重賞の勝ちが多い順（G1の勝ちがある馬を先に）に並べた。\n\n{wt}\n" if wt else "")
            + caution(a, b, n, True) + "\n\n"
            "## あわせて読みたい\n\n- [POGで人気だった3歳馬のいま](/column/arima2026-oshi-pog/)\n- [競走馬の毛色の割合と種類](/column/keiro-wariai/)\n"
            "- [競走馬の名前の付け方と意味](/column/bamei-imi-data/)\n\n## 出典\n\n- JRA「競走馬情報」の各馬のページ（取引市場・生年月日・産地・戦績）\n"
            "- 重賞の成績：JRA「レース結果」（このサイトが集めたJRAの重賞の全着順）\n")
    return "seri-data", 3, title, desc, lead, body


def write(slug: str, order: int, title: str, desc: str, lead: str, body: str, today: str) -> bool:
    p = COLS / f"{slug}.md"
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
    hs, a, b = load()
    if len(hs) < MIN_HORSES:
        print("まだ馬が少ない", len(hs))
        return
    gw = graded_wins(hs)
    today = datetime.now(JST).strftime("%Y-%m-%d")
    n = 0
    for slug, order, title, desc, lead, body in (keiro(hs, a, b, gw), bamei(hs, a, b, gw), seri(hs, a, b, gw)):
        if write(slug, order, title, desc, lead, body, today):
            n += 1
            print("wrote", slug)
    print("記事:", n, "対象", len(hs), "重賞勝ち", len(gw))


if __name__ == "__main__":
    main()
