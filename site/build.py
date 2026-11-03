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
import extra
import og
import strategy
import review
import horses
import monthly

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"
SITE_NAME = "競馬全頭ログ"
X_URL = "https://x.com/zentou_log"
IG_URL = "https://www.instagram.com/zentou_log/"
OFUSE_URL = "https://ofuse.me/zentou_log"
CONTACT_MAIL = "keibalog.kouho@gmail.com"
GA_ID = "G-MFLTSL1RVP"
ADSENSE_PUB = "ca-pub-2715397557499691"
ADSENSE_TAG = f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_PUB}" crossorigin="anonymous"></script>'
GA_TAG = (f'<script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script>'
          f"<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('js',new Date());gtag('config','{GA_ID}');</script>")
SITE_SUB = "中央・地方の全レースを毎日予想。外れも含めて、全部記録する。"
DOMAIN = "www.ai-keiba-log.com"
BASE_URL = f"https://{DOMAIN}"
REPO = "https://github.com/bunbunbunzai/keiba-ai"
JST = timezone(timedelta(hours=9))
MARKS = ["◎", "〇", "▲", "△", "☆"]
# アフィリエイト（TGアフィリエイト・楽天競馬）。リンクIDはTG管理画面で発行したもの
AFF_RAKUTEN = "https://ad2.trafficgate.net/t/r/{id}/1958/319633_399587"
AFF_RAKUTEN_IMG = "https://srv2.trafficgate.net/t/b/{id}/1958/319633_399587"


AFF_SAIKYO_URL = "https://px.a8.net/svt/ejp?a8mat=4BE9CR+9T22IA+47AY+601S1"
AFF_SAIKYO_IMG = "https://www20.a8.net/svt/bgt?aid=261005787593&wid=001&eno=01&mid=s00000019609001008000&mc=1"
AFF_SAIKYO_PX = "https://www10.a8.net/0.gif?a8mat=4BE9CR+9T22IA+47AY+601S1"
AFF_SAIKYO_TXT_URL = "https://px.a8.net/svt/ejp?a8mat=4BE9CR+9T22IA+47AY+61Z82"
AFF_SAIKYO_TXT_PX = "https://www14.a8.net/0.gif?a8mat=4BE9CR+9T22IA+47AY+61Z82"


def aff_saikyo() -> str:
    """競馬最強の法則WEB（A8）：コラム末尾用。人間の予想家と比べたい人向けの文脈で置く。"""
    return (f"<div class='aff affbox saikyo'><span class='pr'>PR</span><p>AIの予想と人間の予想家の見解を比べたい人には、競馬雑誌「競馬最強の法則」の予想情報サイト"
            f"<a href='{AFF_SAIKYO_TXT_URL}' target='_blank' rel='nofollow sponsored noopener' data-aff='saikyo-web'>競馬最強の法則WEB</a>（無料会員登録あり）がある。"
            f"AI予想を読むときの比較材料として使ってほしい。</p>"
            f"<a href='{AFF_SAIKYO_URL}' target='_blank' rel='nofollow sponsored noopener' data-aff='saikyo-web-banner'><img src='{AFF_SAIKYO_IMG}' alt='競馬最強の法則WEB' width='300' height='250' loading='lazy'></a>"
            f"<img src='{AFF_SAIKYO_PX}' alt='' width='1' height='1' style='position:absolute;width:1px;height:1px'>"
            f"<img src='{AFF_SAIKYO_TXT_PX}' alt='' width='1' height='1' style='position:absolute;width:1px;height:1px'></div>")


def aff_rakuten(kind: str = "race") -> str:
    """楽天競馬への導線。race：買い目の下の1行、venue：場ページ、column：コラム末尾（バナー）。"""
    a = f"<a href='{AFF_RAKUTEN.format(id=14)}' target='_blank' rel='nofollow sponsored noopener' data-aff='rakuten-keiba'>楽天競馬</a>"
    if kind == "race":
        return f"<p class='aff'><span class='pr'>PR</span>この買い目は{a}で買える。地方競馬全場に対応、登録無料、馬券購入で楽天ポイントが貯まる。</p>"
    if kind == "venue":
        return f"<p class='aff'><span class='pr'>PR</span>この場の馬券は{a}（地方競馬全場・登録無料）でネット購入できる。</p>"
    return (f"<div class='aff affbox'><span class='pr'>PR</span><p>地方競馬の馬券をネットで買うなら{a}。全15場（ばんえい含む）に対応し、登録無料。楽天銀行なら入出金が即時で、購入額に応じて楽天ポイントが貯まる。</p>"
            f"<a href='{AFF_RAKUTEN.format(id=70)}' target='_blank' rel='nofollow sponsored noopener' data-aff='rakuten-keiba-banner'><img src='{AFF_RAKUTEN_IMG.format(id=70)}' alt='楽天競馬' width='728' height='90' loading='lazy'></a></div>")
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


GLOSSARY = [
    ("mark", "印（◎〇▲△☆）", "予想の評価順。◎は本命（1着候補の筆頭）、〇は対抗、▲は単穴（展開次第で勝てる馬）、△は連下（2〜3着候補）、☆は穴（人気薄で一発がある馬）。"),
    ("score", "評価点", "能力・条件適性・展開利・状態・人的要素の5軸を1〜5点で採点し、重みを付けて合計した45点満点の点数。印はこの点数と人気を見て決める。"),
    ("winpct", "想定勝率", "AIがその馬が勝つと見積もった確率（%）。評価点の上位6頭程度に付け、合計は100%以内。自信度はこの数字で決まる。"),
    ("value", "妙味・期待値", "想定勝率×単勝オッズ。1.2以上なら「オッズがAIの見立てより高い（妙味あり）」、0.8未満なら「過剰人気」。買い目の選定より、◎の候補を絞るときに使う。"),
    ("confidence", "自信度", "◎の想定勝率による区分。A＝40%以上、B＝30〜39%、C＝30%未満。「見送り」は近走データが足りないレースで、買い目を出さない。"),
    ("pace", "展開利", "逃げ・先行・差し・追い込みの脚質と、想定ペース・枠順・当日の馬場傾向の組み合わせで、その馬に有利かどうかの見立て。"),
    ("bias", "トラックバイアス", "その日の馬場で、先行馬が残りやすいか、内枠が有利かなどの偏り。当日の午前の確定結果から判定し、午後の予想に反映する。"),
    ("roi", "回収率", "払戻金の合計÷購入金額の合計×100（%）。100%を超えれば勝ち。このサイトは外れたレースも除外せず、各点100円の均等買いで集計する。"),
    ("torigami", "トリガミ", "馬券は当たったが、払戻が買った金額を下回ること。「的中」でも収支はマイナス。"),
    ("formation", "3連複フォーメーション", "1頭目◎、2頭目〇▲、3頭目は印全部、という組み合わせの3連複。このサイトの標準の買い目（2026年11月2日から）。"),
    ("tanpuku", "単複の切り替え", "◎の単勝か複勝かを人気で決める方式。1〜2番人気は複勝、3〜5番人気は単勝、6番人気以下は買わない。"),
]
GLOSSARY_ID = {k: t for k, t, _ in GLOSSARY}


def term(key: str, label: str | None = None) -> str:
    """用語に用語集へのリンクと、タップで出る短い説明を付ける。"""
    for k, t, d in GLOSSARY:
        if k == key:
            return f"<a class='term' href='/glossary/#{k}' title='{esc(d[:70])}'>{esc(label or t)}</a>"
    return esc(label or key)


def banner(slug: str, alt: str = "") -> str:
    """ページ見出し用の挿絵（site/assets/ban-<slug>.jpg があるときだけ）。"""
    f = ASSETS / f"ban-{slug}.jpg"
    if not f.exists():
        return ""
    return f"<div class='banner'><img src='/assets/ban-{slug}.jpg' alt='{esc(alt)}' width='1600' height='580' loading='lazy'></div>"


def page(title: str, body: str, path: str, desc: str = "", noindex: bool = False, head_extra: str = "",
         og_image: str = "/og/default.jpg") -> str:
    d = desc or "AIが日本の競馬（JRA・地方）の全レースを毎日予想し、外れも含めた全予想の回収率を公開しています。"
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
{GA_TAG}
{ADSENSE_TAG}
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(d)}">
<link rel="canonical" href="{BASE_URL}{path}">
{'<meta name="robots" content="noindex">' if noindex else ''}
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(d)}">
<meta property="og:url" content="{BASE_URL}{path}"><meta property="og:type" content="website"><meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:image" content="{BASE_URL}{og_image}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="{BASE_URL}{og_image}">
<meta name="theme-color" content="#146b45"><link rel="manifest" href="/manifest.webmanifest">
{FAVICON}<link rel="alternate" type="application/rss+xml" title="{SITE_NAME}" href="/feed.xml">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=BIZ+UDPGothic:wght@400;700&family=Shippori+Mincho+B1:wght@700;800&display=swap">
<link rel="stylesheet" href="/style.css?v={ASSET_V}">
{head_extra}
</head><body data-built="{BUILT_ISO}">
<a class="skip" href="#main">本文へ</a>
<header class="top"><div class="wrap">
<div class="bar"><a class="logo" href="/">{'<img src="/assets/logo-mark-96.png" alt="" width="44" height="44">' if LOGO else ''}<span><b>{SITE_NAME}</b><small>{SITE_SUB}</small></span></a>{HEADER_ROI}</div>
<form class="srch" action="/search/" role="search"><input type="search" name="q" placeholder="馬名・レース名で検索" aria-label="サイト内検索" autocomplete="off"><div class="sres" hidden></div></form>
<nav><a href="/">今日の予想</a><a href="/graded/">重賞</a><a href="/results/">成績</a><a href="/strategy/">買い方別</a><a href="/venue/">競馬場</a>{'<a href="/column/">コラム</a>' if HAS_COLUMN else ''}<a href="/about/">予想の方法</a></nav>
</div></header>
<main class="wrap" id="main">{body}</main>
<a class="totop" href="#main" hidden aria-label="ページの先頭へ">↑</a>
<footer class="wrap foot">
<p>本サイトの予想は情報提供を目的としたもので、的中や利益を保証するものではありません。馬券の購入はご自身の判断と責任で行ってください。20歳未満の方は馬券を購入できません。</p>
<p>レース情報は主催者の発表が正です。成績は全予想を各点100円の均等買いとして集計しています。</p>
<p class="support">このサイトは個人が運営しています。サーバー代やX投稿のAPI代の支援は <a href="{OFUSE_URL}" target="_blank" rel="noopener">OFUSE（投げ銭・ファンレター）</a> から。支援の有無で予想の内容や公開範囲は変わりません。</p>
<p class="sns">最新の予想と的中速報は <a href="{X_URL}" target="_blank" rel="noopener me">X（@zentou_log）</a>・<a href="{IG_URL}" target="_blank" rel="noopener me">Instagram</a> でも配信中</p>
<p class="sitemap-links"><a href="/graded/">重賞</a>　<a href="/review/">重賞回顧</a>　<a href="/monthly/">月次レポート</a>　<a href="/strategy/">買い方別の回収率</a>　<a href="/course/">コース別</a>　<a href="/jockey/">騎手別</a>　<a href="/horse/">馬別</a>　<a href="/column/">コラム</a>　<a href="/glossary/">用語集</a>　<a href="/limits/">AI予想の限界</a>　<a href="/changelog/">更新履歴</a></p>
<p class="prefs"><button type="button" class="theme" data-mode="auto">表示：自動</button></p>
<p><a href="/operator/">運営者情報</a>　<a href="/privacy/">プライバシーポリシー</a>　<a href="/contact/">お問い合わせ</a></p>
</footer>
<script src="/app.js?v={ASSET_V}"></script>
</body></html>"""


FAVICON = ('<link rel="icon" href="/assets/favicon.png" type="image/png"><link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">'
           if (ASSETS / "favicon.png").exists() else "")
LOGO = (ASSETS / "logo-mark.png").exists()
HEADER_ROI = ""  # build() の最初に設定（今月の回収率。外れも含む）
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


TODAY = ""
BUILT_ISO = ""
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
            f"<span class='c-nm'><b>{link_horse(h.get('name') or e.get('name'))}</b><small>{link_jockey(h.get('jockey'))}{' ・' + esc(h.get('sex_age')) if h.get('sex_age') else ''}</small></span>"
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
    gname0 = p.get("race_name") or r.get("race_name") or r.get("title_text") or ""
    g0 = extra.grade_of(r, gname0)
    graded_link = ""
    if g0:
        gslug = extra.graded_slug(gname0, VENUE_SLUG.get(venue_of(p), "venue"))
        graded_link = (f"<p class='meta'>{esc(extra.clean_name(gname0))}の過去のAI予想と結果は"
                       f"<a href='/graded/{gslug}/'>{esc(extra.clean_name(gname0))} AI予想まとめ</a>へ。</p>")
    # シェア
    from urllib.parse import quote
    share_text = answer_sentence(date, p)
    tags = "競馬予想,AI予想" + (f",{extra.clean_name(gname0).replace('(', '').replace(')', '')}" if g0 else "")
    url = BASE_URL + race_path(date, p)
    share_html = (f"<div class='share'><a href='https://twitter.com/intent/tweet?text={quote(share_text[:110])}&url={quote(url)}&hashtags={quote(tags)}' target='_blank' rel='noopener'>Xでシェア</a>"
                  f"<a href='https://social-plugins.line.me/lineit/share?url={quote(url)}' target='_blank' rel='noopener'>LINEで送る</a></div>")
    # AI vs あなた（発走前だけ選べる。結果が出たら勝敗を表示）
    vs_html = ""
    hon = p.get("marks", {}).get("◎")
    if p.get("confidence") != "見送り" and horses:
        fin_map = {str(x.get("number")): str(x.get("finish")) for x in (p.get("_result") or {}).get("rows", []) or [] if x.get("number") is not None}
        opts = "".join(f"<option value='{n}'>{n} {esc(h.get('name'))}</option>" for n, h in sorted(horses.items(), key=lambda kv: (kv[0] is None, kv[0])) if n is not None)
        post = f"{date}{(r.get('post_time') or '23:59').replace(':', '')}"
        vs_html = (f"<section class='card vs' data-key='vs:{date}:{race_path(date, p)}' data-post='{post}' data-ai='{esc(hon)}' "
                   f"data-fin='{esc(json.dumps(fin_map))}' data-url='{esc(url)}' data-label='{esc(race_label(p))}'>"
                   f"<h2>AI vs あなた</h2><p class='meta'>あなたの◎を1頭選んで、AIの◎（{esc(hon)}番）と勝負。発走前まで選べる（この端末だけに保存）。</p>"
                   f"<div class='pick'><select><option value=''>馬を選ぶ</option>{opts}</select> <button type='button' class='go'>この馬に決める</button></div>"
                   f"<p class='r'></p><p class='meta'><a href='/me/'>あなたの成績（累計）を見る</a></p></section>")
    bias_html = ""
    bz = bias_for(date, p)
    if bz:
        key, b = bz
        bias_html = (f"<section class='card bias'><h2>当日の{term('bias', 'トラックバイアス')}</h2><p class='big'>{esc(key)}：{esc(b['judgement'])}"
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
<h1>{esc(race_label(p))} 予想</h1><p class="meta">{esc(meta)}{course_link(p)}</p>
<p class="answer">{esc(answer_sentence(date, p))}</p>
<section class="card"><div class="marks">{marks_html}</div>{f"<p class='subs'>{esc(subs)}</p>" if subs else ''}
<p>{term("confidence", "自信度")} <span class="conf c{esc(p.get('confidence'))}">{esc(p.get('confidence'))}</span></p>
<h2>結論</h2>{plain_line(p)}<p class="sum">{esc(p.get('summary'))}</p>
<h3>買い目（各100円・計{len(p.get('bets', []))}点）</h3><ul class="bets">{bets or '<li>買い目なし</li>'}</ul>{aff_rakuten('race') if not str(p['race_id']).startswith('jra_') and p.get('confidence') != '見送り' else ''}</section>
{res_html}
<section class="card"><h2>{term("pace", "展開予想")}</h2><p>{esc(p.get('pace'))}</p></section>
{bias_html}
<section class="card"><h2>全頭評価</h2>
<ul class="hl"><li class="hr hd"><span class="c-no">馬番</span><span class="c-mk">印</span><span class="c-nm">馬名・騎手</span><span class="c-od">単勝</span><span class="c-sc">評価点</span><span class="c-vl">妙味</span><span class="c-fn">着順</span><span class="c-cm">短評</span></li>{''.join(rows)}</ul>
<p class="meta">{term("score", "評価点")}は45点満点。{term("value", "妙味")}は「AIの{term("winpct", "想定勝率")}×単勝オッズ」で、1.2以上を妙味あり、0.8未満を過剰人気としている（オッズは取得時点のもの）。用語は<a href="/glossary/">用語集</a>へ。</p></section>
{f'<section class="card"><h2>更新履歴</h2><ul>{updates}</ul></section>' if updates else ''}
{graded_link}
{vs_html}
{share_html}
{nav}
"""
    hon = p.get("marks", {}).get("◎")
    title = f"{race_label(p)} 予想【{md(date)}】AI全頭評価・買い目と結果 | {SITE_NAME}"
    gname = p.get("race_name") or r.get("race_name") or r.get("title_text") or ""
    g = extra.grade_of(r, gname)
    if g:
        cn = extra.clean_name(gname)
        title = f"【AI予想】{cn}{date[:4]}（{g}） 全頭診断と買い目｜{SITE_NAME}"
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
GRADE_CLASS = {"G1": "g1", "G2": "g2", "G3": "g3", "J・G1": "g1", "J・G2": "g2", "J・G3": "g3", "L": "gl"}


