"""G1の「特集まとめ」（〇〇2026はいつ？日程・出走予定馬と過去10年の傾向【特集まとめ】）を作る。AIは呼ばない。

Bingの検索では、この形の特集まとめ（ジャパンカップ・有馬記念・マイルCS）がレース名の検索で1ページ目に入り、
検索からのクリックのほとんどを集めている。まだ特集まとめが無いG1について、同じ形のページを作る。
数字は重賞の全着順（data/graded_hist）から数え、日程・条件はレースガイド（data/race_guides）とJRAの発表による。
登録馬（特別登録・出走予定馬）は、サイトを作るときに column.py が自動で差し込む。
前哨戦が終わるたび・レースが終わったあとに中身が変わるので、graded の毎日の回で作り直す（中身が同じなら書き換えない）。

  python g1_hub_cols.py
"""
from __future__ import annotations

import contextlib
import io
import re
import statistics
from datetime import datetime, timedelta, timezone

from common import DATA_DIR

import graded_cols as G

ROOT = DATA_DIR.parent
COLS = ROOT / "columns"
JST = timezone(timedelta(hours=9))
FIRST_DATE = "2026-11-20"
YEAR = 2026
WD = "月火水木金土日"

# 手で確かめた日程・条件（JRAの「GⅠ特集」のページと、このサイトのレースガイド）
RACES = [
    dict(series="hjf2026", guide="hanshin-jf2026-guide", slug="hanshin-juvenile-fillies", name="阪神ジュベナイルフィリーズ", no=78, grade="G1", date="20261213",
         place="阪神競馬場 芝1600m（外回り・右回り）", place_s="阪神芝1600m", cond="2歳牝馬・馬齢（55kg）。最大18頭",
         about="2歳の牝馬だけが走るG1で、その年の2歳女王を決めるレース", kind="2yo", fillies=True, hero="g-turf-winter",
         jra="https://www.jra.go.jp/keiba/g1/hjf.html"),
    dict(series="afs2026", guide="asahi-hai-fs2026-guide", slug="asahi-hai-fs", name="朝日杯フューチュリティステークス", no=78, grade="G1", date="20261220",
         place="阪神競馬場 芝1600m（外回り・右回り）", place_s="阪神芝1600m", cond="2歳の牡馬・牝馬・馬齢（牡馬56kg、牝馬55kg）。せん馬は出られない。最大18頭",
         about="2歳馬がマイルで争うG1で、2歳王者を決めるレース", kind="2yo", hero="g-turf-winter",
         jra="https://www.jra.go.jp/keiba/g1/afs.html"),
    dict(series="hopeful2026", guide="hopeful2026-guide", slug="hopeful-stakes", name="ホープフルステークス", no=43, grade="G1", date="20261226",
         place="中山競馬場 芝2000m（内回り・右回り）", place_s="中山芝2000m", cond="2歳の牡馬・牝馬・馬齢。せん馬は出られない。最大18頭",
         about="翌春の皐月賞と同じ舞台で行われる、2歳の中距離のG1", kind="2yo", long=True, hero="g-turf-winter",
         jra="https://www.jra.go.jp/keiba/g1/hopeful/data.html"),
    dict(series="daishogai2026", guide="nakayama-daishogai2026-guide", slug="nakayama-daishogai", name="中山大障害", no=149, grade="J・G1", date="20261226",
         place="中山競馬場 障害芝4100m（大障害コース）", place_s="中山障害4100m", cond="障害3歳以上オープン・定量（3歳61kg、4歳以上63kg、牝馬は2kg減）",
         about="春の中山グランドジャンプと並ぶ、障害レースの最高峰", kind="jump", hero="g-jump",
         jra="https://www.jra.go.jp/keiba/g1/daishogai.html"),
]


def dt(d: str) -> datetime:
    return datetime.strptime(d, "%Y%m%d")


