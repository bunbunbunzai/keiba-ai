"""有馬記念ファン投票に合わせた「馬の紹介」記事を、JRA重賞の成績データ（data/graded_hist）から作る。

  python3 scraper/vote_cols.py          # columns/arima2026-vote-*.md を書き直す

数字はすべて graded_hist（JRA公式の成績ページを集めたもの）から数える。海外・地方のレースと、重賞でないレースは入っていない。
ジャパンカップなど新しい結果が入ったあとに実行し直せば、成績が新しくなる。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
YEAR = 2026
TODAY = "2026-11-19"
# 2025年のファン投票 最終結果の上位20頭（JRA発表）
VOTE_2025 = [("レガレイラ", 612771), ("クロワデュノール", 566330), ("マスカレードボール", 424952), ("メイショウタバル", 415575),
             ("ベラジオオペラ", 409745), ("ジャスティンパレス", 371556), ("ミュージアムマイル", 340383), ("ダノンデサイル", 334627),
             ("エネルジコ", 259097), ("ヘデントール", 256914), ("カムニャック", 221612), ("ジャンタルマンタル", 203121),
             ("エンブロイダリー", 200954), ("アーバンシック", 169916), ("ソールオリエンス", 139417), ("ブローザホーン", 118160),
             ("アスコリピチェーノ", 117249), ("サトノレーヴ", 107466), ("チェルヴィニア", 103058), ("パンジャタワー", 79683)]
VOTE_RANK = {n: i for i, (n, _) in enumerate(VOTE_2025, 1)}


def load():
    runs = defaultdict(list)  # 馬名 → [出走1回分]（古い順）
    for y in range(2020, YEAR + 1):
        f = ROOT / "data" / "graded_hist" / f"{y}.json"
        if not f.exists():
            continue
        for r in json.loads(f.read_text(encoding="utf-8"))["races"]:
            if r["grade"].startswith("J") or not r.get("rows"):
                continue
            for x in r["rows"]:
                runs[x["name"]].append({**x, "date": r["date"], "race": r["abbr"], "grade": r["grade"], "venue": r["venue"],
                                        "surface": r["surface"], "dist": r["distance"], "field": len(r["rows"])})
    for v in runs.values():
        v.sort(key=lambda a: a["date"])
    return runs


RUNS = load()
ran = lambda a: isinstance(a["fin"], int)
md = lambda d: f"{int(d[4:6])}月{int(d[6:])}日"
race_nm = lambda s: s.replace("(", "（").replace(")", "）")


def fin(a) -> str:
    return f"{a['fin']}着" if ran(a) else str(a["fin"])


def tally(rs) -> str:
    rs = [a for a in rs if ran(a)]
    if not rs:
        return "出走なし"
    w = sum(a["fin"] == 1 for a in rs)
    t3 = sum(a["fin"] <= 3 for a in rs)
    return f"{len(rs)}戦{w}勝・3着以内{t3}回"


def horse_link(name: str) -> str:
    hid = hashlib.md5(name.encode()).hexdigest()[:10]
    return f"[{name}](/horse/{hid}/)" if (ROOT / "_site" / "horse" / hid / "index.html").exists() else name


def now(name):
    """今年の最後の出走から、性別・年齢・厩舎。"""
    a = [x for x in RUNS[name] if x["date"].startswith(str(YEAR))][-1]
    return a["sex"], a["age"], a["trainer"]


def this_year(name):
    return [a for a in RUNS[name] if a["date"].startswith(str(YEAR))]


def block(name: str, table: bool = True) -> str:
    rs = RUNS[name]
    ty = this_year(name)
    sex, age, tr = now(name)
    g1 = [a for a in rs if a["grade"] == "G1" and a.get("fin") == 1]
    nak = [a for a in rs if a["venue"] == "中山"]
    lng = [a for a in rs if a["surface"] == "芝" and a["dist"] >= 2400]
    ari = [a for a in rs if a["race"] == "有馬記念"]
    last = rs[-1]
    out = [f"### {name}（{sex}{age}・{tr}厩舎）", ""]
    if name in VOTE_RANK:
        out.append(f"- 昨年のファン投票：{VOTE_RANK[name]}位（{VOTE_2025[VOTE_RANK[name] - 1][1]:,}票）")
    out.append(f"- 今年のJRA重賞：{tally(ty)}（" + "、".join(f"{race_nm(a['race'])}{fin(a)}" for a in ty) + "）")
    out.append("- JRAのG1勝ち：" + ("、".join(f"{race_nm(a['race'])}（{a['date'][:4]}年）" for a in g1) if g1 else "なし"))
    out.append(f"- 中山の重賞：{tally(nak)}" + ("（" + "、".join(f"{a['date'][:4]}年{race_nm(a['race'])}{fin(a)}" for a in nak[-8:]) + "）" if nak else ""))
    out.append(f"- 芝2400m以上の重賞：{tally(lng)}")
    out.append("- 有馬記念：" + ("、".join(f"{a['date'][:4]}年{fin(a)}（{a['pop']}番人気）" if ran(a) else f"{a['date'][:4]}年{fin(a)}" for a in ari) if ari else "出走なし"))
    out.append(f"- いちばん最近のJRA重賞：{md(last['date'])} {race_nm(last['race'])} {fin(last)}" + (f"（{last['pop']}番人気）" if last.get("pop") else ""))
    if table:
        rec = [a for a in rs if a["date"] >= f"{YEAR - 1}0101"][-8:]
        out += ["", "| 日付 | レース | コース | 人気 | 着順 | 騎手 |", "|---|---|---|---|---|---|"]
        out += [f"| {a['date'][:4]}/{int(a['date'][4:6])}/{int(a['date'][6:])} | {race_nm(a['race'])}（{a['grade']}） | {a['venue']} {a['surface']}{a['dist']}m | "
                f"{a.get('pop') or '-'} | {fin(a)} | {a['jockey']} |" for a in reversed(rec)]
    name_l = horse_link(name)
    if name_l != name:
        out += ["", f"このサイトのAI評価の履歴：{name_l}"]
    return "\n".join(out) + "\n"


NOTE = ("> 成績はJRAの重賞だけを数えている。海外や地方のレース、重賞でないレースは入っていない。"
        "引退・休養・次に走るレースは各陣営の発表で変わるので、投票の前にJRAの投票サイトで選べる馬かどうかを確かめてほしい。\n")
LINKS = """## 関連する記事