def grade_badge(p: dict) -> str:
    g = extra.grade_of(p["_race"], p.get("race_name") or p["_race"].get("race_name") or "")
    if not g:
        return ""
    cls = GRADE_CLASS.get(g, "gj")
    return f"<span class='gr {cls}'>{esc(g)}</span>"


def race_short(p: dict, n: int = 18) -> str:
    """一覧用の短いレース名（重賞は正式名、それ以外は条件名を切り詰め）。"""
    name = p.get("race_name") or p["_race"].get("race_name") or p["_race"].get("title_text") or ""
    name = " ".join(extra.nfkc(name).split())
    g = extra.grade_of(p["_race"], name)
    if g:
        name = extra.clean_name(name)
    return name[:n] + ("…" if len(name) > n else "")


def race_cond(p: dict) -> str:
    r = p["_race"]
    return " ".join(x for x in (f"{r.get('surface') or ''}{r.get('distance')}m" if r.get("distance") else "",
                                f"{r.get('field')}頭" if r.get("field") else "") if x)


ALL_DATES: list[str] = []
LINK_HORSES: set = set()
LINK_JOCKEYS: set = set()
LINK_COURSES: set = set()
FEED_EXTRA: list = []
VENUE_PIC = {"東京": "turf", "京都": "turf", "中山": "turf", "阪神": "turf", "新潟": "turf", "福島": "turf", "中京": "turf", "小倉": "turf", "札幌": "turf", "函館": "turf", "帯広": "banei"}


def date_tabs(date: str) -> str:
    """前日・当日・翌日の切り替え（予想がある日だけ）。"""
    ds = sorted(ALL_DATES)
    if date not in ds:
        return ""
    i = ds.index(date)
    items = []
    for d in ds[max(0, i - 2): i + 2]:
        href = "/" if d == TODAY else day_path(d)
        lbl = f"{int(d[4:6])}/{int(d[6:8])}({'月火水木金土日'[datetime(int(d[:4]), int(d[4:6]), int(d[6:8])).weekday()]})"
        items.append(f"<a href='{href}' class='{'on' if d == date else ''}'>{esc(lbl)}{'<small>今日</small>' if d == TODAY else ''}</a>")
    return f"<nav class='dtabs'>{''.join(items)}<a href='/#past' class='more'>過去の日付</a></nav>"


def hero(date: str, preds: list[dict]) -> tuple[str, str | None]:
    """その日の目玉レース：発走前の重賞があればそれ、無ければ勝負レースの1位。"""
    cand = [p for p in preds if p.get("confidence") != "見送り" and extra.grade_of(p["_race"], p.get("race_name") or p["_race"].get("race_name") or "")]
    cand = [p for p in cand if not scored(p)] or cand
    pk = picks(preds, 1)
    p = (sorted(cand, key=lambda q: q["_race"].get("post_time") or "99")[0] if cand else (pk[0] if pk else None))
    if not p:
        return "", None
    hon = p["marks"].get("◎")
    if hon is None:
        return "", None
    r = p["_race"]
    sc = scored(p)
    wp, od, val = honmei_value(p)
    marks = "".join(f"<span><b>{m}</b>{p['marks'][m]} {esc(horse_name(p, p['marks'][m]))}</span>" for m in ("◎", "〇", "▲") if p["marks"].get(m) is not None)
    if sc and sc["stake"]:
        top = "-".join(str(x) for x in sc.get("top3", []) if x is not None)
        res = (f"<p class='hres {'hit' if sc['return'] >= sc['stake'] else 'tg' if sc['return'] else 'miss'}'>結果 {esc(top)}　"
               f"{'的中' if sc['return'] else '不的中'}　回収率{roi_txt(sc['stake'], sc['return'])}</p>")
    else:
        res = f"<p class='hres'>{esc(r.get('post_time') or '')}発走" + (f"　想定勝率{wp:.0f}%" if wp is not None else "") + (f"　単勝{od:.1f}倍" if od else "") + "</p>"
    img = race_og(date, p)
    lbl = "今日の重賞" if (extra.grade_of(r, p.get("race_name") or r.get("race_name") or "") and date == TODAY) else "注目レース" if extra.grade_of(r, p.get("race_name") or r.get("race_name") or "") else "今日の勝負レース" if date == TODAY else "この日の勝負レース"
    return (f"<section class='hero'><a href='{race_path(date, p)}'><img src='{img}' alt='' width='600' height='315' loading='eager'></a>"
            f"<div class='hbody'><p class='hlabel'>{lbl}{grade_badge(p)}</p>"
            f"<h2><a href='{race_path(date, p)}'>{esc(extra.nfkc(race_label(p)))}</a></h2><p class='meta'>{esc(race_cond(p))}　自信度 <span class='conf c{esc(p.get('confidence'))}'>{esc(p.get('confidence'))}</span></p>"
            f"<p class='hmarks'>{marks}</p>{res}</div></section>"), p["race_id"]


def link_horse(name) -> str:
    nm = extra.nfkc(name or "").replace(" ", "")
    return f"<a href='/horse/{extra.short_id(nm)}/'>{esc(name)}</a>" if nm in LINK_HORSES else esc(name)


def link_jockey(name) -> str:
    nm = extra.nfkc(name or "").replace(" ", "")
    return f"<a href='/jockey/{extra.short_id(nm)}/'>{esc(name)}</a>" if nm in LINK_JOCKEYS else esc(name)


def course_link(p: dict) -> str:
    r = p["_race"]
    if not r.get("distance"):
        return ""
    surf = "turf" if r.get("surface") == "芝" else "jump" if r.get("surface") == "障" else "dirt"
    key = f"{VENUE_SLUG.get(venue_of(p), 'venue')}-{surf}-{int(r['distance'])}"
    if key not in LINK_COURSES:
        return ""
    return f"　<a href='/course/{key}/'>このコースの傾向</a>"


def plain_line(p: dict) -> str:
    """初めての人向けの一言要約。印と買い目の型から機械的に作る。"""
    m = p.get("marks", {})
    hon = m.get("◎")
    if hon is None or p.get("confidence") == "見送り":
        return "<p class='plain'>一言でいうと：データ不足のため、このレースは買い目を出していない。</p>"
    rest = "・".join(f"{k}{m[k]}{horse_name(p, m[k])}" for k in ("〇", "▲") if m.get(k) is not None)
    bets = p.get("bets", [])
    kinds = []
    for b in bets:
        if b["type"] not in kinds:
            kinds.append(b["type"])
    bt = "・".join(kinds) + f"で{len(bets)}点" if bets else "買い目なし"
    return (f"<p class='plain'>一言でいうと：本命は<b>◎{hon} {esc(horse_name(p, hon))}</b>" + (f"、相手は{esc(rest)}" if rest else "")
            + f"。買い目は{esc(bt)}（各100円）。自信度{esc(p.get('confidence'))}。</p>")


def race_item(date: str, p: dict) -> str:
    sc = scored(p)
    badge = ""
    if sc and sc["stake"]:
        if not sc["return"]:
            badge = f"<span class='res miss'>不的中 −{sc['stake']:,}円</span>"
        elif sc["return"] < sc["stake"]:
            badge = f"<span class='res tg'>的中 {sc['return'] - sc['stake']:+,}円（トリガミ）</span>"
        else:
            badge = f"<span class='res hit'>的中 {sc['return'] - sc['stake']:+,}円・{roi_txt(sc['stake'], sc['return'])}</span>"
    hon = p.get("marks", {}).get("◎")
    hon_txt = "見送り" if p.get("confidence") == "見送り" else f"◎{hon} {horse_name(p, hon)}"
    odds_txt = ""
    if hon is not None and p.get("confidence") != "見送り":
        hh = next((h for h in p["_race"].get("horses", []) or [] if h.get("number") == hon), None)
        if hh and hh.get("odds"):
            odds_txt = f"<small class='odds'>{hh['odds']}倍{f'・{hh['popularity']}人気' if hh.get('popularity') else ''}</small>"
    pt = p["_race"].get("post_time") or ""
    return (f"<li data-conf='{esc(p.get('confidence'))}' data-venue='{esc(venue_of(p))}' data-post='{date}{pt.replace(':', '')}'>"
            f"<a href='{race_path(date, p)}'><span class='rb'>{race_no(p)}R</span>"
            f"<span class='rinfo'><span class='rname'>{esc(VENUE_NAME.get(venue_of(p), venue_of(p)))} {esc(race_short(p))}{grade_badge(p)}</span>"
            f"<span class='rsub'>{esc(pt)}{'発走' if pt else ''} {esc(race_cond(p))}</span></span>"
            f"<span class='hon'>{esc(hon_txt)}{odds_txt}</span>"
            f"<span class='conf c{esc(p.get('confidence'))}'>{esc(p.get('confidence'))}</span>{badge}</a></li>")


def day_stats(preds: list[dict]) -> tuple[int, int]:
    done = [p["_score"] for p in preds if p.get("_score") and "stake" in p["_score"] and not p["_score"].get("voided")]
    return sum(s["stake"] for s in done), sum(s["return"] for s in done)


def filters(venues: list[str]) -> str:
    vb = "".join(f"<button data-venue='{esc(v)}'>{esc(VENUE_NAME.get(v, v))}</button>" for v in venues)
    return (f"<div class='filters vtabs' data-kind='venue'><button class='on' data-venue='all'>全場</button>{vb}</div>"
            "<div class='filters' data-kind='conf'><button class='on' data-conf='all'>全自信度</button><button data-conf='A'>A</button>"
            "<button data-conf='B'>B</button><button data-conf='C'>C</button><button data-conf='見送り'>見送り</button></div>")