def jp(d: str, wd: bool = True) -> str:
    x = dt(d)
    return f"{x.month}月{x.day}日" + (f"（{WD[x.weekday()]}）" if wd else "")


def ab(r: dict) -> str:
    return (r.get("abbr") or "").replace("(", "（").replace(")", "）")


def who(x: dict, sex: bool = False) -> str:
    return f"{x['name']}（{x['pop']}番人気{'・' + x.get('sex', '') if sex and x.get('sex') else ''}）" if x.get("pop") else x["name"]


def top3(r: dict) -> list[dict]:
    return sorted((x for x in G.runners(r) if G.fin(x) <= 3), key=G.fin)


def preps(all_: dict, cfg: dict) -> list[dict]:
    """今年、このG1より前に終わった重賞のうち、前哨戦として見るもの（2歳重賞・障害重賞）。"""
    out = []
    for r in all_.get(YEAR, []):
        if r["date"] >= cfg["date"] or not G.runners(r):
            continue
        if cfg["kind"] == "2yo" and "2歳" in (r.get("cond") or ""):
            out.append(r)
        elif cfg["kind"] == "jump" and r.get("surface") == "障":
            out.append(r)
    return sorted(out, key=lambda r: r["date"])


def past10(K: dict, slug: str) -> dict[int, dict]:
    ys = sorted(y for y, r in (K.get(slug) or {}).items() if YEAR - 10 <= y < YEAR and G.runners(r))
    return {y: K[slug][y] for y in ys}


def stats(P: dict[int, dict]) -> dict:
    rows = [x for r in P.values() for x in G.runners(r)]
    wins = {y: next(x for x in G.runners(r) if G.fin(x) == 1) for y, r in P.items()}
    fav = [x for x in rows if x["pop"] == 1]
    t3 = sorted(v for v in (G.pay1(r, "3連単") for r in P.values()) if v)
    hi_y = max(P, key=lambda y: G.pay1(P[y], "3連単") or 0) if t3 else None
    long = max(wins.items(), key=lambda kv: kv[1]["pop"])
    jk: dict[str, int] = {}
    for x in wins.values():
        jk[x["jockey"]] = jk.get(x["jockey"], 0) + 1
    tr: dict[str, int] = {}
    for x in wins.values():
        tr[x["trainer"]] = tr.get(x["trainer"], 0) + 1
    rep: dict[str, list[int]] = {}
    for y, x in wins.items():
        rep.setdefault(x["name"], []).append(y)
    return dict(n=len(rows), years=len(P), wins=wins,
                fav=[sum(G.fin(x) == k for x in fav) for k in (1, 2, 3)], fav_n=len(fav),
                w13=sum(1 for x in wins.values() if x["pop"] <= 3), w4=sum(1 for x in wins.values() if x["pop"] >= 4),
                long=long, big=sum(1 for x in rows if x["pop"] >= 10 and G.fin(x) <= 3), big_n=sum(1 for x in rows if x["pop"] >= 10),
                inner=sum(1 for x in wins.values() if (x.get("frame") or 9) <= 4), outer=sum(1 for x in wins.values() if (x.get("frame") or 0) >= 5),
                t3_med=int(statistics.median(t3)) if t3 else 0, t3_hi=(hi_y, G.pay1(P[hi_y], "3連単")) if hi_y else None,
                jockeys=sorted(((j, n) for j, n in jk.items() if n >= 2), key=lambda t: (-t[1], t[0])),
                trainers=sorted(((t, n) for t, n in tr.items() if n >= 2), key=lambda t: (-t[1], t[0])),
                repeat=[(n, ys) for n, ys in rep.items() if len(ys) >= 2],
                kyoto=[y for y, r in P.items() if r.get("venue") != P[max(P)].get("venue")])


def exists(slug: str) -> bool:
    return (COLS / f"{slug}.md").exists()


