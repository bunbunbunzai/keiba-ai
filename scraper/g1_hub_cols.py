"""G1の「特集まとめ」（〇〇2026はいつ？日程・出走予定馬と過去10年の傾向【特集まとめ】）を作る。AIは呼ばない。

Bingの検索では、この形の特集まとめ（ジャパンカップ・有馬記念・マイルCS）がレース名の検索で1ページ目に入り、
検索からのクリックのほとんどを集めている。まだ特集まとめが無いG1について、同じ形のページを作る。
数字は重賞の全着順（data/graded_hist）から数え、日程・条件はレースガイド（data/race_guides）とJRAの発表による。
登録馬（特別登録・出走予定馬）は、サイトを作るときに column.py が自動で差し込む。
前哨戦が終わるたび・レースが終わったあとに中身が変わるので、graded の毎日の回で作り直す（中身が同じなら書き換えない）。

来年のレース（NEXT）は、JRAが出した来年の重賞の一覧（data/graded_hist/<来年>.json）の日程で、レースの AHEAD_DAYS 日前から作る
（2026-11-23〜。1〜2月はG1が無いので、金杯も作る）。条件はレースガイド（data/race_guides）から引き、前哨戦の日程と結果を毎日入れ替える。

  python g1_hub_cols.py
"""
from __future__ import annotations

import contextlib
import io
import json
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


def past10(K: dict, slug: str, year: int = 0) -> dict[int, dict]:
    year = year or YEAR
    ys = sorted(y for y, r in (K.get(slug) or {}).items() if year - 10 <= y < year and G.runners(r))
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
    # JRA：出走馬（馬番なし）はその週の木曜の16時すぎ、G1の枠順は金曜の9時すぎ（https://www.jra.go.jp/faq/pop02/2_2.html）
    thu = (x - timedelta(days=(x.weekday() - 3) % 7)).strftime("%Y%m%d")
    waku = (x - timedelta(days=(x.weekday() - 4) % 7)).strftime("%Y%m%d")
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
             f"- 特別登録の締め切り：{jp(nom)}（登録した馬はJRAが発表する）\n"
             f"- 出走馬の確定：{jp(thu)}の夕方（馬番・枠番はまだ）\n- 枠順の確定：{jp(waku)}の朝\n"
             f"- このサイトのAI予想：枠順の確定後、{jp(waku)}の昼〜レースの前日の夜に公開\n\n")
    if not done:
        body += (f"> 登録馬・出走馬・枠順は、JRAの発表（{jp(nom, False)}ごろから）のあと、このページと[{name}のページ](/graded/{slug}/)に自動で載る。"
                 "レースが終わると、このページの冒頭に結果と払戻が自動で載る。\n\n")
    # レースが終わったら、結果（上位5頭・払戻・AIの◎の着順）はサイトを作るとき（site/weekly.py の result_box）に記事の冒頭へ自動で入る
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


def write(slug: str, series: str, hero: str, title: str, desc: str, lead: str, body: str, today: str,
          first: str = "", extra: dict | None = None) -> bool:
    p = COLS / f"{slug}.md"
    date, updated = first or FIRST_DATE, ""
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
    meta.update(extra or {})
    head = "\n".join(f"{k}: {str(v).replace(chr(10), ' ')}" for k, v in meta.items())
    p.write_text(f"---\n{head}\n---\n{body}", encoding="utf-8")
    return True