def scoreboard(date: str, preds: list[dict]) -> str:
    """当日のここまでの成績（レースが確定するたびに更新）。"""
    bet = [p for p in preds if p.get("confidence") != "見送り"]
    done = [scored(p) for p in bet if scored(p)]
    if not done:
        return (f"<section class='card live'><h2>当日の成績</h2>{banner('morning')}<p>確定 0／{len(bet)}レース。最初のレースが確定すると、ここに的中と回収率が出る。</p></section>")
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


CONF_RANK = {"A": 3, "B": 2, "C": 1}


def honmei_value(p: dict) -> tuple[float | None, float | None, float | None]:
    """◎の想定勝率・単勝オッズ・期待値（勝率×オッズ）。オッズが無ければ None。"""
    hon = p.get("marks", {}).get("◎")
    if hon is None:
        return None, None, None
    wp = next((h.get("win_pct") for h in p.get("horses", []) if h.get("number") == hon), None)
    od = next((h.get("odds") for h in p["_race"].get("horses", []) or [] if h.get("number") == hon), None)
    try:
        wp = float(wp) if wp is not None else None
        od = float(od) if od else None
    except (TypeError, ValueError):
        wp, od = None, None
    val = round(wp / 100 * od, 2) if wp is not None and od else None
    return wp, od, val


def picks(preds: list[dict], n: int = 3) -> list[dict]:
    """その日の勝負レース：的中しやすい順（自信度、◎の人気、中央、重賞、想定勝率で加点）。
    期待値（勝率×オッズ）順にしないのは、これまでの成績で期待値が高い区分ほど回収率が低かったため（/strategy/ 参照）。"""
    cand = []
    for p in preds:
        if p.get("confidence") == "見送り" or p.get("marks", {}).get("◎") is None:
            continue
        wp, od, val = honmei_value(p)
        hon = p["marks"]["◎"]
        pop = next((h.get("popularity") for h in p["_race"].get("horses", []) or [] if h.get("number") == hon), None)
        g = extra.grade_of(p["_race"], p.get("race_name") or p["_race"].get("race_name") or "")
        score = 2.0 * CONF_RANK.get(p.get("confidence"), 0)
        score += 1.5 if str(p["race_id"]).startswith("jra_") else 0
        score += 1.0 if g else 0
        score += {1: 2.0, 2: 1.5, 3: 1.5}.get(pop, 0.5 if pop and pop <= 6 else 0)
        score += min(wp or 0, 40) / 40
        cand.append((score, p))
    cand.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in cand[:n]]


def picks_html(date: str, preds: list[dict], today: bool, exclude: str | None = None) -> str:
    ps = [p for p in picks(preds, 4) if p['race_id'] != exclude][:3]
    if len(ps) < 2:
        return ""
    items = []
    for p in ps:
        hon = p["marks"]["◎"]
        wp, od, val = honmei_value(p)
        sc = scored(p)
        if sc and sc["stake"]:
            res = (f"<span class='res miss'>不的中</span>" if not sc["return"] else
                   f"<span class='res {'tg' if sc['return'] < sc['stake'] else 'hit'}'>的中 回収率{roi_txt(sc['stake'], sc['return'])}</span>")
        else:
            res = f"<span class='res wait'>{esc(p['_race'].get('post_time') or '')}発走</span>"
        meta = "・".join(x for x in (f"想定勝率{wp:.0f}%" if wp is not None else "", f"単勝{od:.1f}倍" if od else "",
                                     f"期待値{val:.2f}" if val is not None else "") if x)
        items.append(f"<li><a href='{race_path(date, p)}'><span class='rno'>{esc(extra.nfkc(race_label(p)))}</span>"
                     f"<span class='hon'>◎{hon} {esc(horse_name(p, hon))}</span><span class='conf c{esc(p.get('confidence'))}'>{esc(p.get('confidence'))}</span>"
                     f"{res}<span class='meta'>{esc(meta)}</span></a></li>")
    return (f"<section class='card picks'><h2>{'今日' if today else 'この日'}の勝負レース{'（ほか）' if exclude else ''}</h2><ul class='races'>{''.join(items)}</ul>"
            f"<p class='meta'>的中しやすさの順に3レース（自信度・◎の人気・中央・重賞・想定勝率で加点）。回収率が高い順ではない。買い方ごとの回収率は<a href='/strategy/'>買い方別</a>へ。</p></section>")


def day_list(date: str, preds: list[dict]) -> str:
    venues = sorted({venue_of(p) for p in preds})
    today = date == TODAY
    h, hid = hero(date, preds)
    tomorrow = (datetime.strptime(date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
    tmr = (f"<p class='notice'><a href='{day_path(tomorrow)}'>明日（{fmt_date(tomorrow)}）の予想を公開しました →</a></p>"
           if today and tomorrow in ALL_DATES else "")
    stale = "<p class='notice stale' hidden>このページの最終更新から時間がたっています。結果の反映が遅れている可能性があります。</p>" if today else ""
    gl = [p for p in preds if extra.grade_of(p["_race"], p.get("race_name") or p["_race"].get("race_name") or "")]
    glist = ""
    if len(gl) >= 2:
        glist = ("<section class='card'><h2>{}の重賞</h2><ul class='races rlist'>".format("今日" if today else "この日")
                 + "".join(race_item(date, p) for p in sorted(gl, key=lambda q: q["_race"].get("post_time") or "")) + "</ul></section>")
    return (stale + tmr + date_tabs(date) + h + scoreboard(date, preds) + glist + picks_html(date, preds, today, hid) + filters(venues)
            + (f"<p class='jump'><a href='#next' class='to-next'>次の発走へ ↓</a><button class='toggle-gone'>発走済みを表示</button></p>" if today else "")
            + "<ul class='races rlist'>" + "".join(race_item(date, p) for p in preds) + "</ul>")


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
    desc_ = f"累計回収率の推移。最初{points[0]:.1f}%から最新{points[-1]:.1f}%。最高{max(points):.1f}%、最低{min(points):.1f}%。点線は100%。"
    return (f"<svg viewBox='0 0 {w} {h}' class='chart' role='img' aria-label='{esc(desc_)}'><title>{esc(desc_)}</title>"
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
    by_month = defaultdict(list)
    for r in rows:
        by_month[r["date"][:6]].append(r)
    monthly = {f"{m[:4]}年{int(m[4:6])}月": totals(v) for m, v in sorted(by_month.items(), reverse=True)}
    month_sentence = "　".join(f"{k}は{v['n']}レースで回収率{v['roi']}、◎勝率{v['win']}。" for k, v in list(monthly.items())[:3])
    conf = defaultdict(list)
    ven = defaultdict(list)
    for r in rows:
        conf[r["confidence"] or "-"].append(r)
        ven[venue_of_race.get(r["race_id"], "-")].append(r)
    venue_link = lambda k: f"<a href='{venue_path(k)}'>{esc(VENUE_NAME.get(k, k))}</a>" if k in VENUE_SLUG else esc(k)
    body = f"""<h1>成績</h1>{banner("results")}
<p class="answer">{SITE_NAME}のAI予想の成績は、{asof}時点で{t['n']}レース・累計回収率{t['roi']}（◎勝率{t['win']}、◎複勝率{t['top3']}）。外れも含めた全予想を、買い目各点100円の均等買いとして集計している。</p>
<div class="kpis"><div><b>{t['n']}</b><span>集計レース</span></div><div><b>{t['roi']}</b><span>累計回収率</span></div>
<div><b>{t['win']}</b><span>◎勝率</span></div><div><b>{t['top3']}</b><span>◎複勝率</span></div></div>
<section class="card"><h2>累計回収率の推移</h2>{svg_line(cum, labels=[md(d) for d in days]) or '<p>2日分以上たまると表示します。</p>'}</section>
<section class="card"><h2>自信度別</h2><div class="scroll">{table({k: totals(v) for k, v in sorted(conf.items())}, '自信度')}</div></section>
<section class="card"><h2>場別</h2><div class="scroll">{table({venue_link(k): totals(v) for k, v in sorted(ven.items(), key=lambda kv: -len(kv[1]))}, '場', raw=True)}</div></section>
<section class="card"><h2>月別</h2><p>{month_sentence}</p><div class="scroll">{table(monthly, '月')}</div></section>
<section class="card"><h2>券種別</h2>{column.stats(STATS_FROM)[1]["table_bets"]}</section>
<section class="card"><h2>日別</h2><div class="scroll">{table(daily, '日付')}</div></section>
<p class="meta">買い方を変えた場合の回収率は<a href="/strategy/">買い方別</a>、コースごとの成績と傾向は<a href="/course/">コース別</a>、騎手ごとは<a href="/jockey/">騎手別</a>、重賞は<a href="/graded/">重賞一覧</a>へ。</p>
<p class="meta">集計対象は自動運用を始めた2026年10月26日以降で、見送り（買い目なし）は除いている。全予想の記録（CSV）は<a href="/data/results_ledger.csv" download>ダウンロード</a>でき、<a href="{REPO}/blob/main/results_ledger.csv">GitHub</a>でも公開している。</p>"""
    ld = {"@context": "https://schema.org", "@type": "Dataset", "name": f"{SITE_NAME} AI競馬予想 全成績",
          "description": "日本の競馬（JRA・地方）全レースのAI予想と結果・回収率の記録（各点100円の均等買い）",
          "url": BASE_URL + "/results/", "license": "https://creativecommons.org/licenses/by/4.0/",
          "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv",
                            "contentUrl": BASE_URL + "/data/results_ledger.csv"}]}
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
                f"<h1>{esc(name)}競馬のAI予想と成績</h1>{banner(VENUE_PIC.get(v, 'dirt'))}<p class='answer'>{esc(lead)}</p>"
                f"<div class='kpis'><div><b>{t['n']}</b><span>集計レース</span></div><div><b>{t['roi']}</b><span>回収率</span></div>"
                f"<div><b>{t['hit']}</b><span>的中率</span></div><div><b>{t['top3']}</b><span>◎複勝率</span></div></div>"
                + (aff_rakuten('venue') if slug not in ("sapporo", "hakodate", "fukushima", "niigata", "tokyo", "nakayama", "chukyo", "kyoto", "hanshin", "kokura") else "")
                + f"<section class='card'><h2>最近の予想</h2>{''.join(recent)}</section>{bias_html}"
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
                          f"<p class='crumb'><a href='/'>トップ</a> › 競馬場</p><h1>競馬場別のAI予想と成績</h1>{banner('venue')}"
                          f"<p class='answer'>中央・地方の各競馬場ごとに、AI予想・回収率・当日バイアスの履歴をまとめている。</p><ul class='days'>{lis}</ul>",
                          "/venue/", desc="競馬場ごとのAI予想・回収率・トラックバイアスの履歴。"))
    out["/venue/"] = max(out.values()) if out else None
    return out