- [有馬記念ファン投票2026：日程・投票方法と、過去10年の1位馬の成績](/column/arima2026-fan-vote/)
- [4歳以上の有力馬：今年のG1で3着以内に入った馬](/column/arima2026-vote-koba/)
- [3歳の有力馬：ダービー馬・菊花賞馬・牝馬のG1馬](/column/arima2026-vote-3sai/)
- [昨年の投票上位20頭は今年どうだったか](/column/arima2026-vote-kyonen/)
- [中山の重賞で成績の良い馬](/column/arima2026-vote-nakayama/)
- [有馬記念2026の日程と見どころ（特集のトップ）](/column/arima2026-guide/)
- [有馬記念の年齢・性別・騎手の傾向](/column/arima-kinen-nenrei-kishu/)
"""
SRC = """## 出典

- 各馬の成績：JRA公式の重賞成績ページ（[有馬記念 2025年の成績](https://www.jra.go.jp/datafile/seiseki/g1/arima/result/arima2025.html)、[天皇賞(秋) 2026年の成績](https://www.jra.go.jp/datafile/seiseki/g1/akiten/result/akiten2026.html) ほか各レースの成績）をこのサイトで集計
- 昨年のファン投票の順位と票数：JRA公式「[有馬記念ファン投票 最終結果発表（2025年12月11日）](https://jra.jp/news/202512/121107.html)」
- 今年のファン投票：JRA公式「[有馬記念ファン投票スタート（2026年11月19日）](https://www.jra.go.jp/news/202611/111904.html)」
"""


def write(slug, title, desc, lead, order, body):
    fm = f"---\ntitle: {title}\ndescription: {desc}\nlead: {lead}\ndate: {TODAY}\ndraft: false\norder: {order}\nseries: arima2026\nhero: g-turf-winter\n---\n"
    links = "\n".join(l for l in LINKS.splitlines() if f"/column/{slug}/" not in l)
    (ROOT / "columns" / f"{slug}.md").write_text(fm + body.rstrip() + "\n\n" + links + "\n\n" + SRC, encoding="utf-8")
    print(slug, len(body))


def g1_top3(cond):
    """今年の芝1800m以上のG1で3着以内に入った馬（条件つき）。成績の良い順。"""
    sc = defaultdict(int)
    for n, rs in RUNS.items():
        for a in this_year(n):
            if a["grade"] == "G1" and a["surface"] == "芝" and a["dist"] >= 1800 and ran(a) and a["fin"] <= 3 and cond(a):
                sc[n] += 4 - a["fin"]
    return sorted(sc, key=lambda n: -sc[n])


def summary_table(names) -> str:
    out = ["| 馬名 | 性齢 | 今年のJRA重賞 | 中山の重賞 | 芝2400m以上の重賞 |", "|---|---|---|---|---|"]
    for n in names:
        s, a, _ = now(n)
        rs = RUNS[n]
        out.append(f"| {n} | {s}{a} | {tally(this_year(n))} | {tally([x for x in rs if x['venue'] == '中山'])} | "
                   f"{tally([x for x in rs if x['surface'] == '芝' and x['dist'] >= 2400])} |")
    return "\n".join(out) + "\n"


def koba():
    top = g1_top3(lambda a: a["age"] >= 4)
    ari = [a["name"] for a in sorted((x for n, rs in RUNS.items() for x in rs if x["date"].startswith("2025") and x["race"] == "有馬記念" and ran(x) and x["fin"] <= 5),
                                     key=lambda x: x["fin"])]
    extra = [n for n in ari if n not in top and this_year(n)]
    names = top + extra
    g2 = sorted({a["name"] for n, rs in RUNS.items() for a in this_year(n)
                 if a["grade"] == "G2" and a["surface"] == "芝" and a["dist"] >= 2000 and a.get("fin") == 1 and a["age"] >= 4} - set(names),
                key=lambda n: this_year(n)[-1]["date"], reverse=True)
    w = [n for n in names if any(a["grade"] == "G1" and a.get("fin") == 1 for a in this_year(n))]
    body = ("## この記事で紹介する馬\n\n今年、芝1800m以上のJRAのG1で3着以内に入った4歳以上の馬と、昨年の有馬記念で5着以内だった馬のうち今年も重賞を走った馬を紹介する。"
            f"全部で{len(names)}頭。\n\n" + summary_table(names) + "\n" + NOTE + "\n## 1頭ずつの成績\n\n" + "\n".join(block(n) for n in names)
            + "\n## 今年の芝2000m以上のG2を勝った4歳以上の馬\n\nG1では3着以内に入っていないが、今年G2を勝っている馬。\n\n" + summary_table(g2))
    write("arima2026-vote-koba", f"有馬記念ファン投票2026 4歳以上の有力馬{len(names)}頭の成績まとめ｜クロワデュノール、ダノンデサイルほか",
          f"有馬記念ファン投票2026で投票先を考えるための、4歳以上の有力馬{len(names)}頭の成績まとめ。今年のG1を勝った{'、'.join(w)}など、今年のJRA重賞の成績、中山の重賞の成績、芝2400m以上の成績、有馬記念の出走歴を1頭ずつ並べた。",
          f"有馬記念ファン投票（12月6日締め切り）で投票する馬を考えるために、4歳以上の有力馬{len(names)}頭の成績をまとめた。今年のG1を勝ったのは{'、'.join(w)}。1頭ずつ、今年の重賞の成績、中山の重賞の成績、芝2400m以上の成績、有馬記念の出走歴を並べている。",
          3, body)


def sansai():
    names = g1_top3(lambda a: a["age"] == 3)
    w = [n for n in names if any(a["grade"] == "G1" and a.get("fin") == 1 for a in this_year(n))]
    rest = [n for n in names if n not in w]
    body = (f"## この記事で紹介する馬\n\n今年、芝1800m以上のJRAのG1で3着以内に入った3歳馬{len(names)}頭。G1を勝った{len(w)}頭は詳しく、残りは表で紹介する。\n\n"
            "有馬記念は3歳馬の成績が良いレースで、過去20年の年齢別の成績は[年齢・性別・騎手の傾向](/column/arima-kinen-nenrei-kishu/)にまとめている。"
            "2024年のレガレイラ、2025年のミュージアムマイルと、2年続けて3歳馬が勝った。3歳馬は4歳以上より2kg軽い重さで走れる。\n\n"
            + summary_table(names) + "\n" + NOTE + "\n## G1を勝った3歳馬\n\n" + "\n".join(block(n) for n in w)
            + "\n## G1で2着・3着に入った3歳馬\n\n" + "\n".join(block(n, table=False) for n in rest))
    write("arima2026-vote-3sai", f"有馬記念ファン投票2026 3歳の有力馬{len(names)}頭の成績まとめ｜ロブチェン、ゴーイントゥスカイほか",
          f"有馬記念ファン投票2026で投票先を考えるための、3歳の有力馬{len(names)}頭の成績まとめ。今年のG1を勝った{'、'.join(w)}など、今年のJRA重賞の成績、中山の重賞の成績、芝2400m以上の成績を1頭ずつ並べた。有馬記念は2年続けて3歳馬が勝っている。",
          f"有馬記念は2024年・2025年と2年続けて3歳馬が勝っている。ファン投票（12月6日締め切り）で投票する馬を考えるために、今年のG1で3着以内に入った3歳馬{len(names)}頭の成績をまとめた。G1を勝ったのは{'、'.join(w)}。",
          4, body)


def kyonen():
    rows, act = [], []
    for i, (n, v) in enumerate(VOTE_2025, 1):
        ty = this_year(n)
        a25 = [a for a in RUNS[n] if a["date"].startswith("2025") and a["race"] == "有馬記念"]
        if ty:
            act.append(n)
        rows.append(f"| {i} | {n} | {v:,}票 | {fin(a25[0]) if a25 else '出走せず'} | "
                    + (f"{tally(ty)}（" + "、".join(f"{race_nm(a['race'])}{fin(a)}" for a in ty) + "）" if ty else "JRA重賞の出走なし") + " |")
    won = [n for n in act if any(a["grade"] == "G1" and a.get("fin") == 1 for a in this_year(n))]
    none = [n for n, _ in VOTE_2025 if n not in act]
    body = ("## 昨年の上位20頭と、今年のJRA重賞の成績\n\n2025年のファン投票の最終結果（有効投票数685万2,342票）の上位20頭が、今年どんな成績だったかを並べた。\n\n"
            "| 昨年の順位 | 馬名 | 昨年の票数 | 昨年の有馬記念 | 今年のJRA重賞 |\n|---|---|---|---|---|\n" + "\n".join(rows) + "\n\n" + NOTE
            + f"\n## 分かること\n\n- **今年もJRAの重賞を走ったのは{len(act)}頭**：残りの{len(none)}頭（{'、'.join(none)}）は、今年のJRA重賞の出走がない。理由は海外のレースへの出走・休養・引退などが考えられるが、この記事のデータでは区別できない\n"
            + f"- **今年もJRAのG1を勝ったのは{len(won)}頭**：{'、'.join(won)}\n"
            + "- **昨年は上位10頭のうち5頭が出走**：票が多くても、距離が合わない馬や別のレースを選んだ馬は出走しない（[過去10年の1位馬の成績](/column/arima2026-fan-vote/)）\n"
            + "\n## 今年もJRAの重賞を走った馬の成績\n\n" + "\n".join(block(n, table=False) for n in act))
    write("arima2026-vote-kyonen", "有馬記念ファン投票 昨年の上位20頭は今年どうだった？2026年の成績まとめ",
          f"2025年の有馬記念ファン投票で上位20頭に入った馬の、2026年のJRA重賞の成績をまとめた。今年もJRAの重賞を走ったのは{len(act)}頭で、G1を勝ったのは{'、'.join(won)}の{len(won)}頭。今年の投票先を考える材料に。",
          f"昨年の有馬記念ファン投票で上位20頭に入った馬のうち、今年もJRAの重賞を走ったのは{len(act)}頭。そのうち{'、'.join(won)}の{len(won)}頭が今年もG1を勝った。昨年1位のレガレイラは、今年の天皇賞（秋）で3着だった。",
          5, body)


def nakayama():
    cand = []
    for n, rs in RUNS.items():
        ty = this_year(n)
        if not ty or ty[-1]["age"] < 3:
            continue
        nk = [a for a in rs if a["venue"] == "中山" and a["surface"] == "芝" and a["dist"] >= 1800 and ran(a)]
        w, t3 = sum(a["fin"] == 1 for a in nk), sum(a["fin"] <= 3 for a in nk)
        if len(nk) >= 2 and t3 >= 2 and w >= 1:
            cand.append((n, len(nk), w, t3, nk))
    cand.sort(key=lambda c: (-c[3], -c[2], c[1]))
    cand = cand[:14]
    tb = ["| 馬名 | 性齢 | 中山の芝1800m以上の重賞 | 走ったレース |", "|---|---|---|---|"]
    for n, k, w, t3, nk in cand:
        s, a, _ = now(n)
        tb.append(f"| {n} | {s}{a} | {k}戦{w}勝・3着以内{t3}回 | " + "、".join(f"{x['date'][:4]}年{race_nm(x['race'])}{fin(x)}" for x in nk[-5:]) + " |")
    ari = sorted((x for n, rs in RUNS.items() for x in rs if x["race"] == "有馬記念" and ran(x) and x["fin"] <= 5 and this_year(n)), key=lambda x: (-int(x["date"]), x["fin"]))
    at = ["| 年 | 着順 | 馬名 | 人気 | 今年のJRA重賞 |", "|---|---|---|---|---|"] + [
        f"| {x['date'][:4]} | {x['fin']}着 | {x['name']} | {x['pop']}番人気 | {tally(this_year(x['name']))} |" for x in ari]
    top = [c[0] for c in cand[:5]]
    body = ("## 中山の重賞で成績の良い馬\n\n有馬記念の舞台は中山の芝2500m。コーナーを6回まわり、最後の直線が短く、ゴール前に坂がある（[コースの特徴](/course/nakayama-turf-2500/)）。"
            "コースの向き不向きが出やすいので、中山の重賞で結果を出している馬を成績データから拾った。\n\n"
            "条件は、今年JRAの重賞を走った馬のうち、中山の芝1800m以上の重賞で1勝以上・3着以内2回以上。3着以内の回数が多い順に並べている。\n\n"
            + "\n".join(tb) + "\n\n" + NOTE + "\n## 有馬記念で5着以内に入ったことがある馬\n\n今年もJRAの重賞を走っている馬だけを載せた。\n\n" + "\n".join(at)
            + "\n\n## 上位5頭の成績\n\n" + "\n".join(block(n, table=False) for n in top))
    write("arima2026-vote-nakayama", "有馬記念ファン投票2026 中山の重賞で成績の良い馬｜コースの相性で選ぶ",
          f"有馬記念の舞台、中山の芝コースの重賞で成績の良い馬を、JRAの成績データから拾った。中山の芝1800m以上の重賞で1勝以上・3着以内2回以上の馬は{'、'.join(top[:3])}など。有馬記念で5着以内に入ったことがある現役馬の一覧も。",
          f"有馬記念は中山の芝2500mで行われ、コースの向き不向きが出やすい。ファン投票で投票する馬を考える材料として、中山の芝1800m以上の重賞で1勝以上・3着以内2回以上の馬を成績データから拾った。3着以内が多いのは{'、'.join(top[:3])}など。",
          6, body)


if __name__ == "__main__":
    koba(); sansai(); kyonen(); nakayama()
