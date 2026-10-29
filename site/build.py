"""サイト生成：predictions/・data/races/・data/results/ から静的HTMLを _site/ に書き出す。

URL 構成
  /                         今日の予想（次に発走するレースを強調、場ごとに切り替え）
  /YYYY/MM/DD/              日付別の予想一覧（アーカイブ）
  /YYYY/MM/DD/<場>/<NN>r/   レースページ
  /results/                 成績
  /about/  /operator/  /privacy/
  旧URL /races/<日付>/<id>.html は新URLへ転送する

使い方: python site/build.py
"""
from __future__ import annotations

import csv
import html
import json
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import column
import og

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"
SITE_NAME = "AI競馬ログ"
SITE_SUB = "全レースAI予想と回収率の記録"
DOMAIN = "www.ai-keiba-log.com"
BASE_URL = f"https://{DOMAIN}"
REPO = "https://github.com/bunbunbunzai/keiba-ai"
JST = timezone(timedelta(hours=9))
MARKS = ["◎", "〇", "▲", "△", "☆"]
STATS_FROM = "20261026"  # 自動運用を始めた日。これより前（試運転）は成績に含めない
VENUE_SLUG = {
    "札幌": "sapporo", "函館": "hakodate", "福島": "fukushima", "新潟": "niigata", "東京": "tokyo",
    "中山": "nakayama", "中京": "chukyo", "京都": "kyoto", "阪神": "hanshin", "小倉": "kokura",
    "帯広ば": "obihiro", "帯広": "obihiro", "門別": "monbetsu", "盛岡": "morioka", "水沢": "mizusawa",
    "浦和": "urawa", "船橋": "funabashi", "大井": "ooi", "川崎": "kawasaki", "金沢": "kanazawa",
    "笠松": "kasamatsu", "名古屋": "nagoya", "園田": "sonoda", "姫路": "himeji", "高知": "kochi", "佐賀": "saga",
}
VENUE_NAME = {"帯広ば": "帯広（ばんえい）"}


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def fmt_date(d: str) -> str:
    return f"{d[:4]}年{int(d[4:6])}月{int(d[6:8])}日"


def md(d: str) -> str:
    return f"{int(d[4:6])}/{int(d[6:8])}"


def roi_txt(stake, ret) -> str:
    return f"{100 * ret / stake:.1f}%" if stake else "―"


def day_path(d: str) -> str:
    return f"/{d[:4]}/{d[4:6]}/{d[6:8]}/"


def venue_of(p: dict) -> str:
    return p.get("venue") or p["_race"].get("venue") or ""


def race_no(p: dict) -> int:
    return int(p.get("race_no") or p["_race"].get("race_no") or 0)


def race_path(d: str, p: dict) -> str:
    v = venue_of(p)
    return f"{day_path(d)}{VENUE_SLUG.get(v, 'venue')}/{race_no(p):02d}r/"


def frame_of(num, field: int):
    """枠番の標準の割り当て（頭数が8を超えると外枠から2頭ずつ）。"""
    try:
        n, f = int(num), int(field)
    except (TypeError, ValueError):
        return ""
    if f <= 8:
        return n
    base, extra = divmod(f, 8)  # 外側の extra 枠が1頭多い
    sizes = [base + (1 if i >= 8 - extra else 0) for i in range(8)]
    for i, sz in enumerate(sizes):
        if n <= sz:
            return i + 1
        n -= sz
    return 8


def venue_path(v: str) -> str:
    return f"/venue/{VENUE_SLUG.get(v, 'venue')}/"


def jsonld(obj) -> str:
    return f'<script type="application/ld+json">{json.dumps(obj, ensure_ascii=False)}</script>'


OG_DAYS = 30  # レースごとの共有画像を作る期間（古いレースはサイト共通の画像を使う）
ASSETS = Path(__file__).resolve().parent / "assets"