# ---------------- SNS投稿の確認ページ（検索には出さない） ----------------
def social_page() -> None:
    sdir = ROOT / "social"
    if not sdir.exists():
        return
    shutil.copytree(sdir, OUT / "social", dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.json"))
    label = {"posted": "投稿済み", "draft": "下書き（鍵が未設定）", "pending": "投稿待ち", "failed": "失敗", "off": "対象外"}
    blocks = []
    for d in sorted((p.name for p in sdir.iterdir() if p.is_dir()), reverse=True)[:7]:
        st = load_json(sdir / d / "posts.json") or {}
        for pid, e in sorted((st.get("posts") or {}).items(), key=lambda kv: kv[1].get("created", ""), reverse=True):
            blocks.append(
                f"<section class='card sp'><img src='{esc(e['image'])}' alt='' loading='lazy' width='270' height='338'>"
                f"<div><p class='meta'>{esc(fmt_date(d))}・{esc(e.get('kind'))}・作成 {esc(e.get('created'))}</p>"
                f"<p>X：{esc(label.get(e.get('x'), e.get('x')))}　Instagram：{esc(label.get(e.get('instagram'), e.get('instagram')))}</p>"
                f"<h3>Xの文面</h3><pre>{esc(e.get('x_text'))}</pre><h3>Instagramの文面</h3><pre>{esc(e.get('ig_caption'))}</pre>"
                + "".join(f"<p class='miss'>{esc(k)}：{esc(e[k])}</p>" for k in ('x_error', 'instagram_error') if e.get(k)) + "</div></section>")
    write("/social/", page(f"SNS投稿の確認 | {SITE_NAME}", "<h1>SNS投稿の確認</h1><p class='meta'>運営者用。直近7日分の自動投稿（下書きを含む）。</p>"
                           + ("".join(blocks) or "<p>まだありません。</p>"), "/social/", noindex=True))


# ---------------- 固定ページ ----------------
ABOUT = f"""<h1>予想の方法</h1>{banner("about")}
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
<section class="card"><h2>印・自信度・買い目</h2><p>評価点の上位に想定勝率を付け、「想定勝率×単勝オッズ」が1.2以上を妙味あり、0.8未満を過剰人気とする。印は◎（本命）〇（対抗）▲（単穴）△（連下）☆（穴）。自信度はA・B・C・見送りの4段階。2026年11月1日からは◎の想定勝率で決めている（A：40%以上、B：30〜39%、C：30%未満）。近走データが不足するレースは見送りとする。買い目は2026年11月2日から型で固定している：◎の単複1点（1〜2番人気は複勝、3〜5番人気は単勝、6番人気以下は買わない）と、3連複フォーメーション（◎→〇▲→印全部）。馬連・馬単・3連単・ワイドは使わない。</p></section>
<section class="card"><h2>当たらないこともある</h2><p>回収率は100%を下回っている。どこが弱いか、数字をどう見るかは<a href="/limits/">AI予想の限界と注意点</a>に正直に書いている。</p></section>
<section class="card support-box"><h2>運営を支援する</h2><p>予想・集計・SNS投稿はすべて自動で動いていますが、サーバー代やX投稿のAPI代は個人で負担しています。応援してもよいと思ったら、<a href="{OFUSE_URL}" target="_blank" rel="noopener">OFUSE（オフセ）</a>からファンレターと一緒に支援できます（コンビニ・PayPay・クレジットカード対応）。支援の有無で予想の内容や公開範囲は変わりません。</p><p><a class="btn" href="{OFUSE_URL}" target="_blank" rel="noopener">OFUSEで応援する</a></p></section>
<section class="card"><h2>よくある質問</h2>
<h3>回収率はどう計算していますか</h3><p>全予想の買い目を各点100円で買ったものとして、払戻の合計÷投資の合計で計算しています。外れたレースも除外しません。</p>
<h3>どのレースを予想していますか</h3><p>JRAと地方競馬の、その日に開催される全レースです。データが不足するレースは「見送り」として記録します。</p>
<h3>予想のルールは変わりますか</h3><p>成績をもとに見直すことがある。変更は<a href="{REPO}/blob/main/PREDICT.md">GitHubのPREDICT.md</a>に日付と理由を残し、<a href="/strategy/">買い方別の回収率</a>で効果を確認できるようにしている。</p><h3>予想は後から変わりますか</h3><p>当日昼に、オッズや馬場の傾向を見て前日の予想を見直すことがあります。その場合は各レースページの「更新履歴」に変更理由を残します。発走後の変更はしません。</p></section>
<section class="card"><h2>データについて</h2><p>出馬表・オッズ・結果は主催者等の公開情報をもとにしている。正式な情報は必ず主催者の発表で確認してほしい。</p></section>"""

FAQ_LD = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
    {"@type": "Question", "name": "回収率はどう計算していますか",
     "acceptedAnswer": {"@type": "Answer", "text": "全予想の買い目を各点100円で買ったものとして、払戻の合計÷投資の合計で計算しています。外れたレースも除外しません。"}},
    {"@type": "Question", "name": "どのレースを予想していますか",
     "acceptedAnswer": {"@type": "Answer", "text": "JRAと地方競馬の、その日に開催される全レースです。データが不足するレースは見送りとして記録します。"}},
    {"@type": "Question", "name": "予想のルールは変わりますか",
     "acceptedAnswer": {"@type": "Answer", "text": "成績をもとに見直すことがあります。変更はGitHubのPREDICT.mdに日付と理由を残し、買い方別の回収率ページで効果を確認できるようにしています。"}},
    {"@type": "Question", "name": "予想は後から変わりますか",
     "acceptedAnswer": {"@type": "Answer", "text": "当日昼にオッズや馬場の傾向を見て前日の予想を見直すことがあり、変更理由を更新履歴に残します。発走後の変更はしません。"}}]}

CONTACT = f"""<h1>お問い合わせ</h1>
<p class="answer">予想の内容についてのご意見、データの誤り、サイトの不具合、広告掲載や取材のご相談などは、このフォームからお送りください。通常2〜3日以内に返信します。</p>
<form class="contact" action="https://formsubmit.co/{CONTACT_MAIL}" method="POST">
<input type="hidden" name="_subject" value="【競馬全頭ログ】お問い合わせ">
<input type="hidden" name="_template" value="table">
<input type="hidden" name="_captcha" value="true">
<input type="hidden" name="_next" value="{BASE_URL}/contact/thanks/">
<input type="text" name="_honey" style="display:none" tabindex="-1" autocomplete="off">
<label>お名前（ニックネーム可）<input type="text" name="name" required maxlength="60"></label>
<label>メールアドレス<input type="email" name="email" required></label>
<label>種類<select name="kind">
<option>予想・データについて</option><option>サイトの不具合</option><option>広告掲載・取材</option><option>その他</option></select></label>
<label>対象のページ（任意）<input type="url" name="page" placeholder="https://www.ai-keiba-log.com/..."></label>
<label>内容<textarea name="message" rows="7" required maxlength="3000"></textarea></label>
<p class="meta">送信いただいた内容は、回答のためにのみ使用します。<a href="/privacy/">プライバシーポリシー</a></p>
<button type="submit" class="btn">送信する</button>
</form>
<p class="meta">フォームが使えない場合は、メールで {CONTACT_MAIL} へお送りください。</p>"""

THANKS = f"""<h1>送信しました</h1>
<p class="answer">お問い合わせを受け付けました。通常2〜3日以内に、ご記入のメールアドレスへ返信します。</p>
<p><a href="/">トップへ戻る</a></p>"""

def glossary_page() -> str:
    items = "".join(f"<dt id='{k}'>{esc(t)}</dt><dd>{esc(d)}</dd>" for k, t, d in GLOSSARY)
    return page(f"用語集：印・評価点・妙味・回収率など | {SITE_NAME}",
                f"<p class='crumb'><a href='/'>トップ</a> › 用語集</p><h1>用語集</h1>"
                f"<p class='answer'>このサイトで使う言葉の説明。予想ページの用語をタップするとここに飛ぶ。初心者向けの解説は<a href='/column/'>コラム</a>へ。</p>"
                f"<dl class='gloss'>{items}</dl>", "/glossary/",
                desc="競馬全頭ログで使う用語（印、評価点、想定勝率、妙味、自信度、展開利、トラックバイアス、回収率、トリガミ、3連複フォーメーション）の説明。")


def limits_page(t: dict, worst_venue: tuple[str, str] | None) -> str:
    wv = f"場別では{esc(worst_venue[0])}が最も悪く（回収率{esc(worst_venue[1])}）、" if worst_venue else ""
    body = f"""<p class='crumb'><a href='/'>トップ</a> › AI予想の限界と注意点</p><h1>AI予想の限界と注意点</h1>
<p class='answer'>このサイトの予想は、現時点で馬券の収支をプラスにできていない。累計回収率は{esc(t['roi'])}（{esc(t['n'])}レース）で、100%を下回っている。読む前に知っておいてほしいことをまとめた。</p>
<section class='card'><h2>当たっている部分と、当たっていない部分</h2>
<p>◎の馬は{esc(t['top3'])}の確率で3着以内に入り、◎の複勝だけなら回収率は80%前後になる。つまり「本命の選び方」は大きくは外していない。一方で、相手の選び方と買い目の組み方で取りこぼしが多く、全体の回収率を下げている。{wv}人気薄を強く評価しすぎる傾向（AIの見立てがオッズより強気なレースほど回収率が低い）もある。詳しくは<a href='/strategy/'>買い方別の回収率</a>で毎日更新している。</p></section>
<section class='card'><h2>AIが苦手なこと</h2>
<ul><li>通過順や脚質のデータが取れないレース（ばんえい競馬など）。</li><li>転入初戦や休み明けなど、近走データが足りない馬。これらは「見送り」にしている。</li><li>当日の馬場の急変、出遅れ、不利などの偶然。予想は発走20分前以降は変えない。</li><li>オッズが締め切り直前に大きく動くレース。予想に使うオッズは取得時点のもので、最終オッズとは違う。</li></ul></section>
<section class='card'><h2>この数字の見方</h2>
<ul><li>回収率は、外れたレースも除外せず、各点100円の均等買いで集計している。都合のいい期間だけを切り取っていない。</li><li>レース数が少ない区分（目安50レース未満）の回収率は、高配当1回で大きく動く。</li><li>予想のルールは成績を見て変えることがある。変更は<a href='/changelog/'>更新履歴</a>に残す。</li></ul></section>
<section class='card'><h2>お願い</h2><p>予想は情報提供であり、的中や利益を保証しない。馬券はご自身の判断と責任で、無理のない金額で。20歳未満の方は馬券を購入できない。</p></section>"""
    return page(f"AI予想の限界と注意点 | {SITE_NAME}", body, "/limits/",
                desc=f"競馬全頭ログのAI予想が当たっていない部分、苦手なレース、数字の見方。累計回収率{t['roi']}（{t['n']}レース）の時点での正直な説明。")


SITE_CHANGES = [
    ("2026-10-26", "自動運用を開始。全レースの予想・結果・回収率の公開を始めた。"),
    ("2026-10-30", "レースごとの的中・回収率を、確定のたびに更新するようにした。初心者向けコラムの準備。"),
    ("2026-11-01", "サイト名を「競馬全頭ログ」に変更。XとInstagramへの自動投稿（的中・重賞・毎晩の全成績）を開始。コラム4本を公開。買い方別の回収率、週次の重賞回顧、馬別ページを追加。"),
    ("2026-11-02", "買い目を型で固定（◎の単複を人気で切り替え＋3連複フォーメーション）。デザインを刷新。挿絵を追加。お問い合わせフォームと支援（OFUSE）の導線を設置。"),
    ("2026-11-03", "コラムを21本追加（AI予想は当たるのか、3連複フォーメーション、単勝と複勝、期待値買い、自信度、中央と地方、2番人気の本命、予想ページの見方、ばんえい競馬、脚質別・枠順別・オッズ別・頭数別・馬体重別・間隔別の勝率、点数計算早見表、ChatGPTでの予想、地方競馬のネット投票、馬連・馬単・ワイド、トリガミ、当たらない理由）。数字はすべて実データから自動更新。"),
]


def changelog_page() -> str:
    rules = []
    try:
        txt = (ROOT / "PREDICT.md").read_text(encoding="utf-8")
        sec = txt.split("## 成績からの調整履歴", 1)[1]
        for line in sec.splitlines():
            if line.startswith("- "):
                rules.append(line[2:].strip())
    except Exception:
        pass
    r_html = "".join(f"<li>{esc(x)}</li>" for x in rules)
    s_html = "".join(f"<li><b>{esc(d)}</b>　{esc(x)}</li>" for d, x in sorted(SITE_CHANGES, reverse=True))
    body = (f"<p class='crumb'><a href='/'>トップ</a> › 更新履歴</p><h1>更新履歴</h1>"
            f"<p class='answer'>予想ルールの変更と、サイトの機能の変更を日付つきで記録している。予想ルールの変更は成績の分析にもとづき、毎週月曜に見直している。</p>"
            f"<section class='card'><h2>予想ルールの変更</h2><ul class='log'>{r_html or '<li>まだありません。</li>'}</ul></section>"
            f"<section class='card'><h2>サイトの変更</h2><ul class='log'>{s_html}</ul></section>")
    return page(f"更新履歴 | {SITE_NAME}", body, "/changelog/", desc="競馬全頭ログの予想ルールとサイト機能の変更履歴。")


OPERATOR = f"""<h1>運営者情報</h1>
<section class="card"><table>
<tr><th>サイト名</th><td>{SITE_NAME}（{SITE_SUB}）</td></tr>
<tr><th>URL</th><td>{BASE_URL}/</td></tr>
<tr><th>運営</th><td>{SITE_NAME} 運営者（個人）</td></tr>
<tr><th>内容</th><td>AIによる競馬予想と、その成績（回収率）の記録・公開</td></tr>
<tr><th>予想の作成</th><td>AI（Anthropic社のClaude）が公開データをもとに作成。作成手順とプログラムは<a href="{REPO}">GitHub</a>で公開</td></tr>
<tr><th>SNS</th><td><a href="{X_URL}">X（@zentou_log）</a>・<a href="{IG_URL}">Instagram（@zentou_log）</a></td></tr>
<tr><th>運営の支援</th><td><a href="{OFUSE_URL}">OFUSE（ofuse.me/zentou_log）</a></td></tr>
<tr><th>お問い合わせ</th><td><a href="/contact/">お問い合わせフォーム</a>、またはメール {CONTACT_MAIL}</td></tr>
</table></section>
<section class="card"><h2>免責事項</h2><p>本サイトの予想・情報は正確性や完全性を保証するものではありません。本サイトの情報を利用して生じた損害について、運営者は責任を負いません。馬券の購入はご自身の判断と責任で行ってください。</p></section>"""

PRIVACY = f"""<h1>プライバシーポリシー</h1>
<section class="card"><h2>個人情報の取り扱い</h2><p>本サイトは、閲覧者の氏名やメールアドレスなどの個人情報を収集していません。お問い合わせの際にご提供いただいた情報は、回答のためにのみ使用します。</p></section>
<section class="card"><h2>アクセス解析について</h2><p>本サイトでは、Google LLCのアクセス解析ツール「Googleアナリティクス」を利用しています。Googleアナリティクスはデータ収集のためにCookieを使用し、閲覧したページや滞在時間、おおよその地域、使用端末などの情報を収集します。これらの情報は匿名で収集されており、個人を特定するものではありません。データの取り扱いについては<a href="https://policies.google.com/technologies/partner-sites?hl=ja" target="_blank" rel="noopener">Googleのサービスを使用するサイトやアプリから収集した情報のGoogleによる使用</a>をご覧ください。収集を望まない場合は、ブラウザの設定でCookieを無効にするか、<a href="https://tools.google.com/dlpage/gaoptout?hl=ja" target="_blank" rel="noopener">Googleアナリティクス オプトアウト アドオン</a>をご利用ください。</p></section>
<section class="card"><h2>広告について</h2><p>本サイトでは今後、広告配信やアフィリエイトプログラムを利用する場合があります。これらのサービスはCookie等を使用して閲覧情報を収集することがありますが、個人を特定する情報は含まれません。Cookieはブラウザの設定で無効にできます。</p></section>
<section class="card"><h2>広告の表記</h2><p>本サイトに掲載する広告・アフィリエイトリンクには、その旨を明記します。</p></section>
<section class="card"><h2>改定</h2><p>本ポリシーは必要に応じて改定することがあります。制定日：2026年10月27日／改定日：2026年11月1日（Googleアナリティクスの利用を追記）</p></section>"""

