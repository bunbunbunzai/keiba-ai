"""検索の入口を増やすページ群（build.py から呼ぶ）。

- /graded/              今週・最近の重賞一覧（中央・地方）
- /graded/<slug>/       重賞ごとの固定ページ（年をまたいで同じURL。「天皇賞秋 AI予想」の受け皿）
- /course/<slug>/       競馬場×芝ダ×距離ごとの、AI予想の成績と当日バイアスの傾向
- /jockey/<id>/         騎手ごとの、AIの◎に乗ったときの成績
データが少ないページ（薄いページ）は作らない。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict

GRADE_RE = re.compile(r"\((G|Jpn|JPN|S|SP|M|H|BG|重賞)\s*([1-3ⅠⅡⅢ])\)")

# 主な重賞の英語スラッグ（年をまたいで同じURLにするため）。無いものは名前から作る
GRADED_SLUG = {
    "フェブラリーステークス": "february-stakes", "高松宮記念": "takamatsunomiya-kinen", "大阪杯": "osaka-hai",
    "桜花賞": "oka-sho", "皐月賞": "satsuki-sho", "天皇賞(春)": "tenno-sho-spring", "NHKマイルカップ": "nhk-mile-cup",
    "ヴィクトリアマイル": "victoria-mile", "優駿牝馬": "oaks", "オークス": "oaks", "東京優駿": "derby", "日本ダービー": "derby",
    "安田記念": "yasuda-kinen", "宝塚記念": "takarazuka-kinen", "スプリンターズステークス": "sprinters-stakes",
    "秋華賞": "shuka-sho", "菊花賞": "kikka-sho", "天皇賞(秋)": "tenno-sho-autumn", "エリザベス女王杯": "queen-elizabeth-cup",
    "マイルチャンピオンシップ": "mile-championship", "ジャパンカップ": "japan-cup", "チャンピオンズカップ": "champions-cup",
    "阪神ジュベナイルフィリーズ": "hanshin-juvenile-fillies", "朝日杯フューチュリティステークス": "asahi-hai-fs",
    "有馬記念": "arima-kinen", "ホープフルステークス": "hopeful-stakes", "中山大障害": "nakayama-daishogai",
    "中山グランドジャンプ": "nakayama-grand-jump", "東京大賞典": "tokyo-daishoten", "帝王賞": "teio-sho",
    "JBCクラシック": "jbc-classic", "JBCスプリント": "jbc-sprint", "JBCレディスクラシック": "jbc-ladies-classic",
    "JBC2歳優駿": "jbc-2yo-yushun", "かしわ記念": "kashiwa-kinen", "川崎記念": "kawasaki-kinen",
    "全日本2歳優駿": "zen-nihon-2yo-yushun", "東京ダービー": "tokyo-derby", "ジャパンダートクラシック": "japan-dirt-classic",
    "南部杯": "nambu-hai", "マイルチャンピオンシップ南部杯": "nambu-hai",
}


def nfkc(s) -> str:
    return unicodedata.normalize("NFKC", s or "")


def grade_of(race: dict, name: str = "") -> str | None:
    g = race.get("grade")
    if g and str(g).upper().startswith(("G", "J・G")):
        return str(g)
    text = nfkc(" ".join(str(x or "") for x in (name, race.get("race_name"), race.get("title_text"))))
    m = GRADE_RE.search(text)
    if m:
        return f"{m.group(1)}{ {'Ⅰ': '1', 'Ⅱ': '2', 'Ⅲ': '3'}.get(m.group(2), m.group(2)) }"
    return "重賞" if "重賞" in text else None


def clean_name(name: str) -> str:
    """「第174回 天皇賞(秋) 3歳以上…」→「天皇賞(秋)」。地方の（Ｓ２）等や条件も外す。"""
    n = nfkc(name)
    n = re.sub(r"^第\d+回\s*", "", n)
    n = GRADE_RE.sub("", n)
    n = re.split(r"\s+(?:\d歳|[23]上|オープン|サラ|混合|一般|選抜)", n)[0]
    n = re.sub(r"競走$", "", n).strip()
    return n


def graded_slug(name: str, venue_slug: str) -> str:
    n = clean_name(name)
    if n in GRADED_SLUG:
        return GRADED_SLUG[n]
    for k, v in GRADED_SLUG.items():
        if k in n:
            return v
    return f"{venue_slug}-{hashlib.md5(n.encode()).hexdigest()[:8]}"


def short_id(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()[:10]


def pct(a, b) -> str:
    return f"{100 * a / b:.1f}%" if b else "―"


def build_pages(B, by_date: dict, today: str) -> dict[str, str]:
    """B は build モジュール（page・write・esc などを使う）。{path: lastmod} を返す。"""
    esc, write, page, jsonld = B.esc, B.write, B.page, B.jsonld
    lastmod: dict[str, str] = {}
    iso = lambda d: f"{d[:4]}-{d[4:6]}-{d[6:8]}"

    # ---------- 重賞 ----------
    graded = defaultdict(list)  # slug -> [(date, p, name, grade)]
    for d, ps in by_date.items():
        for p in ps:
            name = p.get("race_name") or p["_race"].get("race_name") or p["_race"].get("title_text") or ""
            g = grade_of(p["_race"], name)
            if not g:
                continue
            v = B.venue_of(p)
            slug = graded_slug(name, B.VENUE_SLUG.get(v, "venue"))
            p["_graded"] = (slug, clean_name(name), g)
            graded[slug].append((d, p, clean_name(name), g))
    rows_all = []
    for slug, items in graded.items():
        items.sort(key=lambda x: x[0], reverse=True)
        d0, p0, name, g = items[0]
        v = B.VENUE_NAME.get(B.venue_of(p0), B.venue_of(p0))
        lis = []
        for d, p, _, _ in items:
            sc = B.scored(p)
            res = ""
            if sc and sc["stake"]:
                res = (f"的中・回収率{B.roi_txt(sc['stake'], sc['return'])}" if sc["return"] else "不的中")
            hon = p.get("marks", {}).get("◎")
            lis.append(f"<li><a href='{B.race_path(d, p)}'><span>{int(d[:4])}年 {esc(B.fmt_date(d))}</span>"
                       f"<span>◎{esc(hon)} {esc(B.horse_name(p, hon))}　{esc(res)}</span></a></li>")
        path = f"/graded/{slug}/"
        latest = items[0]
        hon = latest[1].get("marks", {}).get("◎")
        lead = (f"{name}（{g}・{v}）のAI予想。{int(latest[0][:4])}年は◎{hon}{B.horse_name(latest[1], hon)}"
                f"（{B.fmt_date(latest[0])}）。全頭の評価点・印・買い目と、確定後の的中・回収率を年ごとに記録している。")
        body = (f"<p class='crumb'><a href='/'>トップ</a> › <a href='/graded/'>重賞</a> › {esc(name)}</p>"
                f"<h1>{esc(name)} AI予想（{esc(g)}）</h1><p class='answer'>{esc(lead)}</p>"
                f"<section class='card'><h2>年ごとのAI予想と結果</h2><ul class='days'>{''.join(lis)}</ul></section>"
                f"<p class='meta'>毎年このページに追加される。最新の予想はレース当日の昼（重賞は前日夜にも）公開。</p>")
        ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": B.SITE_NAME, "item": B.BASE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": "重賞", "item": B.BASE_URL + "/graded/"},
            {"@type": "ListItem", "position": 3, "name": name, "item": B.BASE_URL + path}]}
        write(path, page(f"【AI予想】{name} 全頭診断と買い目・過去の結果｜{B.SITE_NAME}", body, path,
                         desc=lead[:120], head_extra=jsonld(ld)))
        lastmod[path] = iso(items[0][0])
        rows_all.append((latest[0], latest[1], name, g, slug))
    rows_all.sort(key=lambda x: (x[0], x[1]["_race"].get("post_time") or ""), reverse=True)
    upcoming = [r for r in rows_all if r[0] >= today]
    past = [r for r in rows_all if r[0] < today][:40]

    def glist(rows):
        return "<ul class='races'>" + "".join(
            f"<li><a href='/graded/{r[4]}/'><span class='rt'>{esc(B.md(r[0]))}</span>"
            f"<span class='rno'>{esc(B.venue_of(r[1]))}{B.race_no(r[1])}R</span><span class='hon'>{esc(r[2])}（{esc(r[3])}）"
            f"　◎{esc(r[1].get('marks', {}).get('◎'))} {esc(B.horse_name(r[1], r[1].get('marks', {}).get('◎')))}</span></a></li>"
            for r in rows) + "</ul>"
    body = ("<p class='crumb'><a href='/'>トップ</a> › 重賞</p><h1>今週の重賞 AI予想一覧</h1>"
            "<p class='answer'>中央（GⅠ〜GⅢ）と地方（Jpn・S格付け）の重賞のAI予想をまとめている。各レースの固定ページでは、年ごとの予想と結果を記録している。</p>"
            + (f"<section class='card'><h2>これからの重賞</h2>{glist(upcoming)}</section>" if upcoming else "")
            + (f"<section class='card'><h2>最近の重賞</h2>{glist(past)}</section>" if past else "<p>まだありません。</p>"))
    write("/graded/", page(f"今週の重賞 AI予想一覧（中央・地方）｜{B.SITE_NAME}", body, "/graded/",
                           desc="今週の重賞（GⅠ・GⅡ・GⅢ、地方のJpn・S格付け）のAI予想一覧。全頭診断・印・買い目と過去の結果。"))
    lastmod["/graded/"] = iso(today)

    # ---------- コース別（場×芝ダ×距離） ----------
    courses = defaultdict(list)
    for d, ps in by_date.items():
        if d < B.STATS_FROM:
            continue
        for p in ps:
            r = p["_race"]
            if not r.get("distance"):
                continue
            surf = "芝" if r.get("surface") == "芝" else "障害" if r.get("surface") == "障" else "ダート"
            courses[(B.venue_of(p), surf, int(r["distance"]))].append((d, p))
    clist = []
    for (v, surf, dist), items in courses.items():
        done = [B.scored(p) for _, p in items if B.scored(p) and B.scored(p)["stake"]]
        if len(done) < 5:  # 5レース未満は作らない
            continue
        vs = B.VENUE_SLUG.get(v, "venue")
        slug = f"{vs}-{'turf' if surf == '芝' else 'jump' if surf == '障害' else 'dirt'}-{dist}"
        path = f"/course/{slug}/"
        st, rt = sum(s["stake"] for s in done), sum(s["return"] for s in done)
        win = sum(1 for s in done if str(s.get("honmei_finish")) == "1")
        top3 = sum(1 for s in done if str(s.get("honmei_finish")) in ("1", "2", "3"))
        # 勝ち馬の4角位置（先行か）と枠
        front = inner = n = 0
        for _, p in items:
            for row in (p.get("_result") or {}).get("rows") or []:
                if str(row.get("finish")) == "1" and row.get("pos4") and row.get("number"):
                    fld = p["_race"].get("field") or 12
                    n += 1
                    front += row["pos4"] <= (5 if fld >= 12 else 4)
                    inner += row["number"] <= max(1, round(fld / 3))
        vn = B.VENUE_NAME.get(v, v)
        name = f"{vn}{surf}{dist}m"
        lead = (f"{name}のAI予想は{len(done)}レースで回収率{B.roi_txt(st, rt)}、◎の勝率{pct(win, len(done))}・3着内率{pct(top3, len(done))}。"
                + (f"勝ち馬{n}頭のうち4コーナー先行は{pct(front, n)}、内枠（頭数の1/3以内）は{pct(inner, n)}。" if n else ""))
        recent = sorted(items, key=lambda x: x[0], reverse=True)[:20]
        lis = "".join(B.race_item(d, p) for d, p in recent)
        body = (f"<p class='crumb'><a href='/'>トップ</a> › <a href='/course/'>コース別</a> › {esc(name)}</p>"
                f"<h1>{esc(name)}のAI予想成績と傾向</h1><p class='answer'>{esc(lead)}</p>"
                f"<div class='kpis'><div><b>{len(done)}</b><span>集計レース</span></div><div><b>{B.roi_txt(st, rt)}</b><span>回収率</span></div>"
                f"<div><b>{pct(win, len(done))}</b><span>◎勝率</span></div><div><b>{pct(front, n)}</b><span>勝ち馬の先行率</span></div></div>"
                f"<section class='card'><h2>最近のレース</h2><ul class='races'>{lis}</ul></section>"
                f"<p class='meta'>{esc(B.fmt_date(B.STATS_FROM))}以降、見送りを除く。各点100円の均等買いで集計。<a href='{B.venue_path(v)}'>{esc(vn)}競馬の予想一覧</a></p>")
        write(path, page(f"{name} AI予想の成績と傾向（回収率・先行率）｜{B.SITE_NAME}", body, path, desc=lead[:120]))
        lastmod[path] = iso(max(d for d, _ in items))
        clist.append((vn, surf, dist, path, len(done), B.roi_txt(st, rt)))
    clist.sort()
    write("/course/", page(f"コース別 AI予想の成績と傾向｜{B.SITE_NAME}",
                           "<p class='crumb'><a href='/'>トップ</a> › コース別</p><h1>コース別のAI予想成績と傾向</h1>"
                           "<p class='answer'>競馬場・芝ダート・距離ごとに、AI予想の回収率と、勝ち馬の先行率・内枠率をまとめている（5レース以上のコースのみ）。</p>"
                           "<ul class='days'>" + "".join(f"<li><a href='{c[3]}'><span>{esc(c[0])} {esc(c[1])}{c[2]}m</span><span>{c[4]}レース・回収率{c[5]}</span></a></li>" for c in clist) + "</ul>",
                           "/course/", desc="競馬場・芝ダート・距離ごとのAI予想の回収率と傾向。", noindex=not clist))
    if clist:
        lastmod["/course/"] = iso(today)

    # ---------- 騎手別（AIの◎に乗ったとき） ----------
    jk = defaultdict(list)
    for d, ps in by_date.items():
        if d < B.STATS_FROM:
            continue
        for p in ps:
            sc = B.scored(p)
            hon = p.get("marks", {}).get("◎")
            if not sc or hon is None:
                continue
            h = next((x for x in p["_race"].get("horses", []) if x.get("number") == hon), None)
            if h and h.get("jockey"):
                jk[nfkc(h["jockey"]).replace(" ", "")].append((d, p, sc))
    jlist = []
    for name, items in jk.items():
        if len(items) < 5:
            continue
        path = f"/jockey/{short_id(name)}/"
        win = sum(1 for *_, s in items if str(s.get("honmei_finish")) == "1")
        top3 = sum(1 for *_, s in items if str(s.get("honmei_finish")) in ("1", "2", "3"))
        venues = sorted({B.VENUE_NAME.get(B.venue_of(p), B.venue_of(p)) for _, p, _ in items})
        lead = (f"{name}騎手がAI予想の◎に乗ったのは{len(items)}回で、1着{win}回（勝率{pct(win, len(items))}）、"
                f"3着以内{top3}回（{pct(top3, len(items))}）。主な騎乗場：{'・'.join(venues[:5])}。")
        lis = "".join(B.race_item(d, p) for d, p, _ in sorted(items, key=lambda x: x[0], reverse=True)[:20])
        body = (f"<p class='crumb'><a href='/'>トップ</a> › <a href='/jockey/'>騎手別</a> › {esc(name)}</p>"
                f"<h1>{esc(name)}騎手 × AI予想◎の成績</h1><p class='answer'>{esc(lead)}</p>"
                f"<div class='kpis'><div><b>{len(items)}</b><span>◎の騎乗</span></div><div><b>{pct(win, len(items))}</b><span>勝率</span></div>"
                f"<div><b>{pct(top3, len(items))}</b><span>3着内率</span></div></div>"
                f"<section class='card'><h2>◎で騎乗した最近のレース</h2><ul class='races'>{lis}</ul></section>")
        write(path, page(f"{name}騎手 AI予想◎の成績（勝率・複勝率）｜{B.SITE_NAME}", body, path, desc=lead[:120]))
        lastmod[path] = iso(max(d for d, *_ in items))
        jlist.append((name, path, len(items), pct(win, len(items)), pct(top3, len(items))))
    jlist.sort(key=lambda x: -x[2])
    write("/jockey/", page(f"騎手別 AI予想◎の成績｜{B.SITE_NAME}",
                           "<p class='crumb'><a href='/'>トップ</a> › 騎手別</p><h1>騎手別：AI予想の◎に乗ったときの成績</h1>"
                           "<p class='answer'>AIが◎（本命）にした馬の騎手ごとに、勝率・3着内率をまとめている（5回以上の騎手のみ）。</p>"
                           "<div class='scroll'><table><thead><tr><th>騎手</th><th>◎騎乗</th><th>勝率</th><th>3着内率</th></tr></thead><tbody>"
                           + "".join(f"<tr><td><a href='{j[1]}'>{esc(j[0])}</a></td><td>{j[2]}</td><td>{j[3]}</td><td>{j[4]}</td></tr>" for j in jlist)
                           + "</tbody></table></div>", "/jockey/", desc="AI予想の◎に乗った騎手ごとの勝率・複勝率。", noindex=not jlist))
    if jlist:
        lastmod["/jockey/"] = iso(today)
    return lastmod