def page(title: str, body: str, path: str, desc: str = "", noindex: bool = False, head_extra: str = "",
         og_image: str = "/og/default.jpg") -> str:
    d = desc or "AIが日本の競馬（JRA・地方）の全レースを毎日予想し、外れも含めた全予想の回収率を公開しています。"
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(d)}">
<link rel="canonical" href="{BASE_URL}{path}">
{'<meta name="robots" content="noindex">' if noindex else ''}
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(d)}">
<meta property="og:url" content="{BASE_URL}{path}"><meta property="og:type" content="website"><meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:image" content="{BASE_URL}{og_image}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="{BASE_URL}{og_image}">
{FAVICON}<link rel="alternate" type="application/rss+xml" title="{SITE_NAME}" href="/feed.xml">
<link rel="stylesheet" href="/style.css">
{head_extra}
</head><body>
<header class="top"><div class="wrap">
<a class="logo" href="/">{'<img src="/assets/logo-mark-96.png" alt="" width="40" height="40">' if LOGO else ''}<span>{SITE_NAME}<small>{SITE_SUB}</small></span></a>
<nav><a href="/">今日の予想</a><a href="/results/">成績</a><a href="/venue/">競馬場</a>{'<a href="/column/">コラム</a>' if HAS_COLUMN else ''}<a href="/about/">予想の方法</a></nav>
</div></header>
<main class="wrap">{body}</main>
<footer class="wrap foot">
<p>本サイトの予想は情報提供を目的としたもので、的中や利益を保証するものではありません。馬券の購入はご自身の判断と責任で行ってください。20歳未満の方は馬券を購入できません。</p>
<p>レース情報は主催者の発表が正です。成績は全予想を各点100円の均等買いとして集計しています。</p>
<p><a href="/operator/">運営者情報</a>　<a href="/privacy/">プライバシーポリシー</a>　<a href="{REPO}/issues">お問い合わせ</a></p>
</footer>
<script src="/app.js"></script>
</body></html>"""


FAVICON = ('<link rel="icon" href="/assets/favicon.png" type="image/png"><link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">'
           if (ASSETS / "favicon.png").exists() else "")
LOGO = (ASSETS / "logo-mark.png").exists()
HAS_COLUMN = any(not c["draft"] for c in column.columns())


def write(path: str, content: str) -> None:
    f = OUT / path.lstrip("/")
    if path.endswith("/"):
        f = f / "index.html"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")


# ---------------- データ読み込み ----------------
def all_dates() -> list[str]:
    return sorted({p.name for p in (ROOT / "predictions").glob("*") if p.is_dir()}, reverse=True)


SCORE_UPDATED: dict[str, str] = {}


def scored(p: dict) -> dict | None:
    sc = p.get("_score")
    return sc if sc and "stake" in sc and not sc.get("voided") else None


def predictions(date: str) -> list[dict]:
    score = load_json(ROOT / "data" / "results" / date / "score.json") or {}
    SCORE_UPDATED[date] = (score.get("updated") or "")[-5:]
    sc_by = {r.get("race_id"): r for r in score.get("races", [])}
    out = []
    for f in sorted((ROOT / "predictions" / date).glob("*.json")):
        p = load_json(f)
        if not p:
            continue
        p["_race"] = load_json(ROOT / "data" / "races" / date / f"{p['race_id']}.json") or {}
        p["_score"] = sc_by.get(p["race_id"])
        p["_result"] = load_json(ROOT / "data" / "results" / date / f"{p.get('results_key') or p['race_id']}.json") or {}
        out.append(p)
    out.sort(key=lambda p: (p["_race"].get("post_time") or "99:99", venue_of(p), race_no(p)))
    return out


def ledger() -> list[dict]:
    f = ROOT / "results_ledger.csv"
    if not f.exists():
        return []
    with f.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    # 試運転分と見送り（投資0円）は成績から外す
    return [r for r in rows if r["date"] >= STATS_FROM and int(r["stake"] or 0) > 0]


BIAS: dict[str, dict] = {}


def bias_for(date: str, p: dict) -> tuple[str, dict] | None:
    """その日のその場（芝/ダ）の最新のバイアス判定。"""
    if date not in BIAS:
        b, upd = {}, ""
        for src in ("jra", "rakuten"):
            d = load_json(ROOT / "data" / "bias" / f"{date}_{src}.json") or {}
            b.update(d.get("bias", {}))
            upd = max(upd, d.get("updated") or "")
        BIAS[date] = {"bias": b, "updated": upd}
    r = p["_race"]
    key = f"{venue_of(p)}{'芝' if r.get('surface') == '芝' else 'ダ'}"
    v = BIAS[date]["bias"].get(key)
    return (key, dict(v, updated=BIAS[date]["updated"][-5:])) if v else None


# ---------------- 部品 ----------------
def mark_map(p: dict) -> dict:
    out = {}
    for m in MARKS:
        v = p.get("marks", {}).get(m)
        for n in (v if isinstance(v, list) else [v] if v is not None else []):
            out[n] = m
    return out


def horse_name(p: dict, num) -> str:
    for h in p["_race"].get("horses", []) or []:
        if h.get("number") == num:
            return h.get("name") or ""
    return next((e.get("name") for e in p.get("horses", []) if e.get("number") == num), "") or ""


def race_label(p: dict) -> str:
    name = p.get("race_name") or p["_race"].get("race_name") or p["_race"].get("title_text") or ""
    return f"{venue_of(p)}{race_no(p)}R {' '.join(name.split())}".strip()


def result_text(p: dict) -> str:
    sc = p.get("_score")
    if not sc or "stake" not in sc:
        return ""
    if sc.get("voided"):
        return "結果は未確定または返還"
    top = "-".join(str(x) for x in sc.get("top3", []) if x is not None)
    return f"結果は{top}で{'的中（払戻' + format(sc['return'], ',') + '円）' if sc['return'] else '不的中'}"


def answer_sentence(date: str, p: dict) -> str:
    hon = p.get("marks", {}).get("◎")
    base = f"{race_label(p)}（{fmt_date(date)}）のAI予想は"
    if p.get("confidence") == "見送り":
        s = base + "見送り（データ不足などで買い目なし）。"
    else:
        s = base + f"◎{hon}{horse_name(p, hon)}、自信度{p.get('confidence')}。"
    rt = result_text(p)
    return s + (rt + "。" if rt else "")


# ---------------- レースページ ----------------
def race_page(date: str, p: dict, prev_next: tuple) -> str:
    r = p["_race"]
    mk = mark_map(p)
    horses = {h.get("number"): h for h in r.get("horses", []) or []}
    evals = {e.get("number"): e for e in p.get("horses", [])}
    sc = p.get("_score") or {}
    top3 = sc.get("top3") or []
    fin_by = {x.get("number"): x for x in (p.get("_result") or {}).get("rows", []) or []}
    rows = []
    for num in sorted(set(horses) | set(evals), key=lambda x: (x is None, x)):
        h, e = horses.get(num, {}), evals.get(num, {})
        fr = fin_by.get(num) or {}
        fin = fr.get("finish")
        if fin is None and num in top3:
            fin = top3.index(num) + 1
        fin_txt = f"{fin}着" if str(fin or "").isdigit() else (esc(fin) if fin else "")
        odds, wp = h.get("odds"), e.get("win_pct")
        val, tag = "", ""
        try:
            if odds and wp:
                v = float(odds) * float(wp) / 100
                val = f"{v:.2f}"
                tag = "<span class='tag good'>妙味</span>" if v >= 1.2 else "<span class='tag bad'>過剰人気</span>" if v < 0.8 else ""
        except (TypeError, ValueError):
            pass
        pop = h.get("popularity") or fr.get("popularity")
        rows.append(
            f"<li class='hr{' mk' if num in mk else ''}{' top' if str(fin) in ('1', '2', '3') else ''}'>"
            f"<span class='c-no'><b class='fr f{esc(h.get('frame') or fr.get('frame') or frame_of(num, len(horses) or len(evals)))}'>{esc(num)}</b></span>"
            f"<span class='c-mk mark'>{esc(mk.get(num, ''))}</span>"
            f"<span class='c-nm'><b>{esc(h.get('name') or e.get('name'))}</b><small>{esc(h.get('jockey'))}{' ・' + esc(h.get('sex_age')) if h.get('sex_age') else ''}</small></span>"
            f"<span class='c-od'>{esc(odds) if odds else '-'}<small>{f'{esc(pop)}人気' if pop else ''}</small></span>"
            f"<span class='c-sc'>{esc(e.get('score')) if e.get('score') is not None else '-'}<small>{f'勝率{esc(wp)}%' if wp else ''}</small></span>"
            f"<span class='c-vl'>{val or '-'}{tag}</span>"
            f"<span class='c-fn'>{fin_txt}</span>"
            f"<span class='c-cm'>{esc(e.get('comment'))}</span></li>")
    hits = set()
    for x in sc.get("hits", []) or []:
        hits.add(" ".join(x.split()[:2]))
    bets = "".join(
        f"<li class='{'won' if f'{b['type']} {b['combo']}' in hits else ''}'>{esc(b['type'])} {esc(b['combo'])}</li>"
        for b in p.get("bets", []))
    marks_html = "".join(
        f"<div class='m'><b>{m}</b><span>{esc(n)} {esc(horse_name(p, n))}</span></div>"
        for m in ("◎", "〇", "▲") for n in [p.get("marks", {}).get(m)] if n is not None)
    sub = [p.get("marks", {}).get(m) for m in ("△", "☆")]
    subs = "　".join(f"{m}{'・'.join(str(x) for x in (v if isinstance(v, list) else [v]))}"
                    for m, v in zip(("△", "☆"), sub) if v)
    res_html = ""
    if sc and "stake" in sc and not sc.get("voided"):
        hit = sc["return"] > 0
        tg = 0 < sc["return"] < sc["stake"]
        res_html = (f"<section class='card'><h2>結果</h2><p>1〜3着：{esc(' - '.join(str(x) for x in top3))}"
                    f"／◎は{esc(sc.get('honmei_finish') or '-')}着</p>"
                    f"<p class='big {'tg' if tg else 'hit' if hit else 'miss'}'>{'的中（トリガミ：払戻が投資を下回る）' if tg else '的中' if hit else '不的中'}　投資{sc['stake']:,}円・払戻{sc['return']:,}円・"
                    f"このレースの回収率{roi_txt(sc['stake'], sc['return'])}（収支{sc['return'] - sc['stake']:+,}円）</p>"
                    + "".join(f"<p>{esc(x)}</p>" for x in sc.get("hits", []))
                    + (f"<p class='meta'>{esc(SCORE_UPDATED.get(date))}集計</p>" if SCORE_UPDATED.get(date) else "") + "</section>")
    bias_html = ""
    bz = bias_for(date, p)
    if bz:
        key, b = bz
        bias_html = (f"<section class='card bias'><h2>当日のトラックバイアス</h2><p class='big'>{esc(key)}：{esc(b['judgement'])}"
                     f"<span class='conf'>確度{esc(b['confidence'])}</span></p>"
                     f"<p class='meta'>{esc(len(b.get('races', [])))}レース（{esc(','.join(map(str, b.get('races', []))))}R）の1・2着馬から判定。"
                     f"先行{int(b['front_share'] * 100)}%・内枠{int(b['inner_share'] * 100)}%・外枠{int(b['outer_share'] * 100)}%"
                     f"（{esc(b['updated'])}時点の最新判定。予想に使った時点の判定は更新履歴を参照）。"
                     + ("<a href='/column/track-bias/'>トラックバイアスとは</a>" if HAS_COLUMN else "") + "</p></section>")
    updates = "".join(f"<li><b>{esc(u.get('at'))}</b> {esc(u.get('text'))}</li>" for u in p.get("updates", []))
    meta = "・".join(x for x in [
        fmt_date(date),
        f"{r['post_time']}発走" if r.get("post_time") else "",
        f"{r.get('surface') or ''}{r.get('distance')}m" if r.get("distance") else "",
        f"{r.get('field')}頭" if r.get("field") else ""] if x)
    prev, nxt = prev_next
    nav = "<nav class='pn'>" + (f"<a href='{race_path(date, prev)}'>← {esc(race_label(prev))}</a>" if prev else "<span></span>") + \
          (f"<a href='{race_path(date, nxt)}'>{esc(race_label(nxt))} →</a>" if nxt else "") + "</nav>"
    venue = venue_of(p)
    path = race_path(date, p)
    start = f"{date[:4]}-{date[4:6]}-{date[6:8]}" + (f"T{r['post_time']}:00+09:00" if r.get("post_time") else "")
    ld = [
        {"@context": "https://schema.org", "@type": "SportsEvent", "name": race_label(p), "sport": "競馬",
         "startDate": start, "eventStatus": "https://schema.org/EventScheduled",
         "location": {"@type": "Place", "name": f"{VENUE_NAME.get(venue, venue)}競馬場"},
         "description": answer_sentence(date, p), "url": BASE_URL + path},
        {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": SITE_NAME, "item": BASE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": f"{fmt_date(date)}の予想", "item": BASE_URL + day_path(date)},
            {"@type": "ListItem", "position": 3, "name": race_label(p), "item": BASE_URL + path}]},
    ]
    body = f"""