def build(cfg: dict, all_: dict, K: dict) -> tuple[str, str, str, str]:
    name, d, slug = cfg["name"], cfg["date"], cfg["slug"]
    x = dt(d)
    nom = (x - timedelta(days=(x.weekday() - 6) % 7 or 7)).strftime("%Y%m%d")  # その週の前の日曜（特別登録の締め切り）
    waku = (x - timedelta(days=(x.weekday() - 3) % 7)).strftime("%Y%m%d")      # その週の木曜（枠順の確定）
    P = past10(K, slug)
    s = stats(P)
    this = (K.get(slug) or {}).get(YEAR)
    done = bool(this and G.runners(this))
    pr = preps(all_, cfg)
    y0, y1 = min(P), max(P)
    fav = s["fav"]
    # ---- 本文 ----
    body = "## レースの基本情報\n\n"
    body += (f"- レース：第{cfg['no']}回{name}（{cfg['grade']}）\n- 日時：{YEAR}年{jp(d)}\n- 場所：{cfg['place']}\n- 条件：{cfg['cond']}\n"
             f"- 特別登録の締め切り：{jp(nom)}（登録した馬はJRAが発表する）\n- 枠順の確定：{jp(waku)}の予定\n"
             f"- このサイトのAI予想：レースの前日の夜までに公開（枠順の確定後）\n\n")
    if not done:
        body += f"> 登録馬の一覧は、JRAの特別登録の発表（{jp(nom, False)}ごろ）のあと、このページと[{name}のページ](/graded/{slug}/)に自動で載る。\n\n"
    if done:
        t = top3(this)
        body += (f"## {YEAR}年の結果\n\n{YEAR}年の{name}は{who(t[0])}が勝った。2着は{who(t[1])}、3着は{who(t[2])}。"
                 f"このサイトのAI予想と答え合わせは[{name}のページ](/graded/{slug}/)にある。\n\n")
    # 前哨戦
    if pr:
        if cfg["kind"] == "2yo":
            fil = cfg.get("fillies")
            body += f"## {YEAR}年の2歳重賞の結果\n\n" + ("牝馬は名前のあとに「牝」と書いた。" if fil else "") + "人気はそのレースの単勝人気。\n\n"
        else:
            body += f"## {YEAR}年の障害重賞の結果\n\n人気はそのレースの単勝人気。\n\n"
        body += "| 日付 | レース | 1着 | 2着 | 3着 |\n|---|---|---|---|---|\n"
        for r in pr:
            t = top3(r)
            cell = lambda i: (who(t[i]) + ("・牝" if cfg.get("fillies") and t[i].get("sex") == "牝" else "")) if len(t) > i else "-"
            body += f"| {jp(r['date'], False)} | {ab(r)}（{r.get('grade', '')}） | {cell(0)} | {cell(1)} | {cell(2)} |\n"
        body += "\n"
        if cfg["kind"] == "2yo" and cfg.get("fillies"):
            fw = [(r, t) for r in pr for t in top3(r) if t.get("sex") == "牝"]
            if fw:
                body += ("2歳重賞で3着以内に入った牝馬は" + "、".join(f"{t['name']}（{ab(r)}{G.fin(t)}着）" for r, t in fw[:10])
                         + (f"など{len(fw)}頭。" if len(fw) > 10 else "。") + "\n\n")
        if cfg["kind"] == "jump":
            wn = [top3(r)[0]["name"] for r in pr]
            body += (f"{YEAR}年の障害重賞は{len(pr)}レースで、勝ち馬は{len(set(wn))}頭" + ("（すべて違う馬）" if len(set(wn)) == len(wn) else "") + "。"
                     "障害の名馬は[障害レースの名馬の記事](/column/arima2026-oshi-shogai/)でも紹介している。\n\n")
    # 過去10年
    body += (f"## 過去10年のデータから分かること\n\n{y0}〜{y1}年の{s['years']}回、延べ{s['n']}頭の全着順（JRA公式の成績）を集計した。"
             + (f"{'・'.join(str(y) for y in s['kyoto'])}年は{P[s['kyoto'][0]].get('venue')}競馬場で行われた。" if s["kyoto"] and len(s["kyoto"]) <= 2 else "") + "\n\n")
    gl = lambda k, t: f"（[{t}](/column/{slug}-{k}/)）" if exists(f"{slug}-{k}") else ""
    body += (f"- **1番人気**：{fav[0]}勝・2着{fav[1]}回・3着{fav[2]}回。3着以内は{sum(fav)}回（{s['fav_n']}回中）"
             + ("。勝てなかった年はすべて4着以下で、2着・3着は一度もない" if fav[0] and not fav[1] and not fav[2] else "") + f"{gl('ninki-waku', '人気と枠順')}\n"
             f"- **勝ち馬の人気**：1〜3番人気が{s['w13']}勝、4番人気以下が{s['w4']}勝。いちばん人気がなかった勝ち馬は{s['long'][0]}年の{s['long'][1]['name']}（{s['long'][1]['pop']}番人気）\n"
             f"- **人気薄**：10番人気以下は延べ{s['big_n']}頭で、3着以内は{s['big']}回\n"
             f"- **枠**：1〜4枠が{s['inner']}勝、5〜8枠が{s['outer']}勝\n"
             + (f"- **3連単**：中央値は{G.man(s['t3_med'])}。最高は{s['t3_hi'][0]}年の{G.man(s['t3_hi'][1])}\n" if s["t3_hi"] else "")
             + ("- **騎手**：" + "、".join(f"{j}騎手が{n}勝" for j, n in s["jockeys"][:3]) + f"{gl('nenrei-kishu', '年齢・騎手')}\n" if s["jockeys"] else "")
             + ("- **調教師**：" + "、".join(f"{t}調教師が{n}勝" for t, n in s["trainers"][:3]) + "\n" if s["trainers"] else "")
             + ("- **リピーター**：" + "、".join(f"{n}（{'・'.join(str(y) for y in ys)}年）" for n, ys in s["repeat"]) + "が2回以上勝っている\n" if s["repeat"] else "")
             + (f"- **前走**：勝ち馬の前走や間隔は[前走別の成績](/column/{slug}-zenso/)にまとめた\n" if exists(f"{slug}-zenso") else "")
             + "\n")
    body += "## 過去10年の勝ち馬\n\n| 年 | 勝ち馬 | 人気 | 騎手 | 調教師 |\n|---|---|---|---|---|\n"
    for y in sorted(P, reverse=True):
        w = s["wins"][y]
        body += f"| {y} | {w['name']} | {w['pop']}番人気 | {w['jockey']} | {w['trainer']} |\n"
    body += "\n## 特集の記事\n\n"
    links = [("kako-kekka", "過去20年の結果一覧"), ("ninki-waku", "人気と枠順の傾向（過去20年）"), ("nenrei-kishu", "年齢・性別・騎手の傾向（過去20年）"),
             ("zenso", "前走別の成績（ローテーション）"), ("jinx", "ジンクス・データで見る傾向")]
    body += "".join(f"- [{name}の{t}](/column/{slug}-{k}/)\n" for k, t in links if exists(f"{slug}-{k}"))
    body += f"- [{name}のレースガイド（歴史・条件・主な前哨戦）とAI予想](/graded/{slug}/)\n"
    if cfg["kind"] == "2yo":
        body += "- [2026年の2歳重賞の結果（年間の振り返り）](/column/year2026-2sai/)\n" if exists("year2026-2sai") else ""
    body += "\nほかのG1の特集は[秋のG1 2026の日程とまとめ](/column/aki-g1-2026/)から。\n\n"
    body += (f"## 出典\n\n- 日程・条件：[JRA（{name}の特集ページ）]({cfg['jra']})、このサイトのレースガイド\n"
             f"- 過去10年の着順・配当、{YEAR}年の重賞の結果：JRA公式の成績（このサイトが集めたJRAの重賞の全着順）\n")
    # ---- 題名など ----
    title = f"{name}{YEAR}はいつ？日程・出走予定馬と過去10年の傾向【特集まとめ】"
    lead = (f"第{cfg['no']}回{name}は{YEAR}年{jp(d)}、{cfg['place'].split('（')[0]}で行われる。{cfg['about']}だ。"
            f"過去10年は1番人気が{fav[0]}勝し、3着以内に{sum(fav)}回入った。"
            + (f"勝ち馬の{s['w13']}頭が1〜3番人気だが、{s['long'][0]}年には{s['long'][1]['pop']}番人気の{s['long'][1]['name']}が勝っている。" if s["long"][1]["pop"] >= 4 else "")
            + (f"{YEAR}年の{name}は{top3(this)[0]['name']}が勝った。" if done else ""))
    pw = ""
    if pr and cfg["kind"] == "2yo":
        if cfg.get("fillies"):    # 牝馬のG1：牝馬限定の重賞（アルテミスS・ファンタジーSなど）
            big = [r for r in pr if (r.get("cond") or "").endswith("牝")][-2:]
        elif cfg.get("long"):     # 2000mのG1：1800m以上の2歳重賞（札幌2歳S・東スポ杯2歳S・京都2歳Sなど）
            big = [r for r in pr if (r.get("distance") or 0) >= 1800][-2:]
        else:
            big = [r for r in pr if r.get("grade") in ("G1", "G2")][-2:]
        big = big or pr[-2:]
        pw = "今年の2歳重賞では、" + "、".join(f"{ab(r)}を{top3(r)[0]['name']}" for r in big) + "が勝った。"
    elif pr:
        wn = [top3(r)[0]["name"] for r in pr]
        last = s["wins"][max(P)]["name"]
        mine = [ab(r) for r in pr if top3(r)[0]["name"] == last]
        pw = (f"今年の障害重賞は{len(pr)}レースが終わり、勝ち馬は{len(set(wn))}頭" + ("ですべて違う。" if len(set(wn)) == len(wn) else "。")
              + (f"昨年の勝ち馬{last}は、今年の{'・'.join(mine)}を勝った。" if mine else ""))
    desc = (f"{YEAR}年の{name}（{cfg['grade']}・{cfg['place_s']}）は{jp(d)}。{pw}"
            f"過去10年の全着順から分かる人気・枠・騎手の傾向と勝ち馬の一覧、登録馬をまとめた特集のトップページ。")
    return cfg["guide"], title, desc, lead + ("" if done else pw), body