CSS = """.aff{font-size:13px;color:var(--mut);margin:10px 0 0;padding:8px 10px;border:1px dashed var(--line);background:var(--bg)}.aff a{color:var(--acc);font-weight:700}.pr{display:inline-block;font-size:10px;border:1px solid var(--mut);border-radius:2px;padding:0 4px;margin-right:6px;vertical-align:middle;color:var(--mut)}
.affbox{margin:24px 0}.affbox p{margin:0 0 8px;font-size:14px;color:var(--fg)}.affbox img{max-width:100%;height:auto;display:block}
:root{--bg:#f2f3f0;--panel:#fff;--fg:#17201b;--mut:#5f6761;--line:#d9dcd6;--rule:#17201b;--acc:#146b45;--acc-soft:#e3efe8;--hit:#c0122d;--hit-soft:#fbe9ec;--tg:#8a6100;--miss:#7a807b;--card:var(--panel);--won:var(--hit-soft)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#141614;--panel:#1c1f1c;--fg:#ecefe9;--mut:#a4aba5;--line:#343934;--rule:#ecefe9;--acc:#6cc497;--acc-soft:#1f2e26;--hit:#ff7b8c;--hit-soft:#3a2126;--tg:#d9a93a;--miss:#8b918c}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.75 "BIZ UDPGothic","Hiragino Sans","Noto Sans JP",system-ui,sans-serif;font-variant-numeric:tabular-nums}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.wrap{max-width:960px;margin:0 auto;padding:0 16px}
h1,h2,h3,.kpis b,.marks b,.sum{font-family:"Shippori Mincho B1","Hiragino Mincho ProN","Yu Mincho",serif;font-weight:800;letter-spacing:.01em}
h1{font-size:28px;line-height:1.35;margin:22px 0 6px}h2{font-size:19px;line-height:1.4;margin:22px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--rule)}h3{font-size:16px;margin:18px 0 6px}
p{margin:8px 0}
/* ヘッダー：帳面の表紙 */
.top{background:var(--panel);border-bottom:3px solid var(--rule)}.top .wrap{padding:0 16px}
.bar{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;padding:12px 0 8px}.bar .logo{flex:1 1 240px}.roi-badge{margin-left:auto}
.logo{display:flex;align-items:center;gap:12px;color:var(--fg);line-height:1.25}.logo:hover{text-decoration:none}.logo img{display:block}
.logo span{display:flex;flex-direction:column}.logo b{font-family:"Shippori Mincho B1",serif;font-weight:800;font-size:22px;letter-spacing:.04em}.logo small{font-size:12px;color:var(--mut);margin-top:2px}
.roi-badge{font-size:13px;color:var(--mut);white-space:nowrap;border-left:1px solid var(--line);padding-left:12px}.roi-badge b{color:var(--fg);font-size:18px;font-family:"Shippori Mincho B1",serif;margin-left:2px}.roi-badge:hover{text-decoration:none}
nav{display:flex;gap:0 2px;font-size:14px;overflow-x:auto;scrollbar-width:none;margin:0 -16px;padding:0 12px}nav::-webkit-scrollbar{display:none}
nav a{white-space:nowrap;color:var(--fg);padding:8px 10px 9px;border-bottom:3px solid transparent;margin-bottom:-3px}nav a:hover{text-decoration:none;color:var(--acc)}nav a.on{border-bottom-color:var(--acc);color:var(--acc);font-weight:700}
/* 本文 */
main{padding-bottom:24px}
.meta,.crumb{color:var(--mut);font-size:13px;margin:0 0 10px}.crumb{margin-top:14px}
.answer{font-size:17px;line-height:1.8;margin:10px 0 18px;padding:0}
.card{background:none;border:0;padding:0;margin:30px 0}.card>h2:first-child{margin-top:0}.today>h2{font-size:24px;border:0;padding:0;margin:18px 0 0}
.big{font-size:17px;font-weight:700}.sum{font-size:18px;line-height:1.8;font-weight:700;margin:6px 0 14px}.miss{color:var(--miss)}.hit{color:var(--hit);font-weight:700}.tg{color:var(--tg);font-weight:700}
/* 印 */
.marks{display:flex;flex-wrap:wrap;gap:6px 28px;margin:4px 0 6px}.marks .m{display:flex;align-items:baseline;gap:8px;padding:2px 0}
.marks b{font-size:28px;color:var(--acc);line-height:1}.marks span{font-weight:700;font-size:18px}.marks .m:first-child span{font-size:20px}.subs{color:var(--mut);margin:0 0 8px}
.conf{display:inline-block;min-width:26px;text-align:center;border-radius:2px;font-size:12px;font-weight:700;padding:0 6px;border:1px solid var(--line);line-height:20px;vertical-align:middle}
.cA{background:var(--acc);color:#fff;border-color:var(--acc)}.cB{color:var(--acc);border-color:var(--acc)}.cC{color:var(--mut)}.c見送り{color:var(--mut);border-style:dashed}
.bets{display:flex;flex-wrap:wrap;gap:6px 8px;list-style:none;padding:0;margin:6px 0}.bets li{border:1px solid var(--line);background:var(--panel);border-radius:2px;padding:2px 9px;font-size:14px}.bets li.won{background:var(--hit-soft);border-color:var(--hit);color:var(--hit);font-weight:700}
/* 一覧：出馬表のような罫線の行 */
.races{list-style:none;padding:0;margin:0;background:var(--panel);border-top:2px solid var(--rule);border-bottom:1px solid var(--line)}
.races li+li{border-top:1px solid var(--line)}
.races a{display:flex;flex-wrap:wrap;gap:2px 12px;align-items:center;padding:9px 10px;color:var(--fg);border-left:4px solid transparent}.races a:hover{text-decoration:none;background:var(--acc-soft)}
.races li.next a{border-left-color:var(--acc);background:var(--acc-soft)}.races li.next .rt::after{content:" 次"; color:var(--acc);font-weight:700}
.races li.gone a{color:var(--mut)}.races li.gone .rno,.races li.gone .hon{color:var(--fg)}
.rno{font-weight:700;min-width:78px}.rt{color:var(--mut);font-size:13px;min-width:44px}.hon{flex:1;min-width:150px}
.res{font-size:13px}.res.wait{color:var(--mut)}.live .kpis{margin:8px 0}
.races.fold li.gone:not(.keep){display:none}.races.fold li.gone.keep{opacity:.9}
.picks .races a{flex-wrap:wrap;row-gap:2px;padding:10px}.picks .rno{flex-basis:100%;font-size:16px;min-width:0}.picks .meta{margin:0;flex-basis:100%}.picks .res{margin-left:auto}
.jump{display:flex;gap:12px;align-items:center;font-size:13px;margin:10px 0 6px}
.jump button,.filters button,.share a,.share button,.vs .go{border:1px solid var(--line);background:var(--panel);color:var(--fg);border-radius:2px;padding:3px 12px;font:inherit;font-size:13px;cursor:pointer}
.filters{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 6px}.filters button.on{background:var(--rule);color:var(--bg);border-color:var(--rule)}
.share{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.vs select{font:inherit;padding:4px;border-radius:2px;border:1px solid var(--line);background:var(--panel);color:var(--fg)}.vs .r{font-weight:700;margin-top:8px}
/* 数字の帯 */
.kpis{display:flex;flex-wrap:wrap;margin:14px 0;background:var(--panel);border-top:2px solid var(--rule);border-bottom:1px solid var(--line)}
.kpis div{flex:1 1 140px;padding:10px 14px 8px;border-right:1px solid var(--line)}.kpis div:last-child{border-right:0}
.kpis b{display:block;font-size:26px;line-height:1.2}.kpis span{color:var(--mut);font-size:12px;display:block;margin-top:2px}
/* 表 */
table{border-collapse:collapse;width:100%;font-size:14px;background:var(--panel)}th{border-bottom:2px solid var(--rule);font-weight:700;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}.scroll table{white-space:nowrap}.scroll td:first-child{white-space:normal;min-width:9em}
.horses th,.horses td:not(.cmt){white-space:nowrap}.horses .cmt{min-width:260px}.mark{font-weight:700;color:var(--acc)}tr.mk td{background:var(--acc-soft)}
.chart{width:100%;height:auto}.chart .ln{fill:none;stroke:var(--acc);stroke-width:2.5}.chart .base{stroke:var(--mut);stroke-dasharray:4 4}.chart .pt{fill:var(--acc)}.chart .lbl{fill:var(--mut);font-size:12px}.chart .end{text-anchor:end;fill:var(--fg)}.chart .mid{text-anchor:middle}
.days{list-style:none;padding:0;margin:0;background:var(--panel);border-top:2px solid var(--rule);border-bottom:1px solid var(--line)}.days li+li{border-top:1px solid var(--line)}
.days a{display:flex;justify-content:space-between;gap:12px;padding:9px 10px;color:var(--fg)}.days a:hover{text-decoration:none;background:var(--acc-soft)}.days a span:last-child{color:var(--mut);white-space:nowrap}
.pn{display:flex;justify-content:space-between;gap:12px;margin:24px 0;font-size:14px}
.foot{color:var(--mut);font-size:12px;padding:20px 16px 44px;border-top:3px solid var(--rule);max-width:960px}.foot .sns a,.foot .sitemap-links a{color:var(--fg)}
.sp{display:grid;grid-template-columns:270px 1fr;gap:16px}.sp img{width:100%;height:auto}.sp pre{white-space:pre-wrap;font:inherit;font-size:13px;background:var(--panel);padding:8px;border:1px solid var(--line)}
@media (max-width:720px){.sp{grid-template-columns:1fr}}
/* 全頭評価：馬柱 */
.hl{list-style:none;padding:0;margin:0;background:var(--panel);border-top:2px solid var(--rule)}.hr{display:grid;grid-template-columns:48px 28px minmax(150px,1.4fr) 70px 64px 76px 48px 2.2fr;gap:4px 10px;align-items:start;padding:8px 6px;border-bottom:1px solid var(--line);font-size:14px}
.hr small{display:block;color:var(--mut);font-size:12px;font-weight:400}.hr.hd{font-size:12px;color:var(--mut);font-weight:700;border-bottom:2px solid var(--rule)}
.hr.mk{background:var(--acc-soft)}.hr.top .c-fn{color:var(--hit);font-weight:700}.c-cm{color:var(--fg);font-size:13px;line-height:1.6}.c-mk{font-size:18px;color:var(--acc);font-weight:700;line-height:1}
.fr{display:inline-block;min-width:28px;text-align:center;border-radius:2px;border:1px solid var(--line);padding:1px 4px;font-weight:700}
.f1{background:#fff;color:#111}.f2{background:#222;color:#fff}.f3{background:#d33;color:#fff}.f4{background:#2a5bd7;color:#fff}.f5{background:#f2c200;color:#111}.f6{background:#1f8f4a;color:#fff}.f7{background:#f08a24;color:#111}.f8{background:#f4a6c6;color:#111}
.tag{display:inline-block;margin-left:4px;font-size:11px;border-radius:2px;padding:0 4px}.tag.good{background:var(--acc);color:#fff}.tag.bad{background:var(--line);color:var(--fg)}
.bias .conf{margin-left:8px;vertical-align:middle}
@media (max-width:720px){h1{font-size:24px}.roi-badge{border:0;padding:0;font-size:12px;flex-basis:100%;margin:0}.roi-badge b{font-size:16px}.logo b{font-size:20px}.logo small{font-size:11px}.hr.hd{display:none}.hr{grid-template-columns:40px 22px 1fr 1fr 1fr;grid-template-areas:"no mk nm nm fn" "no mk od sc vl" "cm cm cm cm cm";padding:10px 4px;gap:4px 8px}
.c-no{grid-area:no}.c-mk{grid-area:mk}.c-nm{grid-area:nm}.c-fn{grid-area:fn;text-align:right}.c-od{grid-area:od}.c-sc{grid-area:sc}.c-vl{grid-area:vl;text-align:right}.c-cm{grid-area:cm}
.c-od::before{content:"単勝";display:block;color:var(--mut);font-size:11px}.c-sc::before{content:"評価点";display:block;color:var(--mut);font-size:11px}.c-vl::before{content:"妙味";display:block;color:var(--mut);font-size:11px}
.kpis div{flex-basis:46%}.kpis div:nth-child(2n){border-right:0}.kpis div{border-bottom:1px solid var(--line)}}
/* コラム */
.col{line-height:1.9;max-width:720px}.col .hero{width:100%;height:auto;margin:8px 0}.col h2{margin:32px 0 10px}.col table{margin:8px 0}
.note{border:1px dashed var(--line);padding:8px 12px;font-size:14px;color:var(--mut)}
.draft{background:#fff4d6;color:#6b4e00;padding:6px 10px;font-size:13px;margin-top:12px}
.cols{list-style:none;padding:0;margin:0;background:var(--panel);border-top:2px solid var(--rule);border-bottom:1px solid var(--line)}.cols li+li{border-top:1px solid var(--line)}.cols a{display:flex;flex-direction:column;gap:2px;padding:10px 12px;color:var(--fg)}.cols a:hover{text-decoration:none;background:var(--acc-soft)}.cols span{color:var(--mut);font-size:13px}
@media (prefers-reduced-motion:no-preference){nav a,.races a,.days a{transition:background-color .15s}}
/* 日付タブ・競馬場タブ */
.dtabs{display:flex;gap:0;margin:14px 0 10px;border-bottom:2px solid var(--rule);overflow-x:auto;scrollbar-width:none}.dtabs::-webkit-scrollbar{display:none}
.dtabs a{white-space:nowrap;padding:7px 14px;color:var(--fg);border:1px solid var(--line);border-bottom:0;background:var(--panel);margin-right:-1px;font-size:14px;line-height:1.3;display:flex;flex-direction:column;align-items:center}.dtabs a small{font-size:10px;color:var(--mut)}
.dtabs a.on{background:var(--rule);color:var(--bg);border-color:var(--rule)}.dtabs a.on small{color:var(--bg)}.dtabs a.more{margin-left:auto;border:0;background:none;color:var(--acc);font-size:13px;justify-content:center}.dtabs a:hover{text-decoration:none}
.filters.vtabs{gap:0;margin:16px 0 0;border-bottom:1px solid var(--line)}.filters.vtabs button{border:0;border-bottom:3px solid transparent;margin-bottom:-1px;background:none;padding:6px 12px;font-size:14px}.filters.vtabs button.on{background:none;color:var(--acc);border-bottom-color:var(--acc);font-weight:700}
.filters[data-kind=conf]{margin:8px 0 4px}.filters[data-kind=conf] button{font-size:12px;padding:2px 10px}
/* 目玉レース */
.hero{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);gap:0 20px;align-items:center;background:var(--panel);border-top:3px solid var(--rule);border-bottom:1px solid var(--line);margin:0 0 14px;padding:14px}
.hero img{width:100%;height:auto;display:block;border:1px solid var(--line)}.hero h2{border:0;padding:0;margin:2px 0 4px;font-size:22px}.hero h2 a{color:var(--fg)}.hero .meta{margin:0 0 8px}
.hlabel{margin:0;font-size:13px;color:var(--mut)}.hmarks{display:flex;flex-wrap:wrap;gap:4px 18px;margin:4px 0;font-weight:700}.hmarks b{color:var(--acc);font-size:20px;margin-right:4px;font-family:"Shippori Mincho B1",serif}
.hres{margin:6px 0 0;font-weight:700;font-size:15px}.hres.miss{color:var(--miss)}
@media (max-width:720px){.hero{grid-template-columns:1fr;gap:10px;padding:12px}.hero h2{font-size:20px}}
/* レース行 */
.rlist a{display:grid;grid-template-columns:52px minmax(0,1.4fr) minmax(0,1fr) 30px auto;gap:2px 10px;align-items:center;padding:8px 10px 8px 8px}
.rb{display:inline-block;background:var(--rule);color:var(--bg);font-weight:700;font-size:13px;text-align:center;padding:3px 0;border-radius:2px;line-height:1.2;font-family:"Shippori Mincho B1",serif}
.rinfo{display:flex;flex-direction:column;min-width:0}.rname{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.rsub{color:var(--mut);font-size:12px;white-space:nowrap}
.rlist .hon{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.rlist .res{text-align:right;white-space:nowrap}
.rlist li.gone .rb{background:var(--mut)}.rlist li.next .rb{background:var(--acc)}.rlist li.next .rsub::after{content:"　次に発走";color:var(--acc);font-weight:700}
.gr{display:inline-block;margin-left:6px;font-size:11px;font-weight:700;padding:0 6px;border-radius:2px;color:#fff;line-height:18px;vertical-align:middle;font-family:"BIZ UDPGothic",sans-serif}
.g1{background:#1b4fd8}.g2{background:#d0342c}.g3{background:#2b8a3e}.gj{background:#6b3fa0}.gl{background:#555}
@media (max-width:720px){.rlist a{grid-template-columns:44px minmax(0,1fr) 28px;grid-template-areas:"rb info conf" "rb hon hon" "rb res res"}.rlist .rb{grid-area:rb;align-self:start}.rlist .rinfo{grid-area:info}.rlist .conf{grid-area:conf}.rlist .hon{grid-area:hon;white-space:normal}.rlist .res{grid-area:res;text-align:left}}
h1 small{display:block;font-size:14px;color:var(--mut);font-family:"BIZ UDPGothic",sans-serif;font-weight:400;margin-top:2px}

.banner{margin:6px 0 14px}.banner img{width:100%;height:auto;aspect-ratio:16/5;object-fit:cover;object-position:right center;display:block;border:1px solid var(--line)}@media (max-width:720px){.banner img{aspect-ratio:16/8}}.live .banner{margin:4px 0 10px}.venue-pic{float:right;width:min(42%,360px);margin:0 0 10px 16px}.venue-pic img{width:100%;height:auto;display:block;border:1px solid var(--line)}@media (max-width:720px){.venue-pic{float:none;width:100%;margin:0 0 10px}}

.support{margin-top:10px}.btn{display:inline-block;background:var(--acc);color:#fff;padding:7px 16px;border-radius:2px;font-weight:700}.btn:hover{text-decoration:none;opacity:.9}

.contact{max-width:560px;display:grid;gap:12px}.contact label{display:grid;gap:4px;font-size:14px;font-weight:700}.contact input,.contact select,.contact textarea{font:inherit;font-weight:400;padding:8px 10px;border:1px solid var(--line);border-radius:2px;background:var(--panel);color:var(--fg);width:100%}.contact textarea{resize:vertical}.contact .btn{border:0;font:inherit;font-weight:700;cursor:pointer;justify-self:start}

.notice{background:var(--acc-soft);border-left:4px solid var(--acc);padding:8px 12px;margin:12px 0;font-size:14px}.notice.stale{background:#fff4d6;border-left-color:#c98a00;color:#5a3d00}.odds{display:block;color:var(--mut);font-size:12px;font-weight:400}.rlist .hon{white-space:normal}

.term{color:inherit;border-bottom:1px dotted var(--acc);text-decoration:none}.term:hover{color:var(--acc);text-decoration:none}.plain{background:var(--panel);border:1px solid var(--line);padding:8px 12px;margin:0 0 10px;font-size:15px}.gloss dt{font-weight:700;margin-top:14px;font-family:"Shippori Mincho B1",serif;font-size:17px}.gloss dd{margin:2px 0 0;padding-left:0}.log{padding-left:1.2em}.log li{margin:6px 0}

.srch{position:relative;margin:0 0 6px}.srch input{width:100%;max-width:360px;font:inherit;font-size:14px;padding:6px 10px;border:1px solid var(--line);border-radius:2px;background:var(--panel);color:var(--fg)}.sres{position:absolute;z-index:20;left:0;top:100%;width:100%;max-width:360px;background:var(--panel);border:1px solid var(--line);box-shadow:0 6px 18px rgba(0,0,0,.08)}.sres a{display:flex;flex-direction:column;padding:6px 10px;color:var(--fg);border-bottom:1px solid var(--line)}.sres a:hover{background:var(--acc-soft);text-decoration:none}.sres small{color:var(--mut);font-size:12px}.sres p{padding:6px 10px}#sr a{display:flex;justify-content:space-between;gap:12px;padding:8px 10px;border-bottom:1px solid var(--line);color:var(--fg)}#sr{background:var(--panel);border-top:2px solid var(--rule)}

:root[data-theme=dark]{--bg:#141614;--panel:#1c1f1c;--fg:#ecefe9;--mut:#a4aba5;--line:#343934;--rule:#ecefe9;--acc:#6cc497;--acc-soft:#1f2e26;--hit:#ff7b8c;--hit-soft:#3a2126;--tg:#d9a93a;--miss:#8b918c}
:root[data-theme=light]{--bg:#f2f3f0;--panel:#fff;--fg:#17201b;--mut:#5f6761;--line:#d9dcd6;--rule:#17201b;--acc:#146b45;--acc-soft:#e3efe8;--hit:#c0122d;--hit-soft:#fbe9ec;--tg:#8a6100;--miss:#7a807b}
.skip{position:absolute;left:-999px;top:8px;background:var(--rule);color:var(--bg);padding:6px 12px;z-index:50}.skip:focus{left:8px}
.totop{position:fixed;right:14px;bottom:18px;width:40px;height:40px;border-radius:50%;background:var(--rule);color:var(--bg);display:flex;align-items:center;justify-content:center;font-size:18px;box-shadow:0 2px 8px rgba(0,0,0,.2);z-index:30}.totop:hover{text-decoration:none}
.prefs .theme{border:1px solid var(--line);background:var(--panel);color:var(--fg);border-radius:2px;padding:2px 10px;font:inherit;font-size:12px;cursor:pointer}
th.sortable{cursor:pointer;user-select:none}th.sortable:hover{color:var(--acc)}th[data-dir=asc]::after{content:" ▲";font-size:10px}th[data-dir=desc]::after{content:" ▼";font-size:10px}
.cd{color:var(--acc);font-weight:700}
"""