# ---------- 来年のレースの特集まとめ ----------
AHEAD_DAYS = 150  # レースの何日前から特集まとめを作るか（一度に大量のページを増やさないよう、近い順に少しずつ増やす）
NEXT_INDEX = "g1-nittei-2027"
# series は「<名前><年>」。site/weekly.py の FEATURE_RACE、site/column.py の FEATURE_2027 と同じ名前にする。
# about はレースをひとことで（レースガイドの説明から）。preps は前哨戦・関連レース（レースガイドの「主な前哨戦」のうちJRAの重賞）
NEXT = [
    dict(series="nkimpai2027", slug="nakayama-kimpai", about="年明け最初の開催日に行われるハンデ戦のG3で、東の「金杯」と呼ばれる", hero="g-turf-winter",
         preps=["fukushima-kinen", "naruo-kinen"]),
    dict(series="kkimpai2027", slug="kyoto-kimpai", about="年明け最初の開催日に行われるマイルのハンデ戦のG3で、西の「金杯」と呼ばれる", hero="g-turf-winter",
         preps=["fuji-stakes", "turquoise-stakes"]),
    dict(series="feb2027", slug="february-stakes", about="中央競馬でその年最初に行われるG1で、ダートのマイル王を決める", hero="g-dirt-day",
         preps=["champions-cup", "procyon-stakes", "negishi-stakes"]),
    dict(series="takamatsu2027", slug="takamatsunomiya-kinen", about="春のスプリント王を決める、芝1200mのG1", hero="g-sprint",
         preps=["silkroad-stakes", "hankyu-hai", "ocean-stakes"]),
    dict(series="osaka2027", slug="osaka-hai", about="春の中距離チャンピオンを決める、4歳以上のG1", hero="g-turf-spring",
         preps=["kyoto-kinen", "nakayama-kinen", "kinko-sho"]),
    dict(series="oka2027", slug="oka-sho", about="3歳牝馬の三冠の1戦目にあたるG1", hero="g-turf-spring",
         preps=["hanshin-juvenile-fillies", "tulip-sho", "fillies-review"]),
    dict(series="ngj2027", slug="nakayama-grand-jump", about="年末の中山大障害と並ぶ、障害レースの最高峰", hero="g-jump",
         preps=["nakayama-daishogai", "hanshin-spring-jump"]),
    dict(series="satsuki2027", slug="satsuki-sho", about="3歳馬のクラシック三冠の1戦目にあたるG1", hero="g-turf-spring",
         preps=["hopeful-stakes", "kyodo-tsushin-hai", "yayoi-sho", "spring-stakes"]),
    dict(series="tenharu2027", slug="tenno-sho-spring", about="JRAの平地のG1でいちばん距離が長い、芝3200mのレース", hero="g-stayer",
         preps=["hanshin-daishoten", "nikkei-sho", "osaka-hai"]),
    dict(series="nhk2027", slug="nhk-mile-cup", about="3歳のマイル王を決めるG1", hero="g-turf-spring",
         preps=["falcon-stakes", "mainichi-hai", "churchill-downs-cup", "new-zealand-trophy", "oka-sho", "satsuki-sho"]),
    dict(series="vm2027", slug="victoria-mile", about="4歳以上の牝馬が春の女王を争う、芝1600mのG1", hero="g-turf-spring",
         preps=["nakayama-himba-stakes", "takamatsunomiya-kinen", "hanshin-himba-stakes", "fukushima-himba-stakes"]),
    dict(series="oaks2027", slug="oaks", about="3歳牝馬の三冠の2戦目にあたる、芝2400mのG1", hero="g-turf-spring",
         preps=["oka-sho", "flora-stakes"]),
    dict(series="derby2027", slug="derby", about="3歳馬の頂点を決める、クラシック三冠の2戦目", hero="g-turf-spring",
         preps=["mainichi-hai", "satsuki-sho", "aoba-sho", "kyoto-shimbun-hai"]),
    dict(series="yasuda2027", slug="yasuda-kinen", about="春のマイル王を決めるG1", hero="g-turf-summer",
         preps=["milers-cup", "keio-hai-spring-cup", "victoria-mile"]),
    dict(series="takara2027", slug="takarazuka-kinen", about="ファン投票で出走馬を選ぶ、上半期のグランプリ", hero="g-turf-summer",
         preps=["kyoto-kinen", "kinko-sho", "nikkei-sho", "osaka-hai", "tenno-sho-spring"]),
]


