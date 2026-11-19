"""JRAの馬ページの全頭データ（data/horse_info。horse_info.py が集める）から、毛色・馬名の意味・セリのデータ記事を作る。AIは呼ばない。

対象は、集めたなかで3歳以上の馬（直近の出馬表に載った、JRAの現役の馬）。数が少ないとき（1,000頭未満）は作らない。

  python horse_info_cols.py
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from common import DATA_DIR

ROOT = DATA_DIR.parent
COLS = ROOT / "columns"
JST = timezone(timedelta(hours=9))
FIRST_DATE = "2026-11-20"
MIN_HORSES = 1000
COATS = ["鹿毛", "黒鹿毛", "青鹿毛", "青毛", "栗毛", "栃栗毛", "芦毛", "白毛"]


def load() -> list[dict]:
    out = []
    for f in sorted((DATA_DIR / "horse_info").glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        age = re.sub(r"\D", "", d.get("profile", {}).get("馬齢", ""))
        if age and int(age) >= 3:
            out.append(d)
    return out


def span(hs: list[dict]) -> tuple[str, str]:
    ds = sorted(h.get("last_card", "") for h in hs if h.get("last_card"))
    f = lambda d: f"{int(d[4:6])}月{int(d[6:8])}日"
    return f(ds[0]), f(ds[-1])


def jra_runs(h: dict) -> list[dict]:
    """JRAのレースだけ（地方から移ってきた馬の地方のレースは除く）。「JRAへ転入」などの行も除く。"""
    jra = {"札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"}
    return [r for r in h.get("runs", []) if r.get("venue") in jra and (r.get("finish") or "").isdigit()]


def rec(hs: list[dict]) -> dict:
    st = sum(len(jra_runs(h)) for h in hs)
    w = sum(sum(r["finish"] == "1" for r in jra_runs(h)) for h in hs)
    t3 = sum(sum(r["finish"] in ("1", "2", "3") for r in jra_runs(h)) for h in hs)
    return dict(n=len(hs), st=st, w=w, wr=100 * w / st if st else 0, r3=100 * t3 / st if st else 0)


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "―"


CAUTION = ("> 対象は{a}〜{b}にJRAのレースに出走した3歳以上の馬（JRAの競走馬情報で確かめた{n:,}頭）。いま走っている馬だけを数えているので、"
           "引退した馬や、まだデビューしていない馬は入っていない。勝率は、JRAのレースだけを数えた（地方・海外のレースは除く）。")


# ---------- 毛色 ----------
def spread_txt(g: dict) -> str:
    """100頭以上いる毛色どうしの勝率の差を、数字に合わせて書く。"""
    big = {c: rec(v)["wr"] for c, v in g.items() if len(v) >= 100}
    if len(big) < 2:
        return ""
    hi, lo = max(big, key=big.get), min(big, key=big.get)
    d = big[hi] - big[lo]
    head = (f"100頭以上いる毛色のなかで、JRAのレースの勝率がいちばん高いのは{hi}（{big[hi]:.1f}%）、いちばん低いのは{lo}（{big[lo]:.1f}%）で、"
            f"差は{d:.1f}ポイント。")
    tail = ("毛色によって走る力が変わるとは考えられておらず、差は、どんな種牡馬の子が多いかといった偏りによるところが大きい。\n\n"
            if d < 3 else "毛色そのものが走る力を変えるとは考えられておらず、この差は、毛色ごとに多い種牡馬（父）の違いなどが表れたものと見られる。\n\n")
    return head + tail


def keiro(hs: list[dict]) -> tuple:
    a, b = span(hs)
    g = defaultdict(list)
    for h in hs:
        g[h["profile"].get("毛色") or "不明"].append(h)
    n = len(hs)
    order = [c for c in COATS if g.get(c)] + [c for c in g if c not in COATS]
    t = "| 毛色 | 頭数 | 割合 | 勝率（JRAのレース） | 3着内率 |\n|---|---|---|---|---|\n"
    for c in order:
        v = rec(g[c])
        t += f"| {c} | {len(g[c]):,}頭 | {pct(len(g[c]), n)} | {v['wr']:.1f}% | {v['r3']:.1f}% |\n"
    ranks = sorted(order, key=lambda c: -len(g[c]))
    rare = [c for c in ranks if len(g[c]) / n < 0.03]
    white = sorted(g.get("白毛", []), key=lambda h: h["name"])
    blue = sorted(g.get("青毛", []), key=lambda h: -h["record"]["wins"])[:8]
    wt = ("| 馬名 | 性齢 | 父 × 母 | 戦績 |\n|---|---|---|---|\n"
          + "".join(f"| {h['name']} | {h['profile'].get('性別', '')}{h['profile'].get('馬齢', '').replace('歳', '')} | {h['profile'].get('父', '')} × {h['profile'].get('母', '')} | "
                    f"{h['record']['starts']}戦{h['record']['wins']}勝 |\n" for h in white)) if white else "いまは該当する馬がいない。\n"
    bt = ("| 馬名 | 性齢 | 父 × 母 | 戦績 |\n|---|---|---|---|\n"
          + "".join(f"| {h['name']} | {h['profile'].get('性別', '')}{h['profile'].get('馬齢', '').replace('歳', '')} | {h['profile'].get('父', '')} × {h['profile'].get('母', '')} | "
                    f"{h['record']['starts']}戦{h['record']['wins']}勝 |\n" for h in blue)) if blue else ""
    top = ranks[0]
    lead = (f"{a}〜{b}にJRAのレースを走った3歳以上の馬{n:,}頭の毛色を、JRAの競走馬情報で数えた。いちばん多いのは{top}で{pct(len(g[top]), n)}。"
            f"白毛は{len(white)}頭（{pct(len(white), n)}）、青毛は{len(g.get('青毛', []))}頭（{pct(len(g.get('青毛', [])), n)}）しかいない。")
    title = f"競走馬の毛色の割合と種類｜JRAの現役馬{n:,}頭を数えたら白毛は{len(white)}頭、いちばん多いのは{top}"
    desc = (f"競走馬の毛色（鹿毛・黒鹿毛・青鹿毛・青毛・栗毛・栃栗毛・芦毛・白毛）の割合を、JRAの現役馬{n:,}頭の競走馬情報から数えた。"
            f"白毛は{len(white)}頭、青毛は{len(g.get('青毛', []))}頭。毛色ごとの勝率と、珍しい毛色の馬の一覧つき。")
    body = (f"## 毛色ごとの頭数と割合\n\n{t}\n"
            f"割合が3%に満たない珍しい毛色は、{'、'.join(rare)}。\n\n"
            + spread_txt(g) +
            "## 毛色の見分け方\n\n- **鹿毛（かげ）**：茶色の体に、たてがみ・尾・脚の先が黒\n- **黒鹿毛（くろかげ）・青鹿毛（あおかげ）**：鹿毛より黒っぽい。青鹿毛のほうが黒に近い\n"
            "- **青毛（あおげ）**：全身がほぼ真っ黒\n- **栗毛（くりげ）**：体もたてがみも赤茶色\n- **栃栗毛（とちくりげ）**：栗毛のなかでも濃い色\n"
            "- **芦毛（あしげ）**：生まれたときは黒っぽく、年をとるにつれて白くなっていく\n- **白毛（しろげ）**：生まれたときから白い\n\n"
            f"## 白毛の馬（{len(white)}頭）\n\n{wt}\n"
            + (f"## 青毛の馬（勝ち数の多い順に{len(blue)}頭）\n\n{bt}\n" if bt else "")
            + CAUTION.format(a=a, b=b, n=n) + "\n\n"
            "## あわせて読みたい\n\n- [白毛の現役馬に一票を（有馬記念ファン投票）](/column/arima2026-oshi-shiroge/)\n- [競走馬の名前の意味と冠名](/column/bamei-imi-data/)\n"
            "- [セリで買われた馬の成績](/column/seri-data/)\n\n## 出典\n\n- JRA「競走馬情報」の各馬のページ（毛色・戦績）\n")
    return "keiro-wariai", 1, title, desc, lead, body


# ---------- 馬名の意味 ----------
LANG = [("伊", "イタリア語"), ("仏", "フランス語"), ("西", "スペイン語"), ("独", "ドイツ語"), ("英", "英語"), ("羅", "ラテン語"), ("ラテン語", "ラテン語"),
        ("ハワイ語", "ハワイ語"), ("葡", "ポルトガル語"), ("ポルトガル語", "ポルトガル語"), ("蘭", "オランダ語"), ("オランダ語", "オランダ語"),
        ("露", "ロシア語"), ("ギリシャ語", "ギリシャ語"), ("希", "ギリシャ語"), ("アイヌ語", "アイヌ語"), ("中", "中国語"), ("韓", "韓国語"), ("アラビア語", "アラビア語")]


def bamei(hs: list[dict]) -> tuple:
    a, b = span(hs)
    n = len(hs)
    means = [(h, h["profile"].get("馬名意味", "")) for h in hs if h["profile"].get("馬名意味")]
    crown = [h for h, m in means if "冠名" in m]
    mom = [h for h, m in means if "母名" in m]
    dad = [h for h, m in means if "父名" in m]
    lang = Counter()
    for h, m in means:
        hit = set()
        for k, v in LANG:
            if re.search(r"[(（]" + re.escape(k) + r"[)）]", m) or (len(k) > 2 and k in m):
                hit.add(v)
        lang.update(hit)
    ln = Counter(len(h["name"]) for h in hs)
    longest = sorted((h for h in hs if len(h["name"]) == 9), key=lambda h: h["name"])[:6]
    shortest = sorted((h for h in hs if len(h["name"]) <= 2), key=lambda h: h["name"])[:10]
    # 冠名の多い馬主：「冠名+」で始まる意味の馬を、名前の頭の共通部分で数える
    pref = Counter()
    for h, m in means:
        if m.startswith("冠名"):
            for k in range(2, 6):
                pref[h["name"][:k]] += 1
    top_crowns = []
    for p, c in pref.most_common(80):
        if c >= 8 and not any(p != q and p.startswith(q) and pref[q] <= c + 1 for q, _ in top_crowns):
            top_crowns = [(q, cq) for q, cq in top_crowns if not (q.startswith(p) and cq <= c + 1)]
            top_crowns.append((p, c))
    top_crowns = sorted(top_crowns, key=lambda t: -t[1])[:12]
    t1 = ("| 言語 | 頭数 |\n|---|---|\n" + "".join(f"| {k} | {v} |\n" for k, v in lang.most_common(10)))
    t2 = ("| 文字数 | 頭数 | 割合 |\n|---|---|---|\n" + "".join(f"| {k}文字 | {v} | {pct(v, n)} |\n" for k, v in sorted(ln.items())))
    t3 = ("| 冠名（名前の頭） | 頭数 | 例 |\n|---|---|---|\n"
          + "".join(f"| {p} | {c} | {'、'.join(sorted({h['name'] for h, m in means if h['name'].startswith(p) and m.startswith('冠名')})[:3])} |\n" for p, c in top_crowns))
    ex = lambda hs_: "、".join(f"{h['name']}（{h['profile'].get('馬名意味', '')}）" for h in hs_)
    lead = (f"{a}〜{b}にJRAのレースを走った3歳以上の馬{n:,}頭の「馬名の意味」を、JRAの競走馬情報で調べた。"
            f"意味に「冠名」が入る馬は{len(crown):,}頭（{pct(len(crown), n)}）、母の名前から連想した馬は{len(mom)}頭、父の名前からは{len(dad)}頭。"
            + (f"外国語でいちばん多いのは{lang.most_common(1)[0][0]}（{lang.most_common(1)[0][1]}頭）。" if lang else ""))
    title = f"競走馬の名前の意味と付け方｜JRAの現役馬{n:,}頭を調べたら冠名は{pct(len(crown), n)}、外国語は{lang.most_common(1)[0][0] if lang else ''}が最多"
    desc = (f"競走馬の名前はどう付けられているのか。JRAの現役馬{n:,}頭の「馬名の意味」から、冠名の割合、多い冠名、父母の名前からの連想、使われる外国語、文字数を数えた。")
    body = ("## 競走馬の名前のきまり\n\nJRAの競走馬の名前は、カタカナで2〜9文字。馬主が名前を決め、意味と一緒に届け出る。"
            "同じ名前は使えず、有名なG1馬の名前などは、ほかの馬に付けられない。\n\n"
            f"## 冠名（かんめい）\n\n冠名は、同じ馬主の馬に共通して付ける言葉。「メイショウ」「サトノ」のように名前の頭に付けることが多い。"
            f"今回調べた{n:,}頭のうち、馬名の意味に「冠名」と書かれている馬は{len(crown):,}頭（{pct(len(crown), n)}）だった。\n\n"
            f"### 頭数の多い冠名\n\n「冠名＋◯◯」と届け出た馬を、名前の頭の文字で数えた（8頭以上）。\n\n{t3}\n"
            f"## 父や母の名前から連想した名前\n\n馬名の意味に「母名より」などと書かれている馬は{len(mom)}頭、「父名より」は{len(dad)}頭。"
            "親の名前の一部を受け継いだり、親の名前から連想した言葉を付けたりする。\n\n"
            + (f"例：{ex(mom[:3])}\n\n" if mom else "")
            + f"## 使われている外国語\n\n馬名の意味に「(伊)」「(仏)」のように言語が書かれているものを数えた。\n\n{t1}\n"
            f"## 名前の文字数\n\n{t2}\n"
            + (f"9文字の名前の例：{'、'.join(h['name'] for h in longest)}\n\n" if longest else "")
            + (f"2文字の名前の例：{'、'.join(h['name'] for h in shortest)}\n\n" if shortest else "")
            + CAUTION.format(a=a, b=b, n=n) + "\n\n"
            "## あわせて読みたい\n\n- [名前が面白い現役馬（有馬記念ファン投票）](/column/arima2026-oshi-namae/)\n- [競走馬の毛色の割合](/column/keiro-wariai/)\n"
            "- [セリで買われた馬の成績](/column/seri-data/)\n\n## 出典\n\n- JRA「競走馬情報」の各馬のページ（馬名意味）\n")
    return "bamei-imi-data", 2, title, desc, lead, body


# ---------- セリ ----------
def seri(hs: list[dict]) -> tuple:
    a, b = span(hs)
    n = len(hs)
    g = defaultdict(list)
    for h in hs:
        m = (h["profile"].get("取引市場") or "").strip()
        k = re.sub(r"^\d{4}年\s*", "", m) if m else "セリを通っていない（記録なし）"
        g[k].append(h)
    sold = [h for k, v in g.items() if k != "セリを通っていない（記録なし）" for h in v]
    rows = sorted(((k, v) for k, v in g.items() if len(v) >= 15), key=lambda kv: -len(kv[1]))
    t = "| 取引された市場 | 頭数 | 割合 | 勝率（JRAのレース） | 3着内率 | 1頭あたりの勝ち数 |\n|---|---|---|---|---|---|\n"
    for k, v in rows:
        r = rec(v)
        t += f"| {k} | {len(v):,}頭 | {pct(len(v), n)} | {r['wr']:.1f}% | {r['r3']:.1f}% | {r['w'] / max(1, r['n']):.2f} |\n"
    sel = g.get("セレクトセール", [])
    sr, nr = rec(sel), rec(g.get("セリを通っていない（記録なし）", []))
    best = sorted((h for h in sel), key=lambda h: -sum(r["finish"] == "1" for r in jra_runs(h)))[:8]
    bt = ("| 馬名 | 性齢 | 取引 | JRAの勝ち |\n|---|---|---|---|\n"
          + "".join(f"| {h['name']} | {h['profile'].get('性別', '')}{h['profile'].get('馬齢', '').replace('歳', '')} | {h['profile'].get('取引市場', '')} | "
                    f"{sum(r['finish'] == '1' for r in jra_runs(h))}勝 |\n" for h in best)) if best else ""
    lead = (f"{a}〜{b}にJRAのレースを走った3歳以上の馬{n:,}頭のうち、JRAの記録でセリ（市場）で取引されたことが分かるのは{len(sold):,}頭（{pct(len(sold), n)}）。"
            + (f"日本でいちばん大きいセリのセレクトセール出身は{len(sel)}頭で、JRAのレースの勝率は{sr['wr']:.1f}%。セリの記録がない馬は{nr['wr']:.1f}%。" if sel else ""))
    title = f"セリで買われた競走馬の成績｜セレクトセール出身馬の勝率は{sr['wr']:.1f}%（JRAの現役馬{n:,}頭で比較）"
    desc = (f"JRAの現役馬{n:,}頭を、取引された市場（セレクトセール、北海道サマーセールなど）で分けて、JRAのレースの勝率を比べた。"
            "セリを通らずに馬主に渡る馬（庭先取引・自家生産など）との比較つき。")
    body = ("## セリ（市場取引）とは\n\n競走馬の多くは、牧場から馬主に売られる。売り方には、セリ（市場）で値段を競り合う方法と、"
            "セリを通さずに牧場と馬主が直接取引する方法（庭先取引）がある。馬主が自分の牧場で生産した馬もいる。"
            "JRAの競走馬情報には、セリで取引された馬だけ「取引市場」が書かれている。\n\n"
            f"## 市場ごとの成績\n\n15頭以上いる市場だけを並べた。\n\n{t}\n"
            "セレクトセールは、良い血統の馬が高い値段で取引されることの多い市場。勝率の差は、血統や育成の差に加えて、"
            "成績の良い馬ほど長く走り続けて今回の数に入りやすい、といった偏りも含んでいる。\n\n"
            + (f"## セレクトセール出身で勝ち数の多い馬\n\n{bt}\n" if bt else "")
            + CAUTION.format(a=a, b=b, n=n) + "\n\n"
            "## あわせて読みたい\n\n- [POGで人気だった3歳馬のいま](/column/arima2026-oshi-pog/)\n- [競走馬の毛色の割合](/column/keiro-wariai/)\n"
            "- [競走馬の名前の意味と冠名](/column/bamei-imi-data/)\n\n## 出典\n\n- JRA「競走馬情報」の各馬のページ（取引市場・戦績）\n")
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
    meta.update({"draft": "false", "order": order, "hero": "g-turf-autumn"})
    head = "\n".join(f"{k}: {str(v).replace(chr(10), ' ')}" for k, v in meta.items())
    p.write_text(f"---\n{head}\n---\n{body}", encoding="utf-8")
    return True


def main() -> None:
    hs = load()
    if len(hs) < MIN_HORSES:
        print("まだ馬が少ない", len(hs))
        return
    today = datetime.now(JST).strftime("%Y-%m-%d")
    n = 0
    for slug, order, title, desc, lead, body in (keiro(hs), bamei(hs), seri(hs)):
        if write(slug, order, title, desc, lead, body, today):
            n += 1
            print("wrote", slug)
    print("記事:", n)


if __name__ == "__main__":
    main()