JS = """(function(){
function ga(n,p){try{if(window.gtag)gtag('event',n,p||{})}catch(e){}}
document.addEventListener('click',function(e){var a=e.target.closest('a');if(!a)return;var h=a.href||'';
 if(a.closest('.share')){ga('share',{method:/line/.test(h)?'line':'x',page:location.pathname});return;}
 if(/x\\.com\\/zentou_log|instagram\\.com\\/zentou_log/.test(h)){ga('sns_follow',{network:/instagram/.test(h)?'instagram':'x'});return;}
 if(a.dataset.aff){ga('affiliate_click',{program:a.dataset.aff,page:location.pathname});}});
(function(){var p=location.pathname,best=null;document.querySelectorAll('header nav a').forEach(function(a){var h=a.getAttribute('href');if(h==='/'?(p==='/'||/^[/]\\d{4}[/]/.test(p)):p.indexOf(h)===0){if(!best||h.length>best.getAttribute('href').length)best=a;}});if(best)best.classList.add('on');})();
(function(){var f=document.querySelector('.srch'),inp=f&&f.querySelector('input'),box=f&&f.querySelector('.sres'),idx=null,t;
 function norm(x){return (x||'').normalize('NFKC').replace(/[\\s　]/g,'').toLowerCase();}
 function load(cb){if(idx)return cb(idx);fetch('/search.json').then(function(r){return r.json()}).then(function(j){idx=j;cb(j)}).catch(function(){cb({})});}
 function render(q,el,limit){var k=norm(q);if(!k){el.innerHTML='';el.hidden=true;return;}load(function(j){var E=j.e||[],R=j.r||[];var hits=E.filter(function(e){return norm(e[0]).indexOf(k)>=0}).slice(0,limit);
  el.innerHTML=hits.length?hits.map(function(e){var r=R[e[2]]||['#',''];return "<a href='"+r[0]+"'><b>"+e[0]+"</b><small>"+e[1]+(r[1]?'・'+r[1]:'')+"</small></a>"}).join(''):"<p class='meta'>見つかりませんでした。</p>";el.hidden=false;});}
 if(inp){inp.addEventListener('input',function(){clearTimeout(t);t=setTimeout(function(){render(inp.value,box,8)},120)});
  inp.addEventListener('blur',function(){setTimeout(function(){box.hidden=true},200)});inp.addEventListener('focus',function(){if(inp.value)render(inp.value,box,8)});
  f.addEventListener('submit',function(e){if(!inp.value.trim())e.preventDefault();});}
 var sr=document.getElementById('sr');if(sr){var q=new URLSearchParams(location.search).get('q')||'';if(inp)inp.value=q;render(q,sr,100);sr.hidden=false;}})();
(function(){var el=document.getElementById('me');if(!el)return;var picks=[];try{for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);if(k&&k.indexOf('vs:')===0){var m=k.match(/^vs:(\\d{8}):(.+)$/);if(m)picks.push({d:m[1],path:m[2],pick:localStorage.getItem(k)});}}}catch(e){}
 if(!picks.length){el.innerHTML="<p>まだ選んだレースがありません。<a href='/'>今日の予想</a>のレースページで、発走前に自分の◎を選べます。</p>";return;}
 var dates=picks.map(function(p){return p.d}).filter(function(v,i,a){return a.indexOf(v)===i});var win=0,lose=0,draw=0,pend=0,rows=[];
 Promise.all(dates.map(function(d){return fetch('/vsdata/'+d+'.json').then(function(r){return r.ok?r.json():{}}).catch(function(){return {}}).then(function(j){return [d,j]})})).then(function(all){var data={};all.forEach(function(x){data[x[0]]=x[1]});
  picks.sort(function(a,b){return a.d<b.d?1:-1}).forEach(function(p){var r=(data[p.d]||{})[p.path];if(!r||!r.fin||!Object.keys(r.fin).length){pend++;rows.push([p,null]);return;}var me=parseInt(r.fin[p.pick])||99,ai=parseInt(r.fin[String(r.ai)])||99;var res=me<ai?'win':me>ai?'lose':'draw';if(res==='win')win++;else if(res==='lose')lose++;else draw++;rows.push([p,{me:r.fin[p.pick]||'-',ai:r.fin[String(r.ai)]||'-',aiNo:r.ai,res:res,label:r.label}]);});
  var html="<div class='kpis'><div><b>"+win+"勝"+lose+"敗"+(draw?draw+"分":"")+"</b><span>あなた vs AI</span></div><div><b>"+(win+lose?Math.round(100*win/(win+lose)):0)+"%</b><span>あなたの勝率</span></div><div><b>"+pend+"</b><span>結果待ち</span></div></div>";
  html+="<ul class='days'>"+rows.map(function(x){var p=x[0],r=x[1];var lab=r?r.label:p.path;var t=r?("あなた◎"+p.pick+"番 "+r.me+"着／AI◎"+r.aiNo+"番 "+r.ai+"着 → "+(r.res==='win'?'あなたの勝ち':r.res==='lose'?'AIの勝ち':'引き分け')):("あなた◎"+p.pick+"番　結果待ち");return "<li><a href='"+p.path+"'><span>"+p.d.slice(4,6).replace(/^0/,'')+"/"+p.d.slice(6).replace(/^0/,'')+" "+lab+"</span><span>"+t+"</span></a></li>"}).join('')+"</ul>";el.innerHTML=html;});})();
var st={venue:'all',conf:'all'};try{var sv=JSON.parse(localStorage.getItem('filters')||'{}');if(sv.venue&&document.querySelector(".filters button[data-venue='"+sv.venue+"']"))st.venue=sv.venue;if(sv.conf)st.conf=sv.conf;}catch(e){}
document.querySelectorAll('.filters').forEach(function(f){var k=f.dataset.kind;f.querySelectorAll('button').forEach(function(b){b.classList.toggle('on',b.dataset[k]===st[k])});});if(st.venue!=='all'||st.conf!=='all')setTimeout(function(){apply()},0);
(function(){var b=document.querySelector('.totop');if(!b)return;window.addEventListener('scroll',function(){b.hidden=window.scrollY<800},{passive:true});})();
(function(){var btn=document.querySelector('.theme');if(!btn)return;var modes=['auto','light','dark'],lbl={auto:'表示：自動',light:'表示：ライト',dark:'表示：ダーク'};var m='auto';try{m=localStorage.getItem('theme')||'auto'}catch(e){}
 function apply(){if(m==='auto')document.documentElement.removeAttribute('data-theme');else document.documentElement.setAttribute('data-theme',m);btn.textContent=lbl[m];btn.dataset.mode=m;}
 apply();btn.addEventListener('click',function(){m=modes[(modes.indexOf(m)+1)%3];try{localStorage.setItem('theme',m)}catch(e){}apply();});})();
(function(){document.querySelectorAll('table').forEach(function(t){var ths=t.querySelectorAll('thead th');if(ths.length<2||t.querySelectorAll('tbody tr').length<3)return;ths.forEach(function(th,i){th.classList.add('sortable');th.addEventListener('click',function(){var tb=t.querySelector('tbody'),rows=[].slice.call(tb.rows),asc=th.dataset.dir!=='asc';
  rows.sort(function(a,b){var x=(a.cells[i]||{}).textContent||'',y=(b.cells[i]||{}).textContent||'';var nx=parseFloat(x.replace(/[^0-9.+-]/g,'')),ny=parseFloat(y.replace(/[^0-9.+-]/g,''));if(!isNaN(nx)&&!isNaN(ny))return asc?nx-ny:ny-nx;return asc?x.localeCompare(y,'ja'):y.localeCompare(x,'ja');});
  rows.forEach(function(r){tb.appendChild(r)});ths.forEach(function(h){delete h.dataset.dir});th.dataset.dir=asc?'asc':'desc';});});});})();
(function(){var li=document.querySelector('.races li.next');if(!li)return;var p=li.dataset.post;if(!p||p.length<12)return;var t=new Date(p.slice(0,4)+'-'+p.slice(4,6)+'-'+p.slice(6,8)+'T'+p.slice(8,10)+':'+p.slice(10,12)+':00+09:00').getTime();var el=li.querySelector('.rsub');if(!el)return;var sp=document.createElement('span');sp.className='cd';el.appendChild(sp);
 function tick(){var m=Math.round((t-Date.now())/60000);sp.textContent=m>0?'　あと'+(m>=60?Math.floor(m/60)+'時間'+(m%60)+'分':m+'分'):'';}tick();setInterval(tick,30000);})();
function apply(){document.querySelectorAll('.races li').forEach(function(li){
 var ok=(st.venue==='all'||li.dataset.venue===st.venue)&&(st.conf==='all'||li.dataset.conf===st.conf);li.style.display=ok?'':'none';});}
document.querySelectorAll('.filters').forEach(function(f){f.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;
 f.querySelectorAll('button').forEach(function(x){x.classList.toggle('on',x===b)});var k=f.dataset.kind;st[k]=b.dataset[k];try{localStorage.setItem('filters',JSON.stringify(st))}catch(e){}apply();});});
var now=new Date(Date.now()+9*3600e3),s=now.toISOString().replace(/[-:T]/g,'').slice(0,12),first=null;
(function(){var b=document.body.dataset.built;if(!b)return;var age=(Date.now()-Date.parse(b))/36e5;var st=document.querySelector('.notice.stale');if(st&&age>6)st.hidden=false;
 if(document.querySelector('.today')&&document.querySelector('.races li[data-post]')){var pend=[].some.call(document.querySelectorAll('.races li[data-post]'),function(li){return !li.querySelector('.res.hit,.res.miss,.res.tg')&&li.dataset.conf!=='見送り'});
  if(pend){setInterval(function(){if(document.visibilityState==='visible'&&(Date.now()-(window.__lastHide||0))>0)location.reload();},5*60*1000);}}})();
document.querySelectorAll('.races li[data-post]').forEach(function(li){var p=li.dataset.post;if(p.length<12)return;
 if(p<=s){li.classList.add('gone');if(!li.querySelector('.res')&&li.dataset.conf!=='見送り'){var w=document.createElement('span');w.className='res wait';w.textContent='結果待ち';li.querySelector('a').appendChild(w);}}else if(!first){first=li;}});
if(first&&document.body.contains(first)&&document.querySelector('.today')){first.classList.add('next');first.id='next';}
var tl=document.querySelector('.today ul.races:not(.picks ul)'),tb=document.querySelector('.toggle-gone'),tn=document.querySelector('.to-next');
if(tl&&tb){var gone=tl.querySelectorAll('li.gone');if(gone.length>3&&first){gone.forEach(function(li,i){if(i>=gone.length-2)li.classList.add('keep')});tl.classList.add('fold');tb.textContent='発走済み'+gone.length+'レースを表示';
 tb.addEventListener('click',function(){var f=tl.classList.toggle('fold');tb.textContent=f?'発走済み'+gone.length+'レースを表示':'発走済みを隠す';ga('toggle_gone',{open:!f});});}else{tb.style.display='none';}}
if(tn&&!first){tn.style.display='none';}
document.querySelectorAll('.vs').forEach(function(v){
 var key=v.dataset.key,fin={},pick=null;try{fin=JSON.parse(v.dataset.fin||'{}')}catch(e){}
 try{pick=localStorage.getItem(key)}catch(e){}
 var started=v.dataset.post<=s,r=v.querySelector('.r'),sel=v.querySelector('select'),btn=v.querySelector('.go');
 function show(){
  if(!pick){if(started){v.querySelector('.pick').style.display='none';r.textContent='発走済みのため選べません。';}return;}
  v.querySelector('.pick').style.display='none';
  var me=fin[pick],ai=fin[v.dataset.ai];
  if(!me){r.textContent='あなたの◎は'+pick+'番。結果が出たら勝敗を表示します。';return;}
  var a=parseInt(me)||99,b=parseInt(ai)||99,res=a<b?'あなたの勝ち！':a>b?'AIの勝ち':'引き分け';
  r.textContent='あなたの◎'+pick+'番は'+me+'着、AIの◎'+v.dataset.ai+'番は'+(ai||'-')+'着 → '+res;
  var t=v.dataset.label+'で競馬全頭ログのAIと勝負：'+res+'（私の◎'+pick+'番'+me+'着／AIの◎'+(ai||'-')+'着）';
  var a2=document.createElement('a');a2.href='https://twitter.com/intent/tweet?text='+encodeURIComponent(t)+'&url='+encodeURIComponent(v.dataset.url)+'&hashtags='+encodeURIComponent('競馬全頭ログ');a2.target='_blank';a2.rel='noopener';a2.textContent='結果をXでシェア';
  var d=document.createElement('div');d.className='share';d.appendChild(a2);v.appendChild(d);}
 if(btn)btn.addEventListener('click',function(){if(!sel.value||v.dataset.post<=s)return;pick=sel.value;try{localStorage.setItem(key,pick)}catch(e){}ga('vs_pick',{race:v.dataset.label});show();});
 show();});
})();"""