def guide_of(slug: str) -> dict:
    try:
        return json.loads((DATA_DIR / "race_guides" / f"{slug}.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def course_s(r: dict) -> str:
    """一覧の「芝 2,000 メートル」「ダ 1,600 メートル」を「芝2000m」「ダート1600m」に。"""
    c = (r.get("course") or "").replace(" ", "").replace(",", "").replace("メートル", "m")
    return re.sub(r"^ダ(?!ー)", "ダート", re.sub(r"^障(?!害)", "障害", c))


def time_jp(t: str) -> str:
    """「1:35.4」を「1分35秒4」に。"""
    m = re.fullmatch(r"(\d+):(\d{2})\.(\d)", t or "")
    return f"{m.group(1)}分{m.group(2)}秒{m.group(3)}" if m else (t or "")


def next_guide_slug(cfg: dict) -> str:
    return f"{cfg['slug']}{cfg['series'][-4:]}-guide"


def past_block(name: str, slug: str, P: dict, s: dict) -> str:
    """「過去10年のデータから分かること」と「過去10年の勝ち馬」（来年の特集まとめ用。数え方は今年の分と同じ）。"""
    y0, y1 = min(P), max(P)
    fav = s["fav"]
    gl = lambda k, t: f"（[{t}](/column/{slug}-{k}/)）" if exists(f"{slug}-{k}") else ""
    body = (f"## 過去10年のデータから分かること\n\n{y0}〜{y1}年の{s['years']}回、延べ{s['n']}頭の全着順（JRA公式の成績）を集計した。"
            + (f"{'・'.join(str(y) for y in s['kyoto'])}年は{P[s['kyoto'][0]].get('venue')}競馬場で行われた。" if s["kyoto"] and len(s["kyoto"]) <= 2 else "") + "\n\n")
    body += (f"- **1番人気**：{fav[0]}勝・2着{fav[1]}回・3着{fav[2]}回。3着以内は{sum(fav)}回（{s['fav_n']}回中）{gl('ninki-waku', '人気と枠順')}\n"
             f"- **勝ち馬の人気**：1〜3番人気が{s['w13']}勝、4番人気以下が{s['w4']}勝。いちばん人気がなかった勝ち馬は{s['long'][0]}年の{s['long'][1]['name']}（{s['long'][1]['pop']}番人気）\n"
             f"- **人気薄**：10番人気以下は延べ{s['big_n']}頭で、3着以内は{s['big']}回\n"
             f"- **枠**：1〜4枠が{s['inner']}勝、5〜8枠が{s['outer']}勝\n"
             + (f"- **3連単**：中央値は{G.man(s['t3_med'])}。最高は{s['t3_hi'][0]}年の{G.man(s['t3_hi'][1])}\n" if s["t3_hi"] else "")
             + ("- **騎手**：" + "、".join(f"{j}騎手が{n}勝" for j, n in s["jockeys"][:3]) + f"{gl('nenrei-kishu', '年齢・騎手')}\n" if s["jockeys"] else "")
             + ("- **調教師**：" + "、".join(f"{t}調教師が{n}勝" for t, n in s["trainers"][:3]) + "\n" if s["trainers"] else "")
             + ("- **2回以上勝った馬**：" + "、".join(f"{n}（{'・'.join(str(y) for y in ys)}年）" for n, ys in s["repeat"]) + "\n" if s["repeat"] else "")
             + (f"- **前走**：勝ち馬の前走や間隔は[前走別の成績](/column/{slug}-zenso/)にまとめた\n" if exists(f"{slug}-zenso") else "")
             + "\n")
    body += "## 過去10年の勝ち馬\n\n| 年 | 勝ち馬 | 人気 | 騎手 | 調教師 | 単勝 | 3連単 |\n|---|---|---|---|---|---|---|\n"
    for y in sorted(P, reverse=True):
        w = s["wins"][y]
        tan, t3 = G.pay1(P[y], "単勝"), G.pay1(P[y], "3連単")
        body += f"| {y} | {w['name']} | {w['pop']}番人気 | {w['jockey']} | {w['trainer']} | {f'{tan:,}円' if tan else '-'} | {G.man(t3) if t3 else '-'} |\n"
    return body + "\n"


def build_next(cfg: dict, all_: dict, K: dict, today: str) -> tuple | None:
    """来年のレースの特集まとめ。日程が無い・過去のデータが無い・まだ遠いレースは None。"""
    slug, year = cfg["slug"], int(cfg["series"][-4:])
    r = (K.get(slug) or {}).get(year)
    P = past10(K, slug, year)
    if not r or not P:
        return None
    d = r["date"]
    gslug = next_guide_slug(cfg)
    days = (dt(d) - dt(today.replace("-", ""))).days
    if not (COLS / f"{gslug}.md").exists() and not (0 <= days <= AHEAD_DAYS):
        return None
    g = guide_of(slug)
    facts = {str(f.get("k")): str(f.get("v")) for f in g.get("facts") or []}
    name = g.get("name") or r.get("name") or ab(r)
    grade = r.get("grade") or ""
    place_s = f"{r.get('venue', '')}{course_s(r)}"
    x = dt(d)
    last = K[slug].get(year - 1) or {}
    m = re.match(r"第\s*(\d+)\s*回", last.get("title") or "")
    no = f"第{int(m.group(1)) + 1}回" if m and G.runners(last) else ""
    s = stats(P)
    fav = s["fav"]
    done = bool(G.runners(r))
    g1 = grade in ("G1", "J・G1") and x.weekday() in (5, 6)
    thu = (x - timedelta(days=(x.weekday() - 3) % 7)).strftime("%Y%m%d")
    waku = (x - timedelta(days=(x.weekday() - 4) % 7)).strftime("%Y%m%d")
    # ---- 基本情報 ----
    body = "## レースの基本情報\n\n"
    body += f"- レース：{no}{name}（{grade}）\n- 日時：{year}年{jp(d)}\n- 場所：{facts.get('競馬場・距離') or place_s}\n"
    body += f"- 出られる馬：{facts['出走条件']}\n" if facts.get("出走条件") else f"- 出られる馬：{r.get('cond', '')}\n"
    body += f"- 負担重量：{facts['負担重量']}\n" if facts.get("負担重量") else ""
    if g1:
        body += (f"- 出走馬の確定：{jp(thu)}の夕方（馬番・枠番はまだ）\n- 枠順の確定：{jp(waku)}の朝\n"
                 f"- このサイトのAI予想：枠順の確定後、{jp(waku)}の昼〜レースの前日の夜に公開\n\n")
    else:
        body += "- 出走馬・枠順：JRAの発表のあと、このページに載る\n- このサイトのAI予想：枠順の確定後、レースの前日の夜までに公開\n\n"
    if not done:
        body += (f"> 日付は、JRAが発表した{year}年の重賞の一覧による。場所・出られる馬・負担重量は{year - 1}年までの内容で、{year}年の正式な条件はJRAの発表で確かめてほしい。"
                 f"登録馬・出走馬・枠順は、JRAの発表のあと、このページと[{name}のページ](/graded/{slug}/)に自動で載る。\n\n")
    # ---- 去年の結果 ----
    lt = top3(last) if G.runners(last) else []
    if len(lt) >= 3:
        tan, t3 = G.pay1(last, "単勝"), G.pay1(last, "3連単")
        body += (f"## {year - 1}年の結果\n\n{year - 1}年{jp(last['date'])}の{name}は、{who(lt[0])}が勝った"
                 + (f"（{lt[0]['jockey']}騎手" + (f"、勝ち時計{time_jp(lt[0]['time'])}" if lt[0].get("time") else "") + (f"、{last['track']}馬場" if last.get("track") else "") + "）" if lt[0].get("jockey") else "")
                 + f"。2着は{who(lt[1])}、3着は{who(lt[2])}。"
                 + (f"払戻は単勝{tan:,}円" + (f"、3連単{G.man(t3)}" if t3 else "") + "。" if tan else "") + "\n\n")
    # ---- 前哨戦・関連レース ----
    rows = []
    for ps in cfg.get("preps") or []:
        cand = [K[ps][y] for y in (year - 1, year) if (K.get(ps) or {}).get(y)]
        cand = [c for c in cand if c["date"] < d and (x - dt(c["date"])).days <= 200]
        if cand:
            rows.append((ps, max(cand, key=lambda c: c["date"])))
    rows.sort(key=lambda t: t[1]["date"])
    if rows:
        body += ("## 前哨戦・関連レースの日程と結果\n\n終わったレースは上位3頭（かっこ内は単勝人気）、これからのレースは日付を載せる。結果は、レースが終わるたびに自動で入る。\n\n"
                 "| 日付 | レース | 1着 | 2着 | 3着 |\n|---|---|---|---|---|\n")
        for ps, c in rows:
            nm = f"[{ab(c)}](/graded/{ps}/)" if (DATA_DIR / "race_guides" / f"{ps}.json").exists() else ab(c)
            when = (f"{c['date'][:4]}年" if c["date"][:4] != str(year) else "") + jp(c["date"], False)
            t = top3(c) if G.runners(c) else []
            if len(t) >= 3:
                body += f"| {when} | {nm}（{c.get('grade', '')}） | {who(t[0])} | {who(t[1])} | {who(t[2])} |\n"
            else:
                body += f"| {when} | {nm}（{c.get('grade', '')}） | これから | - | - |\n"
        body += "\n"
        if facts.get("主な前哨戦"):
            body += f"レースガイドでは、主な前哨戦を次のように説明している：{facts['主な前哨戦'].rstrip('。')}。\n\n"
    # ---- 過去10年 ----
    body += past_block(name, slug, P, s)
    body += "## 特集の記事\n\n"
    links = [("kako-kekka", "過去20年の結果一覧"), ("ninki-waku", "人気と枠順の傾向（過去20年）"), ("nenrei-kishu", "年齢・性別・騎手の傾向（過去20年）"),
             ("zenso", "前走別の成績（ローテーション）"), ("jinx", "ジンクス・データで見る傾向")]
    body += "".join(f"- [{name}の{t}](/column/{slug}-{k}/)\n" for k, t in links if exists(f"{slug}-{k}"))
    body += f"- [{name}のレースガイド（歴史・条件・主な前哨戦）とAI予想](/graded/{slug}/)\n"
    body += f"\nほかのレースは[{year}年のG1日程と特集の一覧](/column/{NEXT_INDEX}/)から。\n\n"
    body += (f"## 出典\n\n- 日程：JRA「[{year}年 重賞競走一覧](https://www.jra.go.jp/datafile/seiseki/replay/{year}/jyusyo.html)」\n"
             f"- 場所・出られる馬・負担重量・前哨戦：このサイトのレースガイド（JRAの発表にもとづく{year - 1}年までの内容）\n"
             f"- 過去10年の着順・配当、前哨戦の結果：JRA公式の成績（このサイトが集めたJRAの重賞の全着順）\n")
    # ---- 題名など ----
    title = f"{name}{year}はいつ？日程・前哨戦と過去10年の傾向【特集まとめ】"
    lw = f"{year - 1}年は{who(lt[0])}が勝った。" if lt else ""
    lead = (f"{no}{name}は{year}年{jp(d)}、{r.get('venue', '')}競馬場の{course_s(r)}で行われる。{cfg['about']}レースだ。"
            f"過去10年は1番人気が{fav[0]}勝し、3着以内に{sum(fav)}回入った。" + lw)
    desc = (f"{year}年の{name}（{grade}・{place_s}）は{jp(d)}。{lw}"
            f"前哨戦の日程と結果、過去10年の全着順から分かる人気・枠・騎手の傾向と勝ち馬の一覧をまとめた特集のトップページ。")
    extra = {"race_name": name, "race_date": d, "race_venue": r.get("venue", ""), "race_course": course_s(r), "race_grade": grade}
    return gslug, title, desc, lead, body, extra


def build_index(K: dict, year: int, today: str) -> tuple[str, str, str, str] | None:
    """来年のG1の日程の一覧（特集まとめへの入口）。"""
    g1 = sorted(((ys[year], s) for s, ys in K.items() if year in ys and ys[year].get("grade") in ("G1", "J・G1")), key=lambda t: t[0]["date"])
    if len(g1) < 20:
        return None
    hub = {c["slug"]: next_guide_slug(c) for c in NEXT if int(c["series"][-4:]) == year}
    body = (f"JRAが発表した{year}年の重賞の一覧から、G1（障害のJ・G1を含む{len(g1)}レース）の日付・競馬場・コースを並べた。"
            f"レース名から、日程・前哨戦・過去10年の傾向をまとめた特集まとめ、またはレースの傾向のページへ進める。\n\n"
            f"## {year}年のG1の日程\n\n| 日付 | レース | 競馬場・コース | 出られる馬 | {year - 1}年の勝ち馬 |\n|---|---|---|---|---|\n")
    for r, s in g1:
        name = guide_of(s).get("name") or ab(r)
        gs = hub.get(s)
        href = f"/column/{gs}/" if gs and exists(gs) else (f"/graded/{s}/" if (DATA_DIR / "race_guides" / f"{s}.json").exists() else "")
        last = K[s].get(year - 1) or {}
        lt = top3(last) if G.runners(last) else []
        lw = f"{lt[0]['name']}（{lt[0]['pop']}番人気）" if lt else ("これから（" + jp(last["date"], False) + "）" if last.get("date") else "-")
        body += (f"| {jp(r['date'])} | " + (f"[{name}]({href})" if href else name) + ("（J・G1）" if r.get("grade") == "J・G1" else "")
                 + f" | {r.get('venue', '')} {course_s(r)} | {r.get('cond', '')} | {lw} |\n")
    first, last_ = g1[0][0], g1[-1][0]
    wd = [r for r, _ in g1 if dt(r["date"]).weekday() not in (5, 6)]
    body += (f"\n{year}年の最初のG1は{jp(first['date'])}の{guide_of(g1[0][1]).get('name') or ab(first)}、最後は{jp(last_['date'])}の{guide_of(g1[-1][1]).get('name') or ab(last_)}。"
             + ("土曜・日曜以外に行われるG1は" + "、".join(f"{guide_of(s).get('name') or ab(r)}（{jp(r['date'])}）" for r, s in g1 if r in wd) + "。" if wd else "")
             + "\n\n")
    made = [(c, (K.get(c["slug"]) or {}).get(year)) for c in NEXT if int(c["series"][-4:]) == year and exists(next_guide_slug(c))]
    if made:
        body += f"## 特集まとめ（公開しているもの）\n\nレースの約5か月前から順に公開している。出走馬・枠順・AI予想・結果は、発表のたびに自動で入れ替わる。\n\n"
        for c, r in sorted(made, key=lambda t: t[1]["date"]):
            nm = guide_of(c["slug"]).get("name") or ab(r)
            body += f"- [{nm}{year}（{jp(r['date'])}・{r.get('venue', '')}{course_s(r)}）](/column/{next_guide_slug(c)}/)\n"
        body += "\n"
    body += (f"## {year}年の日程で変わること\n\nJRAの発表によると、{year}年の中央競馬は1月4日（月）に始まり、12月28日（火）で終わる。"
             "重賞では、根岸ステークス・オーシャンステークス・キーンランドカップ・みやこステークス・武蔵野ステークスの5レースについて、G3からG2への格上げが申請されている"
             f"（格付けの審査は{year}年1月の予定）。障害の新潟ジャンプステークスは福島競馬場に移り、福島ジャンプステークスとして行われる。\n\n"
             "> 日付と条件は変わることがある。正式な内容はJRAの発表で確かめてほしい。馬券は20歳から購入できる。\n\n"
             f"## 出典\n\n- JRA「[{year}年 重賞競走一覧](https://www.jra.go.jp/datafile/seiseki/replay/{year}/jyusyo.html)」「[{year}年 GⅠレース一覧](https://www.jra.go.jp/datafile/seiseki/replay/{year}/g1.html)」\n"
             f"- JRA「[{year}年度開催日割および重賞競走](https://www.jra.go.jp/news/202609/092805.html)」（2026年9月28日）、「[{year}年度競馬番組等](https://www.jra.go.jp/news/202611/111701.html)」（2026年11月17日）\n"
             f"- {year - 1}年の勝ち馬：JRA公式の成績（このサイトが集めたJRAの重賞の全着順）\n")
    nm = lambda i: guide_of(g1[i][1]).get("name") or ab(g1[i][0])
    by = {s: r for r, s in g1}
    pick = [(s, by[s]) for s in ("february-stakes", "derby", "arima-kinen") if s in by]
    title = f"{year}年のG1日程一覧｜{nm(0)}から{nm(-1)}まで全{len(g1)}レース（JRA）"
    desc = (f"{year}年のJRAのG1（障害を含む{len(g1)}レース）の日付・競馬場・コースの一覧。"
            + "、".join(f"{guide_of(s).get('name') or ab(r)}は{jp(r['date'])}" for s, r in pick) + "。各レースの特集まとめへの入口。")
    nj = sum(1 for r, _ in g1 if r.get("grade") == "J・G1")
    lead = (f"{year}年のJRAのG1は{len(g1)}レース（障害の{nj}レースを含む）。{jp(first['date'])}の{nm(0)}に始まり、{jp(last_['date'])}の{nm(-1)}で終わる。"
            "JRAが発表した重賞の一覧から、日付・競馬場・コースを表にまとめた。")
    return title, desc, lead, body


def main() -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        all_ = G.load_all()
        G._init_names()
        K = G.keyed(all_)
    today = datetime.now(JST).strftime("%Y-%m-%d")
    n = 0
    for cfg in NEXT:
        out = build_next(cfg, all_, K, today)
        if not out:
            continue
        gslug, title, desc, lead, body, extra = out
        if write(gslug, cfg["series"], cfg["hero"], title, desc, lead, body, today, first=today, extra=extra):
            n += 1
            print("wrote", gslug)
    for year in sorted({int(c["series"][-4:]) for c in NEXT}):
        idx = build_index(K, year, today)
        if idx and write(NEXT_INDEX, f"g1{year}", "g-turf-spring", *idx, today, first=today):
            n += 1
            print("wrote", NEXT_INDEX)
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