<p class="crumb"><a href="/">トップ</a> › <a href="{day_path(date)}">{fmt_date(date)}</a> › <a href="{venue_path(venue)}">{esc(VENUE_NAME.get(venue, venue))}</a> › {race_no(p)}R</p>
<h1>{esc(race_label(p))} 予想</h1><p class="meta">{esc(meta)}</p>
<p class="answer">{esc(answer_sentence(date, p))}</p>
<section class="card"><div class="marks">{marks_html}</div>{f"<p class='subs'>{esc(subs)}</p>" if subs else ''}
<p>自信度 <span class="conf c{esc(p.get('confidence'))}">{esc(p.get('confidence'))}</span></p>
<h2>結論</h2><p class="big">{esc(p.get('summary'))}</p>
<h3>買い目（各100円・計{len(p.get('bets', []))}点）</h3><ul class="bets">{bets or '<li>買い目なし</li>'}</ul></section>
{res_html}
<section class="card"><h2>展開予想</h2><p>{esc(p.get('pace'))}</p></section>
{bias_html}
<section class="card"><h2>全頭評価</h2>
<ul class="hl"><li class="hr hd"><span class="c-no">馬番</span><span class="c-mk">印</span><span class="c-nm">馬名・騎手</span><span class="c-od">単勝</span><span class="c-sc">評価点</span><span class="c-vl">妙味</span><span class="c-fn">着順</span><span class="c-cm">短評</span></li>{''.join(rows)}</ul>
<p class="meta">評価点は45点満点。妙味は「AIの想定勝率×単勝オッズ」で、1.2以上を妙味あり、0.8未満を過剰人気としている（オッズは取得時点のもの）。</p></section>
{f'<section class="card"><h2>更新履歴</h2><ul>{updates}</ul></section>' if updates else ''}
{nav}
"""
    hon = p.get("marks", {}).get("◎")
    title = f"{race_label(p)} 予想【{md(date)}】AI全頭評価・買い目と結果 | {SITE_NAME}"
    desc = answer_sentence(date, p) + " 全頭の評価点・短評と買い目を掲載。"
    return page(title, body, path, desc=desc, noindex=p.get("confidence") == "見送り", head_extra="".join(jsonld(x) for x in ld),
                og_image=race_og(date, p))


def race_og(date: str, p: dict) -> str:
    """直近 OG_DAYS 日のレースは専用の共有画像を作る。"""
    cutoff = (datetime.now(JST) - timedelta(days=OG_DAYS)).strftime("%Y%m%d")
    if date < cutoff:
        return "/og/default.jpg"
    r = p["_race"]
    rel = f"/og/{date}/{VENUE_SLUG.get(venue_of(p), 'venue')}-{race_no(p):02d}.jpg"
    marks = [] if p.get("confidence") == "見送り" else [
        (m, str(n), horse_name(p, n)) for m in ("◎", "〇", "▲") for n in [p.get("marks", {}).get(m)] if n is not None]
    sc = scored(p)
    res = None
    if sc and sc["stake"]:
        res = ((f"的中 回収率{roi_txt(sc['stake'], sc['return'])}", sc["return"] >= sc["stake"]) if sc["return"] else ("不的中", False))
    meta = "・".join(x for x in [f"{r['post_time']}発走" if r.get("post_time") else "",
                                f"{r.get('surface') or ''}{r.get('distance')}m" if r.get("distance") else "",
                                f"{r.get('field')}頭" if r.get("field") else ""] if x)
    og.race_image(OUT / rel.lstrip("/"), f"{fmt_date(date)} {VENUE_NAME.get(venue_of(p), venue_of(p))}",
                  f"{race_label(p)} AI予想", meta, marks, p.get("confidence") or "", res)
    return rel


def redirect_page(to: str) -> str:
    return (f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="robots" content="noindex">'
            f'<link rel="canonical" href="{BASE_URL}{to}"><meta http-equiv="refresh" content="0; url={to}">'
            f'<title>移動しました</title></head><body><a href="{to}">こちらへ移動しました</a></body></html>')


# ---------------- 一覧 ----------------
def race_item(date: str, p: dict) -> str:
    sc = scored(p)
    badge = ""
    if sc and sc["stake"]:
        if not sc["return"]:
            badge = f"<span class='res miss'>不的中 −{sc['stake']:,}円</span>"
        elif sc["return"] < sc["stake"]:
            badge = f"<span class='res tg'>的中（トリガミ）払戻{sc['return']:,}円・回収率{roi_txt(sc['stake'], sc['return'])}</span>"
        else:
            badge = f"<span class='res hit'>的中 払戻{sc['return']:,}円・回収率{roi_txt(sc['stake'], sc['return'])}</span>"
    hon = p.get("marks", {}).get("◎")
    hon_txt = "見送り" if p.get("confidence") == "見送り" else f"◎{hon} {horse_name(p, hon)}"
    pt = p["_race"].get("post_time") or ""
    return (f"<li data-conf='{esc(p.get('confidence'))}' data-venue='{esc(venue_of(p))}' data-post='{date}{pt.replace(':', '')}'>"
            f"<a href='{race_path(date, p)}'><span class='rt'>{esc(pt)}</span>"
            f"<span class='rno'>{esc(venue_of(p))}{race_no(p)}R</span><span class='hon'>{esc(hon_txt)}</span>"
            f"<span class='conf c{esc(p.get('confidence'))}'>{esc(p.get('confidence'))}</span>{badge}</a></li>")


def day_stats(preds: list[dict]) -> tuple[int, int]:
    done = [p["_score"] for p in preds if p.get("_score") and "stake" in p["_score"] and not p["_score"].get("voided")]
    return sum(s["stake"] for s in done), sum(s["return"] for s in done)


def filters(venues: list[str]) -> str:
    vb = "".join(f"<button data-venue='{esc(v)}'>{esc(VENUE_NAME.get(v, v))}</button>" for v in venues)
    return (f"<div class='filters' data-kind='venue'><button class='on' data-venue='all'>全場</button>{vb}</div>"
            "<div class='filters' data-kind='conf'><button class='on' data-conf='all'>全自信度</button><button data-conf='A'>A</button>"
            "<button data-conf='B'>B</button><button data-conf='C'>C</button><button data-conf='見送り'>見送り</button></div>")


def scoreboard(date: str, preds: list[dict]) -> str:
    """当日のここまでの成績（レースが確定するたびに更新）。"""
    bet = [p for p in preds if p.get("confidence") != "見送り"]
    done = [scored(p) for p in bet if scored(p)]
    if not done:
        return f"<section class='card live'><h2>当日の成績</h2><p>確定 0／{len(bet)}レース。最初のレースが確定すると、ここに的中と回収率が出る。</p></section>"
    st, rt = sum(s["stake"] for s in done), sum(s["return"] for s in done)
    hit = sum(1 for s in done if s["return"] > 0)
    win = sum(1 for s in done if str(s.get("honmei_finish")) == "1")
    top3 = sum(1 for s in done if str(s.get("honmei_finish")) in ("1", "2", "3"))
    rows = []
    for v in sorted({venue_of(p) for p in bet}):
        vb = [p for p in bet if venue_of(p) == v]
        vd = [scored(p) for p in vb if scored(p)]
        vs, vr = sum(s["stake"] for s in vd), sum(s["return"] for s in vd)
        rows.append(f"<tr><td>{esc(VENUE_NAME.get(v, v))}</td><td>{len(vd)}／{len(vb)}</td>"
                    f"<td>{sum(1 for s in vd if s['return'] > 0)}</td><td>{roi_txt(vs, vr)}</td><td>{vr - vs:+,}円</td></tr>")
    upd = SCORE_UPDATED.get(date)
    return (f"<section class='card live'><h2>当日の成績{f'（{esc(upd)}時点）' if upd else ''}</h2>"
            f"<div class='kpis'><div><b>{len(done)}／{len(bet)}</b><span>確定レース</span></div>"
            f"<div><b>{hit}</b><span>的中レース（{100 * hit / len(done):.0f}%）・うちプラス{sum(1 for s in done if s['return'] > s['stake'])}</span></div>"
            f"<div><b>{roi_txt(st, rt)}</b><span>当日回収率</span></div>"
            f"<div><b>{rt - st:+,}円</b><span>収支（投資{st:,}円）</span></div>"
            f"<div><b>{win}・{top3}</b><span>◎の1着・3着内</span></div></div>"
            f"<div class='scroll'><table><thead><tr><th>場</th><th>確定</th><th>的中</th><th>回収率</th><th>収支</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
            f"<p class='meta'>レースが確定するたびに自動で更新（数分おき）。各点100円の均等買い、見送りは除く。</p></section>")


def day_list(date: str, preds: list[dict]) -> str:
    venues = sorted({venue_of(p) for p in preds})
    return (scoreboard(date, preds) + filters(venues)
            + "<ul class='races'>" + "".join(race_item(date, p) for p in preds) + "</ul>")


# ---------------- 成績 ----------------
def svg_line(points: list[float], w=640, h=180, labels: list[str] | None = None) -> str:
    if len(points) < 2:
        return ""
    h_plot = h - 20 if labels else h
    lo, hi = min(points + [100]), max(points + [100])
    pad = (hi - lo) * 0.1 or 10
    lo, hi = lo - pad, hi + pad
    xs = [i * (w - 60) / (len(points) - 1) + 40 for i in range(len(points))]
    ys = [h_plot - 20 - (v - lo) / (hi - lo) * (h_plot - 40) for v in points]
    y100 = h_plot - 20 - (100 - lo) / (hi - lo) * (h_plot - 40)
    step = max(1, len(points) // 8)
    lab = "".join(f"<text x='{xs[i]:.1f}' y='{h - 4}' class='lbl mid'>{esc(labels[i])}</text>"
                  for i in range(0, len(points), step)) if labels else ""
    dots = "".join(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='2.5' class='pt'/>" for x, y in zip(xs, ys)) if len(points) <= 40 else ""
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(zip(xs, ys)))
    return (f"<svg viewBox='0 0 {w} {h}' class='chart' role='img' aria-label='累計回収率の推移'>"
            f"<line x1='30' x2='{w - 10}' y1='{y100:.1f}' y2='{y100:.1f}' class='base'/>"
            f"<text x='2' y='{y100 + 4:.1f}' class='lbl'>100%</text>"
            f"<path d='{path}' class='ln'/>{dots}{lab}<circle cx='{xs[-1]:.1f}' cy='{ys[-1]:.1f}' r='4' class='pt'/>"
            f"<text x='{xs[-1] - 4:.1f}' y='{ys[-1] - 8:.1f}' class='lbl end'>{points[-1]:.1f}%</text></svg>")


def totals(rows) -> dict:
    n = len(rows)
    st = sum(int(r["stake"]) for r in rows)
    rt = sum(int(r["return"]) for r in rows)
    return {"n": n, "stake": st, "ret": rt, "roi": roi_txt(st, rt),
            "win": f"{100 * sum(r['honmei_finish'] == '1' for r in rows) / n:.1f}%" if n else "―",
            "top3": f"{100 * sum(r['honmei_finish'] in ('1', '2', '3') for r in rows) / n:.1f}%" if n else "―",
            "hit": f"{100 * sum(int(r['return']) > 0 for r in rows) / n:.1f}%" if n else "―"}


def results_page(rows: list[dict], venue_of_race: dict) -> str:
    by_day = defaultdict(list)
    for r in rows:
        by_day[r["date"]].append(r)
    days = sorted(by_day)
    cum, cs, cr = [], 0, 0
    for d in days:
        cs += sum(int(r["stake"]) for r in by_day[d]); cr += sum(int(r["return"]) for r in by_day[d])
        cum.append(100 * cr / cs if cs else 100)
    t = totals(rows)
    asof = fmt_date(days[-1]) if days else ""

    def table(groups: dict, label: str, raw: bool = False) -> str:
        body = "".join(f"<tr><td>{k if raw else esc(k)}</td><td>{v['n']}</td><td>{v['roi']}</td><td>{v['hit']}</td><td>{v['win']}</td><td>{v['top3']}</td></tr>"
                       for k, v in groups.items())
        return (f"<table><thead><tr><th>{label}</th><th>レース</th><th>回収率</th><th>的中率</th><th>◎勝率</th><th>◎複勝率</th></tr></thead>"
                f"<tbody>{body}</tbody></table>")

    daily = {fmt_date(d): totals(by_day[d]) for d in sorted(by_day, reverse=True)}
    conf = defaultdict(list)
    ven = defaultdict(list)
    for r in rows:
        conf[r["confidence"] or "-"].append(r)
        ven[venue_of_race.get(r["race_id"], "-")].append(r)
    venue_link = lambda k: f"<a href='{venue_path(k)}'>{esc(VENUE_NAME.get(k, k))}</a>" if k in VENUE_SLUG else esc(k)
    body = f"""<h1>成績</h1>