import hashlib as _hashlib
ASSET_V = _hashlib.md5((CSS + JS).encode("utf-8")).hexdigest()[:8]


def build() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    (OUT / "style.css").write_text(CSS, encoding="utf-8")
    (OUT / "manifest.webmanifest").write_text(json.dumps({
        "name": SITE_NAME, "short_name": SITE_NAME, "start_url": "/", "display": "standalone", "background_color": "#f2f3f0", "theme_color": "#146b45", "lang": "ja",
        "icons": [{"src": "/assets/logo-mark.png", "sizes": "512x512", "type": "image/png"}, {"src": "/assets/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"}]},
        ensure_ascii=False), encoding="utf-8")
    (OUT / "ads.txt").write_text(f"google.com, {ADSENSE_PUB.replace('ca-', '')}, DIRECT, f08c47fec0942fa0\n", encoding="utf-8")
    (OUT / "app.js").write_text(JS, encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    global HEADER_ROI
    led0 = ledger()
    mon = datetime.now(JST).strftime("%Y%m")
    mrows = [r for r in led0 if r["date"].startswith(mon)] or [r for r in led0 if r["date"][:6] == max((x["date"][:6] for x in led0), default="")]
    if mrows:
        st0, rt0 = sum(int(r["stake"]) for r in mrows), sum(int(r["return"]) for r in mrows)
        HEADER_ROI = (f"<a class='roi-badge' href='/results/'>{int(mrows[0]['date'][4:6])}月の回収率 <b>{roi_txt(st0, rt0)}</b>"
                      f"（{len(mrows)}R・外れ含む）</a>")
    if ASSETS.exists():
        shutil.copytree(ASSETS, OUT / "assets", ignore=shutil.ignore_patterns("og-base.png", "src"))
    og.site_image(OUT / "og" / "default.jpg", "全レースAI予想と回収率の記録",
                  ["中央競馬・地方競馬の全レースを毎日予想", "外れも含めた全成績を公開"])
    now = datetime.now(JST)
    today = now.strftime("%Y%m%d")
    global TODAY, ALL_DATES, BUILT_ISO
    TODAY = today
    BUILT_ISO = now.strftime('%Y-%m-%dT%H:%M:%S+09:00')
    dates = all_dates()
    ALL_DATES = list(dates)
    lastmod: dict[str, str] = {}
    venue_of_race: dict[str, str] = {}
    day_rows = []
    by_date = {}
    for d in dates:
        by_date[d] = predictions(d)
    # 内部リンク用：馬別・騎手別・コース別ページが作られる対象を先に数える
    _hc, _jc, _cc = defaultdict(int), defaultdict(int), defaultdict(int)
    for d, ps in by_date.items():
        for p in ps:
            for e in p.get("horses", []):
                nm = extra.nfkc(e.get("name") or "").replace(" ", "")
                if nm:
                    _hc[nm] += 1
            if d >= STATS_FROM:
                sc_ = scored(p)
                hon_ = p.get("marks", {}).get("◎")
                hh_ = next((x for x in p["_race"].get("horses", []) if x.get("number") == hon_), None) if sc_ and hon_ is not None else None
                if hh_ and hh_.get("jockey"):
                    _jc[extra.nfkc(hh_["jockey"]).replace(" ", "")] += 1
                r_ = p["_race"]
                if sc_ and sc_["stake"] and r_.get("distance"):
                    surf = "turf" if r_.get("surface") == "芝" else "jump" if r_.get("surface") == "障" else "dirt"
                    _cc[f"{VENUE_SLUG.get(venue_of(p), 'venue')}-{surf}-{int(r_['distance'])}"] += 1
    LINK_HORSES.clear(); LINK_HORSES.update(k for k, n in _hc.items() if n >= 2)
    LINK_JOCKEYS.clear(); LINK_JOCKEYS.update(k for k, n in _jc.items() if n >= 5)
    LINK_COURSES.clear(); LINK_COURSES.update(k for k, n in _cc.items() if n >= 5)
    for d in dates:
        ps = by_date[d]
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
        dog = "/og/default.jpg"
        if d >= (datetime.now(JST) - timedelta(days=OG_DAYS)).strftime("%Y%m%d"):
            dog = f"/og/{d}/day.jpg"
            _done = [scored(p) for p in ps if scored(p) and scored(p)["stake"]]
            og.site_image(OUT / dog.lstrip("/"), f"{fmt_date(d)}の予想　{len({venue_of(p) for p in ps})}場・{len(ps)}レース",
                          [f"確定{len(_done)}レース　的中{sum(1 for x in _done if x['return'] > 0)}　回収率{roi_txt(st, rt)}" if _done else "全レースの印・買い目を公開中",
                           "外れも含めた全成績を公開"])
        write(day_path(d), page(f"{fmt_date(d)}の競馬AI予想 全{len(ps)}レース | {SITE_NAME}",
                                f"<p class='crumb'><a href='/'>トップ</a> › {fmt_date(d)}</p><h1>{fmt_date(d)}のAI予想</h1>"
                                f"<p class='answer'>{fmt_date(d)}は{len({venue_of(p) for p in ps})}場・{len(ps)}レースを予想。当日回収率は{roi_txt(st, rt)}。</p>"
                                + day_list(d, ps), day_path(d),
                                desc=f"{fmt_date(d)}の競馬（JRA・地方）全{len(ps)}レースのAI予想と結果。当日回収率{roi_txt(st, rt)}。", og_image=dog))
        lastmod[day_path(d)] = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    # トップ：今日（無ければ最新日）を中心に
    led = ledger()
    t = totals(led)
    main_d = today if today in by_date else (dates[0] if dates else None)
    if main_d:
        head = "今日の予想" if main_d == today else f"{fmt_date(main_d)}の予想"
        top_list = f"<section class='today'>{day_list(main_d, by_date[main_d])}</section>"
    else:
        head, top_list = "今日の予想", "<p>予想はまだありません。</p>"
    past = "".join(f"<li><a href='{day_path(d)}'><span>{fmt_date(d)}（{n}レース）</span><span>回収率 {roi}</span></a></li>"
                   for d, n, roi in day_rows if d != main_d)
    body = (f"<h1>{head}<small>{fmt_date(main_d) if main_d else ''}</small></h1>"
            f"<p class='answer'>AIが日本の競馬（JRA・地方）の全レースを毎日予想し、外れも含めた成績を公開している。累計回収率は{t['roi']}（{t['n']}レース、◎複勝率{t['top3']}）。<a href='/results/'>成績の詳細</a>　<span class='meta'>最終更新 {now.strftime('%m/%d %H:%M')}</span></p>"
            + top_list + (f"<section id='past'><h2>過去の予想</h2><ul class='days'>{past}</ul></section>" if past else ""))
    site_ld = [{"@context": "https://schema.org", "@type": "Organization", "name": SITE_NAME, "url": BASE_URL + "/", "logo": BASE_URL + "/assets/logo-mark.png",
                "sameAs": [X_URL, IG_URL], "contactPoint": {"@type": "ContactPoint", "contactType": "customer support", "url": BASE_URL + "/contact/"}},
               {"@context": "https://schema.org", "@type": "WebSite", "name": SITE_NAME, "url": BASE_URL + "/",
                "potentialAction": {"@type": "SearchAction", "target": {"@type": "EntryPoint", "urlTemplate": BASE_URL + "/search/?q={search_term_string}"}, "query-input": "required name=search_term_string"}}]
    write("/", page(f"{SITE_NAME}｜今日の競馬AI予想（JRA・地方 全レース）と回収率", body, "/",
                    desc=f"AIが中央競馬・地方競馬の全レースを毎日予想。今日の予想と、外れも含めた全成績（累計回収率{t['roi']}）を公開。",
                    head_extra="".join(jsonld(x) for x in site_ld),
                    og_image=f"/og/{main_d}/day.jpg" if main_d and (OUT / "og" / main_d / "day.jpg").exists() else "/og/default.jpg"))
    write("/results/", results_page(led, venue_of_race))
    # 戦略別回収率
    sg = strategy.collect(by_date, STATS_FROM)
    s_body, s_rank = strategy.render(sg, esc, roi_txt, f"{int(STATS_FROM[4:6])}月{int(STATS_FROM[6:8])}日", fmt_date(max(by_date)) if by_date else "")
    s_best = f"回収率が最も高い買い方は「{s_rank[0][0]}」の{s_rank[0][1]:.1f}%（{s_rank[0][2]}レース）。" if s_rank else ""
    write("/strategy/", page(f"買い方別の回収率：◎単勝だけ・自信度別・期待値別で比べる | {SITE_NAME}",
                             f"<p class='crumb'><a href='/'>トップ</a> › <a href='/results/'>成績</a> › 買い方別</p><h1>買い方別の回収率</h1>{banner('strategy')}" + s_body
                             + "<p class='meta'>全体の成績は<a href='/results/'>成績ページ</a>、券種の説明は<a href='/column/baken-shurui/'>コラム</a>へ。</p>",
                             "/strategy/", desc=f"同じAI予想でも買い方で回収率はどう変わるか。◎の単勝だけ、自信度別、期待値別、人気別、券種別の回収率を全レースの実データで比較。{s_best}"))
    lastmod.update(venue_pages(by_date, led, venue_of_race))
    import sys as _sys
    lastmod.update(extra.build_pages(_sys.modules[__name__], by_date, today))
    lastmod.update(review.build_pages(_sys.modules[__name__], by_date, today))
    lastmod.update(horses.build_pages(_sys.modules[__name__], by_date, today))
    lastmod.update(monthly.build_pages(_sys.modules[__name__], by_date, led, venue_of_race, today))
    FEED_EXTRA[:] = [(k, "重賞回顧 " + k.split("/")[2]) for k in lastmod if k.startswith("/review/2")][:3] + \
                    [(k, "月次レポート " + k.split("/")[2]) for k in lastmod if k.startswith("/monthly/2")][:2]
    # 検索索引（馬名・レース名・重賞名 → ページ）。小さく保つため、馬は最新1件のレースページへ
    idx: dict[str, list] = {}
    for d in sorted(by_date):  # 古い順に回して最新で上書き
        for p_ in by_date[d]:
            for e in p_.get("horses", []):
                nm = extra.nfkc(e.get("name") or "").replace(" ", "")
                if nm:
                    hp = OUT / "horse" / extra.short_id(nm) / "index.html"
                    idx[nm] = ["馬", f"/horse/{extra.short_id(nm)}/" if hp.exists() else race_path(d, p_), f"{md(d)} {VENUE_NAME.get(venue_of(p_), venue_of(p_))}{race_no(p_)}R"]
            rn = extra.nfkc(p_.get("race_name") or p_["_race"].get("race_name") or "").strip()
            if rn and extra.grade_of(p_["_race"], rn):
                cn = extra.clean_name(rn)
                idx[cn] = ["重賞", f"/graded/{extra.graded_slug(rn, VENUE_SLUG.get(venue_of(p_), 'venue'))}/", f"{md(d)} {VENUE_NAME.get(venue_of(p_), venue_of(p_))}"]
    for v, slug in VENUE_SLUG.items():
        if (OUT / "venue" / slug / "index.html").exists():
            idx[VENUE_NAME.get(v, v) + "競馬"] = ["競馬場", f"/venue/{slug}/", ""]
    for d, ps in by_date.items():
        fins = {}
        for p_ in ps:
            rows = (p_.get("_result") or {}).get("rows") or []
            if rows:
                fins[race_path(d, p_)] = {"ai": p_.get("marks", {}).get("◎"), "fin": {str(x.get("number")): str(x.get("finish")) for x in rows if x.get("number") is not None}, "label": race_label(p_)}
        (OUT / "vsdata").mkdir(exist_ok=True)
        (OUT / "vsdata" / f"{d}.json").write_text(json.dumps(fins, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    # 圧縮した形：{"r":[[path,label],...],"e":[[name,type,rIndex],...]}
    paths: dict[tuple, int] = {}
    ents = []
    for k, (typ, path_, lab) in idx.items():
        key = (path_, lab)
        if key not in paths:
            paths[key] = len(paths)
        ents.append([k, typ, paths[key]])
    (OUT / "search.json").write_text(json.dumps({"r": [list(k) for k in paths], "e": ents}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    write("/search/", page(f"検索 | {SITE_NAME}", "<p class='crumb'><a href='/'>トップ</a> › 検索</p><h1>検索</h1><p class='meta'>馬名・レース名・競馬場名で探せる。</p><div id='sr'></div>", "/search/", noindex=True))
    write("/me/", page(f"あなたの成績（AI vs あなた） | {SITE_NAME}",
                       "<p class='crumb'><a href='/'>トップ</a> › あなたの成績</p><h1>あなたの成績</h1>"
                       "<p class='answer'>各レースページの「AI vs あなた」で選んだ◎の成績。この端末のブラウザにだけ保存され、サーバーには送られない。</p>"
                       "<div id='me'><p class='meta'>読み込み中…</p></div>"
                       "<p class='meta'>勝敗は「あなたの◎の着順」と「AIの◎の着順」を比べて決める。同着は引き分け。結果が未確定のレースは数えない。</p>", "/me/", noindex=True))
    write("/glossary/", glossary_page())
    _vb = defaultdict(lambda: [0, 0, 0])
    for r in led:
        v = venue_of_race.get(r["race_id"], "")
        if v:
            _vb[v][0] += int(r["stake"]); _vb[v][1] += int(r["return"]); _vb[v][2] += 1
    _wv = min(((v, x) for v, x in _vb.items() if x[2] >= 20), key=lambda kv: kv[1][1] / kv[1][0], default=None)
    write("/limits/", limits_page(t, (VENUE_NAME.get(_wv[0], _wv[0]), roi_txt(_wv[1][0], _wv[1][1])) if _wv else None))
    write("/changelog/", changelog_page())
    write("/contact/", page(f"お問い合わせ | {SITE_NAME}", f"<p class='crumb'><a href='/'>トップ</a> › お問い合わせ</p>" + CONTACT, "/contact/",
                            desc="競馬全頭ログへのお問い合わせフォーム。予想やデータについてのご意見、不具合の報告、広告掲載・取材のご相談。"))
    write("/contact/thanks/", page(f"送信しました | {SITE_NAME}", THANKS, "/contact/thanks/", noindex=True))
    write("/about/", page(f"予想の方法とよくある質問 | {SITE_NAME}", ABOUT, "/about/", head_extra=jsonld(FAQ_LD),
                          desc="競馬全頭ログの予想の作り方（評価の5軸・印・自信度・買い目）と、回収率の計算方法。"))
    write("/operator/", page(f"運営者情報 | {SITE_NAME}", OPERATOR, "/operator/"))
    write("/privacy/", page(f"プライバシーポリシー | {SITE_NAME}", PRIVACY, "/privacy/"))
    today_iso = now.strftime("%Y-%m-%d")
    lastmod.update(column.build(write, page, jsonld, BASE_URL, SITE_NAME, STATS_FROM, today_iso))
    for old, new in (("results.html", "/results/"), ("about.html", "/about/")):
        (OUT / old).write_text(redirect_page(new), encoding="utf-8")
    social_page()
    write("/404.html", page(f"ページが見つかりません | {SITE_NAME}",
                            "<h1>ページが見つかりません</h1><p class='answer'>URLが変わったか、削除された可能性がある。上の検索欄で馬名やレース名から探せる。</p>"
                            "<ul><li><a href='/'>今日の予想</a></li><li><a href='/graded/'>重賞</a></li><li><a href='/results/'>成績</a></li><li><a href='/venue/'>競馬場別</a></li><li><a href='/column/'>コラム</a></li></ul>",
                            "/404.html", noindex=True))
    items = []
    for d, n, roi in day_rows[:30]:
        items.append(f"<item><title>{esc(fmt_date(d))}の競馬AI予想（{n}レース・回収率{esc(roi)}）</title>"
                     f"<link>{BASE_URL}{day_path(d)}</link><guid>{BASE_URL}{day_path(d)}</guid>"
                     f"<pubDate>{datetime.strptime(d, '%Y%m%d').replace(tzinfo=JST, hour=9).strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate>"
                     f"<description>{esc(fmt_date(d))}の中央・地方全{n}レースのAI予想と結果。当日回収率{esc(roi)}。</description></item>")
    for path_, title_ in [(x, y) for x, y in FEED_EXTRA][:10]:
        items.append(f"<item><title>{esc(title_)}</title><link>{BASE_URL}{path_}</link><guid>{BASE_URL}{path_}</guid>"
                     f"<pubDate>{now.strftime('%a, %d %b %Y %H:%M:%S %z')}</pubDate><description>{esc(title_)}</description></item>")
    (OUT / "feed.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>{SITE_NAME}</title><link>{BASE_URL}/</link><description>{SITE_SUB}</description><language>ja</language>"
        + "".join(items) + "</channel></rss>\n", encoding="utf-8")
    k = Path(__file__).resolve().parent / "indexnow_key.txt"
    if k.exists():
        (OUT / f"{k.read_text().strip()}.txt").write_text(k.read_text().strip(), encoding="utf-8")
    (OUT / "data").mkdir(exist_ok=True)
    if (ROOT / "results_ledger.csv").exists():
        shutil.copy(ROOT / "results_ledger.csv", OUT / "data" / "results_ledger.csv")
    (OUT / "CNAME").write_text(DOMAIN + "\n", encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n", encoding="utf-8")
    (OUT / "llms.txt").write_text(
        f"# {SITE_NAME}\n\n> AI（Claude）が日本の競馬（JRA・地方）の全レースを毎日予想し、外れも含めた全予想の回収率を公開するサイト。\n\n"
        f"- [今日の予想]({BASE_URL}/)\n- [成績・回収率]({BASE_URL}/results/)：累計{t['n']}レース・回収率{t['roi']}\n"
        f"- [買い方別の回収率]({BASE_URL}/strategy/)\n- [重賞回顧]({BASE_URL}/review/)\n- [馬別のAI評価履歴]({BASE_URL}/horse/)\n- [予想の方法]({BASE_URL}/about/)\n" + (f"- [初心者向けコラム]({BASE_URL}/column/)：馬券の種類・回収率・人気と勝率などを実データで解説\n" if HAS_COLUMN else "") + f"- [全予想の記録CSV]({REPO}/blob/main/results_ledger.csv)\n", encoding="utf-8")
    fixed = {"/": today_iso, "/results/": today_iso, "/strategy/": today_iso, "/about/": None, "/contact/": None, "/glossary/": None, "/limits/": today_iso, "/changelog/": today_iso, "/operator/": None, "/privacy/": None}
    sm = "".join(f"<url><loc>{BASE_URL}{u}</loc>{f'<lastmod>{m}</lastmod>' if m else ''}</url>"
                 for u, m in list(fixed.items()) + sorted(lastmod.items(), reverse=True))
    (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + sm + "</urlset>\n", encoding="utf-8")
    print(f"built {len(dates)} days into {OUT}")


if __name__ == "__main__":
    build()