def write(slug: str, series: str, hero: str, title: str, desc: str, lead: str, body: str, today: str) -> bool:
    p = COLS / f"{slug}.md"
    date, updated = FIRST_DATE, ""
    if p.exists():
        t = p.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", t, re.S)
        if m:
            if m.group(2).strip() == body.strip():
                return False
            dd = re.search(r"^date:\s*(\S+)", m.group(1), re.M)
            date = dd.group(1) if dd else date
        updated = today
    meta = {"title": title, "description": desc, "lead": lead, "date": date}
    if updated and updated > date:
        meta["updated"] = updated
    meta.update({"draft": "false", "order": 1, "series": series, "hero": hero})
    head = "\n".join(f"{k}: {str(v).replace(chr(10), ' ')}" for k, v in meta.items())
    p.write_text(f"---\n{head}\n---\n{body}", encoding="utf-8")
    return True


def main() -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        all_ = G.load_all()
        G._init_names()
        K = G.keyed(all_)
    today = datetime.now(JST).strftime("%Y-%m-%d")
    n = 0
    for cfg in RACES:
        if not past10(K, cfg["slug"]):
            print("過去のデータが無い", cfg["slug"])
            continue
        slug, title, desc, lead, body = build(cfg, all_, K)
        if write(slug, cfg["series"], cfg["hero"], title, desc, lead, body, today):
            n += 1
            print("wrote", slug)
    print("特集まとめ:", n)


if __name__ == "__main__":
    main()