<p class="answer">{SITE_NAME}のAI予想の成績は、{asof}時点で{t['n']}レース・累計回収率{t['roi']}（◎勝率{t['win']}、◎複勝率{t['top3']}）。外れも含めた全予想を、買い目各点100円の均等買いとして集計している。</p>
<div class="kpis"><div><b>{t['n']}</b><span>集計レース</span></div><div><b>{t['roi']}</b><span>累計回収率</span></div>
<div><b>{t['win']}</b><span>◎勝率</span></div><div><b>{t['top3']}</b><span>◎複勝率</span></div></div>
<section class="card"><h2>累計回収率の推移</h2>{svg_line(cum, labels=[md(d) for d in days]) or '<p>2日分以上たまると表示します。</p>'}</section>
<section class="card"><h2>自信度別</h2><div class="scroll">{table({k: totals(v) for k, v in sorted(conf.items())}, '自信度')}</div></section>
<section class="card"><h2>場別</h2><div class="scroll">{table({venue_link(k): totals(v) for k, v in sorted(ven.items(), key=lambda kv: -len(kv[1]))}, '場', raw=True)}</div></section>
<section class="card"><h2>券種別</h2>{column.stats(STATS_FROM)[1]["table_bets"]}</section>
<section class="card"><h2>日別</h2><div class="scroll">{table(daily, '日付')}</div></section>
<p class="meta">集計対象は自動運用を始めた2026年10月26日以降で、見送り（買い目なし）は除いている。全予想の記録（CSV）は<a href="{REPO}/blob/main/results_ledger.csv">GitHub</a>で公開している。</p>"""
    ld = {"@context": "https://schema.org", "@type": "Dataset", "name": f"{SITE_NAME} AI競馬予想 全成績",
          "description": "日本の競馬（JRA・地方）全レースのAI予想と結果・回収率の記録（各点100円の均等買い）",
          "url": BASE_URL + "/results/", "license": "https://creativecommons.org/licenses/by/4.0/",
          "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv",
                            "contentUrl": f"{REPO}/blob/main/results_ledger.csv"}]}
    return page(f"AI競馬予想の成績・回収率（{t['n']}レース累計{t['roi']}） | {SITE_NAME}", body, "/results/",
                desc=f"AI競馬予想の全成績。{asof}時点で{t['n']}レース、累計回収率{t['roi']}、◎勝率{t['win']}。自信度別・場別・日別の回収率。",
                head_extra=jsonld(ld))


# ---------------- 競馬場ページ ----------------
def venue_pages(by_date: dict, led: list[dict], venue_of_race: dict) -> dict[str, str]:
    """/venue/<slug>/：場ごとの成績・当日バイアスの履歴・最近の予想。{path: lastmod} を返す。"""
    groups = defaultdict(list)  # slug -> [(date, p)]
    for d, ps in by_date.items():
        for p in ps:
            v = venue_of(p)
            if v in VENUE_SLUG:
                groups[VENUE_SLUG[v]].append((d, p))
    out = {}
    for slug, items in groups.items():
        items.sort(key=lambda x: (x[0], x[1]["_race"].get("post_time") or ""), reverse=True)
        v = venue_of(items[0][1])
        name = VENUE_NAME.get(v, v)
        rows = [r for r in led if VENUE_SLUG.get(venue_of_race.get(r["race_id"], "")) == slug]
        t = totals(rows)
        dates = sorted({d for d, _ in items}, reverse=True)
        # バイアスの履歴
        brows = []
        for d in dates[:30]:
            for src in ("jra", "rakuten"):
                for key, b in ((load_json(ROOT / "data" / "bias" / f"{d}_{src}.json") or {}).get("bias") or {}).items():
                    if key.startswith(v):
                        brows.append(f"<tr><td><a href='{day_path(d)}'>{fmt_date(d)}</a></td><td>{esc(key)}</td><td>{esc(b['judgement'])}</td>"
                                     f"<td>{esc(b['confidence'])}</td><td>{int(b['front_share'] * 100)}%</td><td>{len(b.get('races', []))}</td></tr>")
        bias_html = ("<section class='card'><h2>当日バイアスの履歴</h2><div class='scroll'><table><thead><tr><th>日付</th><th>コース</th><th>判定</th><th>確度</th>"
                     "<th>連対馬の先行率</th><th>参照R</th></tr></thead><tbody>" + "".join(brows) + "</tbody></table></div>"
                     "<p class='meta'>その日に確定したレースの1・2着馬の4コーナー位置と馬番から判定（最終判定）。</p></section>") if brows else ""
        recent = []
        for d in dates[:3]:
            lis = "".join(race_item(d, p) for dd, p in sorted(items, key=lambda x: x[1]["_race"].get("post_time") or "") if dd == d)
            recent.append(f"<h3><a href='{day_path(d)}'>{fmt_date(d)}</a></h3><ul class='races'>{lis}</ul>")
        days_html = "".join(f"<li><a href='{day_path(d)}'><span>{fmt_date(d)}</span><span>{sum(1 for dd, _ in items if dd == d)}レース</span></a></li>"
                            for d in dates[3:30])
        path = f"/venue/{slug}/"
        lead = (f"{name}競馬のAI予想は、{fmt_date(dates[-1])}から{len(items)}レースを公開している。" +
                (f"成績は{t['n']}レース・回収率{t['roi']}、◎勝率{t['win']}・◎複勝率{t['top3']}（各点100円の均等買い、外れも含む）。" if t["n"] else "成績はレースの確定後に集計する。"))
        body = (f"<p class='crumb'><a href='/'>トップ</a> › <a href='/venue/'>競馬場</a> › {esc(name)}</p>"
                f"<h1>{esc(name)}競馬のAI予想と成績</h1><p class='answer'>{esc(lead)}</p>"
                f"<div class='kpis'><div><b>{t['n']}</b><span>集計レース</span></div><div><b>{t['roi']}</b><span>回収率</span></div>"
                f"<div><b>{t['hit']}</b><span>的中率</span></div><div><b>{t['top3']}</b><span>◎複勝率</span></div></div>"
                f"<section class='card'><h2>最近の予想</h2>{''.join(recent)}</section>{bias_html}"
                + (f"<section class='card'><h2>過去の開催日</h2><ul class='days'>{days_html}</ul></section>" if days_html else ""))
        ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": SITE_NAME, "item": BASE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": "競馬場", "item": BASE_URL + "/venue/"},
            {"@type": "ListItem", "position": 3, "name": name, "item": BASE_URL + path}]}
        write(path, page(f"{name}競馬のAI予想・回収率と当日バイアス | {SITE_NAME}", body, path,
                         desc=f"{name}競馬の全レースAI予想。{lead[:80]}", head_extra=jsonld(ld)))
        out[path] = f"{dates[0][:4]}-{dates[0][4:6]}-{dates[0][6:8]}"
    # 一覧
    lis = "".join(f"<li><a href='/venue/{slug}/'><span>{esc(VENUE_NAME.get(venue_of(items[0][1]), venue_of(items[0][1])))}</span>"
                  f"<span>{len(items)}レース</span></a></li>" for slug, items in sorted(groups.items(), key=lambda kv: -len(kv[1])))
    write("/venue/", page(f"競馬場別のAI予想と成績 | {SITE_NAME}",
                          f"<p class='crumb'><a href='/'>トップ</a> › 競馬場</p><h1>競馬場別のAI予想と成績</h1>"
                          f"<p class='answer'>中央・地方の各競馬場ごとに、AI予想・回収率・当日バイアスの履歴をまとめている。</p><ul class='days'>{lis}</ul>",
                          "/venue/", desc="競馬場ごとのAI予想・回収率・トラックバイアスの履歴。"))
    out["/venue/"] = max(out.values()) if out else None
    return out


# ---------------- 固定ページ ----------------
ABOUT = f"""<h1>予想の方法</h1>
<p class="answer">{SITE_NAME}は、AI（Anthropic社のClaude）が日本の中央競馬（JRA）と地方競馬の全レースを毎日予想し、外れも含めた全予想の回収率を公開するサイトである。</p>
<section class="card"><h2>更新のタイミング</h2><ul>
<li>前日夜：翌日の出馬表と各馬の近5走をもとに、午前に発走するレースを予想</li>
<li>当日昼：当日のオッズ・馬体重と、午前の結果から判定した馬場の傾向をもとに、午後のレースを予想（前日の予想も見直す）</li>
<li>各レースの確定後（数分おき）：結果と払戻を取り込み、的中と回収率を更新。全レース終了後に1日分を確定</li></ul></section>
<section class="card"><h2>評価の5軸（45点満点）</h2><ul>
<li>能力（×3）：直近5走のレースレベル、着差、時計。不利のあった走は内容で補正</li>
<li>条件適性（×2）：距離、コース、馬場状態、回り</li>
<li>展開利（×2）：想定ペースと脚質、枠順、当日の馬場の傾向</li>
<li>状態・ローテ（×1）：間隔、休み明け、馬体重</li>
<li>人的・その他（×1）：騎手、厩舎、斤量、血統</li></ul></section>
<section class="card"><h2>印・自信度・買い目</h2><p>評価点の上位に想定勝率を付け、「想定勝率×単勝オッズ」が1.2以上を妙味あり、0.8未満を過剰人気とする。印は◎（本命）〇（対抗）▲（単穴）△（連下）☆（穴）。自信度はA・B・C・見送りの4段階で、近走データが不足するレースは見送りとする。買い目は原則10点以内。</p></section>
<section class="card"><h2>よくある質問</h2>
<h3>回収率はどう計算していますか</h3><p>全予想の買い目を各点100円で買ったものとして、払戻の合計÷投資の合計で計算しています。外れたレースも除外しません。</p>
<h3>どのレースを予想していますか</h3><p>JRAと地方競馬の、その日に開催される全レースです。データが不足するレースは「見送り」として記録します。</p>
<h3>予想は後から変わりますか</h3><p>当日昼に、オッズや馬場の傾向を見て前日の予想を見直すことがあります。その場合は各レースページの「更新履歴」に変更理由を残します。発走後の変更はしません。</p></section>
<section class="card"><h2>データについて</h2><p>出馬表・オッズ・結果は主催者等の公開情報をもとにしている。正式な情報は必ず主催者の発表で確認してほしい。</p></section>"""

FAQ_LD = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
    {"@type": "Question", "name": "回収率はどう計算していますか",
     "acceptedAnswer": {"@type": "Answer", "text": "全予想の買い目を各点100円で買ったものとして、払戻の合計÷投資の合計で計算しています。外れたレースも除外しません。"}},
    {"@type": "Question", "name": "どのレースを予想していますか",
     "acceptedAnswer": {"@type": "Answer", "text": "JRAと地方競馬の、その日に開催される全レースです。データが不足するレースは見送りとして記録します。"}},
    {"@type": "Question", "name": "予想は後から変わりますか",
     "acceptedAnswer": {"@type": "Answer", "text": "当日昼にオッズや馬場の傾向を見て前日の予想を見直すことがあり、変更理由を更新履歴に残します。発走後の変更はしません。"}}]}

OPERATOR = f"""<h1>運営者情報</h1>
<section class="card"><table>
<tr><th>サイト名</th><td>{SITE_NAME}（{SITE_SUB}）</td></tr>
<tr><th>URL</th><td>{BASE_URL}/</td></tr>
<tr><th>運営</th><td>{SITE_NAME} 運営者（個人）</td></tr>
<tr><th>内容</th><td>AIによる競馬予想と、その成績（回収率）の記録・公開</td></tr>
<tr><th>予想の作成</th><td>AI（Anthropic社のClaude）が公開データをもとに作成。作成手順とプログラムは<a href="{REPO}">GitHub</a>で公開</td></tr>
<tr><th>お問い合わせ</th><td><a href="{REPO}/issues">GitHubのIssues</a>からご連絡ください</td></tr>
</table></section>
<section class="card"><h2>免責事項</h2><p>本サイトの予想・情報は正確性や完全性を保証するものではありません。本サイトの情報を利用して生じた損害について、運営者は責任を負いません。馬券の購入はご自身の判断と責任で行ってください。</p></section>"""

PRIVACY = f"""<h1>プライバシーポリシー</h1>
<section class="card"><h2>個人情報の取り扱い</h2><p>本サイトは、閲覧者の氏名やメールアドレスなどの個人情報を収集していません。お問い合わせの際にご提供いただいた情報は、回答のためにのみ使用します。</p></section>
<section class="card"><h2>アクセス解析・広告について</h2><p>本サイトでは、利用状況の把握のためにアクセス解析ツールを、また今後、広告配信やアフィリエイトプログラムを利用する場合があります。これらのサービスはCookie等を使用して閲覧情報を収集することがありますが、個人を特定する情報は含まれません。Cookieはブラウザの設定で無効にできます。</p></section>
<section class="card"><h2>広告の表記</h2><p>本サイトに掲載する広告・アフィリエイトリンクには、その旨を明記します。</p></section>
<section class="card"><h2>改定</h2><p>本ポリシーは必要に応じて改定することがあります。制定日：2026年10月27日</p></section>"""

CSS = """:root{--bg:#f6f5f1;--fg:#1d1d1b;--mut:#6b6a63;--card:#fff;--line:#e3e1d9;--acc:#1f6f4a;--hit:#c0392b;--miss:#8a8a85;--won:#fdecea}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ecebe6;--mut:#a3a29b;--card:#1e1e1c;--line:#33322e;--acc:#5fbf8c;--hit:#ff7a6b;--miss:#8a8a85;--won:#3a2422}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.7 "Hiragino Sans","Noto Sans JP",system-ui,sans-serif}
a{color:var(--acc);text-decoration:none}.wrap{max-width:960px;margin:0 auto;padding:0 16px}
.top{background:var(--card);border-bottom:1px solid var(--line)}.top .wrap{display:flex;flex-wrap:wrap;gap:8px 20px;align-items:center;justify-content:space-between;padding:12px 16px}
.logo{font-weight:700;color:var(--fg);display:flex;align-items:center;gap:10px;line-height:1.3}.logo span{display:flex;flex-direction:column}.logo img{border-radius:8px}.logo small{font-weight:400;font-size:12px;color:var(--mut)}
nav{display:flex;gap:16px;font-size:14px}
h1{font-size:24px;margin:20px 0 4px}h2{font-size:18px;margin:0 0 8px}h3{font-size:15px;margin:16px 0 6px}
.meta,.crumb{color:var(--mut);font-size:13px;margin:0 0 10px}.crumb{margin-top:12px}
.answer{background:var(--card);border-left:4px solid var(--acc);padding:10px 14px;margin:12px 0;border-radius:4px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0}
.big{font-size:17px;font-weight:600}.miss{color:var(--miss)}.hit{color:var(--hit);font-weight:700}
.marks{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;margin-bottom:8px}.marks .m{display:flex;gap:10px;align-items:center;border:1px solid var(--line);border-radius:8px;padding:8px 12px}
.marks b{font-size:22px;color:var(--acc)}.marks span{font-weight:600}.subs{color:var(--mut);margin:4px 0 8px}
.races{list-style:none;padding:0;margin:0;display:grid;gap:6px}.races a{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px;color:var(--fg)}
.races li.next a{border:2px solid var(--acc)}.races li.next .rt::after{content:" 次に発走";color:var(--acc);font-weight:700}
.races li.gone a{opacity:.85}.res{font-size:13px}.tg{color:#b7791f;font-weight:700}.res.wait{color:var(--mut)}.live .kpis{margin:8px 0}
.rno{font-weight:700;min-width:84px}.rt{color:var(--mut);font-size:13px;min-width:44px}.hon{flex:1;min-width:150px}
.conf{display:inline-block;min-width:28px;text-align:center;border-radius:4px;font-size:12px;font-weight:700;padding:0 6px;border:1px solid var(--line)}
.cA{background:#1f6f4a;color:#fff}.cB{background:#3f8f6a;color:#fff}.cC{background:#c9c6b8;color:#1d1d1b}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.scroll{overflow-x:auto}.horses th,.horses td:not(.cmt){white-space:nowrap}.horses .cmt{min-width:260px}.mark{font-weight:700;color:var(--acc)}tr.mk td{background:rgba(31,111,74,.06)}
.bets{display:flex;flex-wrap:wrap;gap:6px;list-style:none;padding:0}.bets li{border:1px solid var(--line);border-radius:6px;padding:2px 8px;font-size:14px}.bets li.won{background:var(--won);border-color:var(--hit);color:var(--hit);font-weight:700}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:16px 0}.kpis div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.kpis b{display:block;font-size:24px}.kpis span{color:var(--mut);font-size:13px}
.chart{width:100%;height:auto}.chart .ln{fill:none;stroke:var(--acc);stroke-width:2.5}.chart .base{stroke:var(--mut);stroke-dasharray:4 4}.chart .pt{fill:var(--acc)}.chart .lbl{fill:var(--mut);font-size:12px}.chart .end{text-anchor:end;fill:var(--fg)}.chart .mid{text-anchor:middle}
.filters{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}.filters button{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:16px;padding:3px 12px;font:inherit;font-size:13px;cursor:pointer}.filters button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.days{list-style:none;padding:0;display:grid;gap:6px}.days a{display:flex;justify-content:space-between;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px;color:var(--fg)}
.pn{display:flex;justify-content:space-between;gap:12px;margin:20px 0;font-size:14px}
.foot{color:var(--mut);font-size:12px;padding:24px 16px 40px}
.hl{list-style:none;padding:0;margin:0}.hr{display:grid;grid-template-columns:48px 28px minmax(150px,1.4fr) 70px 64px 76px 48px 2.2fr;gap:4px 10px;align-items:start;padding:8px 6px;border-bottom:1px solid var(--line);font-size:14px}
.hr small{display:block;color:var(--mut);font-size:12px;font-weight:400}.hr.hd{font-size:12px;color:var(--mut);font-weight:700;border-bottom:2px solid var(--line)}
.hr.mk{background:rgba(31,111,74,.06)}.hr.top .c-fn{color:var(--hit);font-weight:700}.c-cm{color:var(--fg);font-size:13px;line-height:1.6}
.fr{display:inline-block;min-width:28px;text-align:center;border-radius:4px;border:1px solid var(--line);padding:1px 4px}
.f1{background:#fff;color:#111}.f2{background:#222;color:#fff}.f3{background:#d33;color:#fff}.f4{background:#2a5bd7;color:#fff}.f5{background:#f2c200;color:#111}.f6{background:#1f8f4a;color:#fff}.f7{background:#f08a24;color:#111}.f8{background:#f4a6c6;color:#111}
.tag{display:inline-block;margin-left:4px;font-size:11px;border-radius:4px;padding:0 4px}.tag.good{background:var(--acc);color:#fff}.tag.bad{background:var(--line);color:var(--fg)}
.bias .conf{margin-left:8px;vertical-align:middle}
@media (max-width:720px){.hr.hd{display:none}.hr{grid-template-columns:40px 22px 1fr 1fr 1fr;grid-template-areas:"no mk nm nm fn" "no mk od sc vl" "cm cm cm cm cm";padding:10px 4px;gap:4px 8px}
.c-no{grid-area:no}.c-mk{grid-area:mk;font-size:18px}.c-nm{grid-area:nm}.c-fn{grid-area:fn;text-align:right}.c-od{grid-area:od}.c-sc{grid-area:sc}.c-vl{grid-area:vl;text-align:right}.c-cm{grid-area:cm}
.c-od::before{content:"単勝";display:block;color:var(--mut);font-size:11px}.c-sc::before{content:"評価点";display:block;color:var(--mut);font-size:11px}.c-vl::before{content:"妙味";display:block;color:var(--mut);font-size:11px}}
.col{line-height:1.85}.col .hero{width:100%;height:auto;border-radius:10px;margin:8px 0}.col h2{margin:28px 0 8px;padding-bottom:4px;border-bottom:2px solid var(--line)}.col table{margin:8px 0}
.note{background:var(--card);border:1px dashed var(--line);border-radius:8px;padding:8px 12px;font-size:14px;color:var(--mut)}
.draft{background:#fff4d6;color:#6b4e00;border-radius:6px;padding:6px 10px;font-size:13px;margin-top:12px}
.cols{list-style:none;padding:0;display:grid;gap:8px}.cols a{display:flex;flex-direction:column;gap:2px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px;color:var(--fg)}.cols span{color:var(--mut);font-size:13px}"""

JS = """(function(){
var st={venue:'all',conf:'all'};
function apply(){document.querySelectorAll('.races li').forEach(function(li){
 var ok=(st.venue==='all'||li.dataset.venue===st.venue)&&(st.conf==='all'||li.dataset.conf===st.conf);li.style.display=ok?'':'none';});}
document.querySelectorAll('.filters').forEach(function(f){f.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;
 f.querySelectorAll('button').forEach(function(x){x.classList.toggle('on',x===b)});var k=f.dataset.kind;st[k]=b.dataset[k];apply();});});
var now=new Date(Date.now()+9*3600e3),s=now.toISOString().replace(/[-:T]/g,'').slice(0,12),first=null;
document.querySelectorAll('.races li[data-post]').forEach(function(li){var p=li.dataset.post;if(p.length<12)return;
 if(p<=s){li.classList.add('gone');if(!li.querySelector('.res')&&li.dataset.conf!=='見送り'){var w=document.createElement('span');w.className='res wait';w.textContent='結果待ち';li.querySelector('a').appendChild(w);}}else if(!first){first=li;}});
if(first&&document.body.contains(first)&&document.querySelector('.today')){first.classList.add('next');}
})();"""


def build() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    (OUT / "style.css").write_text(CSS, encoding="utf-8")
    (OUT / "app.js").write_text(JS, encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    if ASSETS.exists():
        shutil.copytree(ASSETS, OUT / "assets", ignore=shutil.ignore_patterns("og-base.png", "src"))
    og.site_image(OUT / "og" / "default.jpg", "全レースAI予想と回収率の記録",
                  ["中央競馬・地方競馬の全レースを毎日予想", "外れも含めた全成績を公開"])
    now = datetime.now(JST)
    today = now.strftime("%Y%m%d")
    dates = all_dates()
    lastmod: dict[str, str] = {}
    venue_of_race: dict[str, str] = {}
    day_rows = []
    by_date = {}
    for d in dates:
        ps = predictions(d)
        by_date[d] = ps
        for i, p in enumerate(ps):
            venue_of_race[p["race_id"]] = venue_of(p)
            same = [q for q in ps if venue_of(q) == venue_of(p)]
            j = same.index(p)
            pn = (same[j - 1] if j > 0 else None, same[j + 1] if j + 1 < len(same) else None)
            path = race_path(d, p)
            write(path, race_page(d, p, pn))
            write(f"/races/{d}/{p['race_id']}.html", redirect_page(path))
            if p.get("confidence") != "見送り":
                lastmod[path] = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        st, rt = day_stats(ps)
        day_rows.append((d, len(ps), roi_txt(st, rt)))
        write(day_path(d), page(f"{fmt_date(d)}の競馬AI予想 全{len(ps)}レース | {SITE_NAME}",
                                f"<p class='crumb'><a href='/'>トップ</a> › {fmt_date(d)}</p><h1>{fmt_date(d)}のAI予想</h1>"
                                f"<p class='answer'>{fmt_date(d)}は{len({venue_of(p) for p in ps})}場・{len(ps)}レースを予想。当日回収率は{roi_txt(st, rt)}。</p>"
                                + day_list(d, ps), day_path(d),
                                desc=f"{fmt_date(d)}の競馬（JRA・地方）全{len(ps)}レースのAI予想と結果。当日回収率{roi_txt(st, rt)}。"))
        lastmod[day_path(d)] = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    # トップ：今日（無ければ最新日）を中心に
    led = ledger()
    t = totals(led)
    main_d = today if today in by_date else (dates[0] if dates else None)
    if main_d:
        head = "今日の全レースAI予想" if main_d == today else f"{fmt_date(main_d)}の全レースAI予想"
        top_list = f"<section class='today'><h2>{fmt_date(main_d)}</h2>{day_list(main_d, by_date[main_d])}</section>"
    else:
        head, top_list = "今日の全レースAI予想", "<p>予想はまだありません。</p>"
    past = "".join(f"<li><a href='{day_path(d)}'><span>{fmt_date(d)}（{n}レース）</span><span>回収率 {roi}</span></a></li>"
                   for d, n, roi in day_rows if d != main_d)
    body = (f"<h1>{head}</h1>"
            f"<p class='answer'>AIが日本の競馬（JRA・地方）の全レースを毎日予想し、外れも含めた成績を公開している。累計回収率は{t['roi']}（{t['n']}レース、◎複勝率{t['top3']}）。<a href='/results/'>成績の詳細</a></p>"
            f"<p class='meta'>最終更新 {now.strftime('%Y-%m-%d %H:%M')}</p>"
            + top_list + (f"<section><h2>過去の予想</h2><ul class='days'>{past}</ul></section>" if past else ""))
    write("/", page(f"{SITE_NAME}｜今日の競馬AI予想（JRA・地方 全レース）と回収率", body, "/",
                    desc=f"AIが中央競馬・地方競馬の全レースを毎日予想。今日の予想と、外れも含めた全成績（累計回収率{t['roi']}）を公開。"))
    write("/results/", results_page(led, venue_of_race))
    lastmod.update(venue_pages(by_date, led, venue_of_race))
    write("/about/", page(f"予想の方法とよくある質問 | {SITE_NAME}", ABOUT, "/about/", head_extra=jsonld(FAQ_LD),
                          desc="AI競馬ログの予想の作り方（評価の5軸・印・自信度・買い目）と、回収率の計算方法。"))
    write("/operator/", page(f"運営者情報 | {SITE_NAME}", OPERATOR, "/operator/"))
    write("/privacy/", page(f"プライバシーポリシー | {SITE_NAME}", PRIVACY, "/privacy/"))
    today_iso = now.strftime("%Y-%m-%d")
    lastmod.update(column.build(write, page, jsonld, BASE_URL, SITE_NAME, STATS_FROM, today_iso))
    for old, new in (("results.html", "/results/"), ("about.html", "/about/")):
        (OUT / old).write_text(redirect_page(new), encoding="utf-8")
    write("/404.html", page(f"ページが見つかりません | {SITE_NAME}",
                            "<h1>ページが見つかりません</h1><p class='answer'>URLが変わったか、削除された可能性がある。</p>"
                            "<ul><li><a href='/'>今日の予想</a></li><li><a href='/results/'>成績</a></li><li><a href='/venue/'>競馬場別</a></li></ul>",
                            "/404.html", noindex=True))
    items = []
    for d, n, roi in day_rows[:30]:
        items.append(f"<item><title>{esc(fmt_date(d))}の競馬AI予想（{n}レース・回収率{esc(roi)}）</title>"
                     f"<link>{BASE_URL}{day_path(d)}</link><guid>{BASE_URL}{day_path(d)}</guid>"
                     f"<pubDate>{datetime.strptime(d, '%Y%m%d').replace(tzinfo=JST, hour=9).strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate>"
                     f"<description>{esc(fmt_date(d))}の中央・地方全{n}レースのAI予想と結果。当日回収率{esc(roi)}。</description></item>")
    (OUT / "feed.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>{SITE_NAME}</title><link>{BASE_URL}/</link><description>{SITE_SUB}</description><language>ja</language>"
        + "".join(items) + "</channel></rss>\n", encoding="utf-8")
    (OUT / "CNAME").write_text(DOMAIN + "\n", encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n", encoding="utf-8")
    (OUT / "llms.txt").write_text(
        f"# {SITE_NAME}\n\n> AI（Claude）が日本の競馬（JRA・地方）の全レースを毎日予想し、外れも含めた全予想の回収率を公開するサイト。\n\n"
        f"- [今日の予想]({BASE_URL}/)\n- [成績・回収率]({BASE_URL}/results/)：累計{t['n']}レース・回収率{t['roi']}\n"
        f"- [予想の方法]({BASE_URL}/about/)\n" + (f"- [初心者向けコラム]({BASE_URL}/column/)：馬券の種類・回収率・人気と勝率などを実データで解説\n" if HAS_COLUMN else "") + f"- [全予想の記録CSV]({REPO}/blob/main/results_ledger.csv)\n", encoding="utf-8")
    fixed = {"/": today_iso, "/results/": today_iso, "/about/": None, "/operator/": None, "/privacy/": None}
    sm = "".join(f"<url><loc>{BASE_URL}{u}</loc>{f'<lastmod>{m}</lastmod>' if m else ''}</url>"
                 for u, m in list(fixed.items()) + sorted(lastmod.items(), reverse=True))
    (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + sm + "</urlset>\n", encoding="utf-8")
    print(f"built {len(dates)} days into {OUT}")


if __name__ == "__main__":
    build()
