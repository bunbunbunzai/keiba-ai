"""作ったサイト（_site）の点検。公開の直前に走らせて、表示の崩れや出力の欠けを見つける。

使い方: python tests/site_smoke.py [サイトのフォルダ]    # 既定は _site
- 標準ライブラリだけで動く（公開の手順では pillow と requests しか入れていない）。
- 見つけた問題を1行ずつ出し、1つでもあれば終了コード 1。公開は止めない（pages.yml では continue-on-error）。
- ブラウザを動かす点検（目次・「最終更新から時間がたっています」の表示）は tests/site_smoke_js.py（手元で実行）。
"""
from __future__ import annotations

import csv
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "site"))

import sitekit  # noqa: E402

BASE = "https://www.ai-keiba-log.com"
HELP_URL = "https://www.jra.go.jp/news/other/izon.html"
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
GOOGLE_NOINDEX = '<meta name="googlebot" content="noindex">'
GENSEN_FROM = "20261111"  # 厳選レース（自信度A）を出し始めた日（site/build.py と同じ）


def read(site: Path, rel: str) -> str:
    f = site / rel
    return f.read_text(encoding="utf-8") if f.exists() else ""


def text_of(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment))


def repeated_word(text: str) -> str:
    """同じ語が続いていたら、その語を返す。"""
    toks = text.split()
    return next((a for a, b in zip(toks, toks[1:]) if a == b), "")


def race_pages(site: Path) -> list[Path]:
    return sorted(site.glob("20[0-9][0-9]/[0-9][0-9]/[0-9][0-9]/*/*r/index.html"))


def day_pages(site: Path) -> list[Path]:
    return sorted(site.glob("20[0-9][0-9]/[0-9][0-9]/[0-9][0-9]/index.html"))


def sitemap_locs(xml: str) -> list[str]:
    return [u.findtext(f"{NS}loc") or "" for u in ET.fromstring(xml)]


def page_file(site: Path, url: str) -> Path:
    path = url[len(BASE):] if url.startswith(BASE) else url
    return site / path.lstrip("/") / "index.html" if path.endswith("/") else site / path.lstrip("/")


# ---- 点検 ----
def check_footer_helpline(site: Path) -> list[str]:
    """どのページのフッターにも、のめり込みが不安なときの相談先がある。"""
    out = []
    races = race_pages(site)
    for rel in ["index.html", "results/index.html", "column/index.html"] + ([str(races[-1].relative_to(site))] if races else []):
        s = read(site, rel)
        foot = s[s.find("<footer"):]
        if HELP_URL not in foot:
            out.append(f"{rel}：フッターに相談先（{HELP_URL}）へのリンクが無い")
    return out


def check_no_webfont(site: Path) -> list[str]:
    """見出しの Web フォントを読み込んでいない（読み込みの遅れで文字の幅が変わり、画面がずれていた）。"""
    out = []
    for rel in ("index.html", "style.css"):
        s = read(site, rel)
        for w in ("fonts.googleapis.com", "fonts.gstatic.com", "Shippori"):
            if w in s:
                out.append(f"{rel}：Web フォントの読み込みが残っている（{w}）")
    return out


def check_race_names(site: Path) -> list[str]:
    """レース名に、同じ語の繰り返しや全角の英数字が残っていない（題名・見出し・一覧）。"""
    out = []
    for f in race_pages(site):
        s = f.read_text(encoding="utf-8")
        for tag in ("title", "h1"):
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", s, re.S)
            t = text_of(m.group(1)) if m else ""
            if (w := repeated_word(t)) or re.search(r"[０-９Ａ-Ｚａ-ｚ]", t):
                out.append(f"{f.relative_to(site)}：<{tag}> のレース名が崩れている（{w or '全角の英数字'}）：{t.strip()[:60]}")
    for f in [site / "index.html"] + day_pages(site):
        s = f.read_text(encoding="utf-8") if f.exists() else ""
        for m in re.finditer(r"<span class='rname'>([^<]*)", s):
            if w := repeated_word(html.unescape(m.group(1))):
                out.append(f"{f.relative_to(site)}：一覧のレース名に同じ語が続いている（{w}）：{m.group(1)[:40]}")
                break
    return out[:20]


def check_gensen_zero_day(site: Path) -> list[str]:
    """厳選レースが無い日は、大きな枠を出さず1行だけにする。厳選を出し始めた日以降の一覧には、枠か1行のどちらかがある。"""
    out = []
    for f in [site / "index.html"] + day_pages(site):
        s = f.read_text(encoding="utf-8") if f.exists() else ""
        rel = f.relative_to(site)
        if "自信度A・0レース" in s:
            out.append(f"{rel}：厳選レースが0件なのに枠が出ている")
        if f.name == "index.html" and f.parent != site:
            day = "".join(f.parent.relative_to(site).parts)
            if day >= GENSEN_FROM and "class='races" in s and "gensen-box" not in s and "gensen-none" not in s:
                out.append(f"{rel}：厳選レースの枠も「この日は無い」の1行も無い")
    return out[:20]


def check_noindex_sitemap(site: Path) -> list[str]:
    """Google に載せない設定へ変わったページの一覧（Search Console から送る）がある。ふだんのサイトマップとは重ならない。"""
    xml = read(site, "sitemap-noindex.xml")
    if not xml:
        return ["sitemap-noindex.xml が無い"]
    out = []
    urls = [(u.findtext(f"{NS}loc") or "", u.findtext(f"{NS}lastmod") or "") for u in ET.fromstring(xml)]
    locs = [u for u, _ in urls]
    if not locs:
        out.append("sitemap-noindex.xml：1件も載っていない")
    if dup := set(locs) & set(sitemap_locs(read(site, "sitemap.xml"))):
        out.append(f"sitemap-noindex.xml：ふだんのサイトマップと重なっている（{len(dup)}件。例 {sorted(dup)[0]}）")
    now = datetime.now(timezone(timedelta(hours=9)))
    today = now.strftime("%Y-%m-%d")
    oldest = (now - timedelta(days=sitekit.NOINDEX_SITEMAP_DAYS + 1)).strftime("%Y-%m-%d")  # 日付をまたいで点検しても落ちないよう1日の余裕
    if off := [(u, d) for u, d in urls if not oldest <= d <= today]:
        out.append(f"sitemap-noindex.xml：更新日が範囲の外（今日より先、または{sitekit.NOINDEX_SITEMAP_DAYS}日より前）：{len(off)}件。例 {off[0]}")
    for u in locs[:30] + locs[::500]:
        s = page_file(site, u).read_text(encoding="utf-8")[:3000] if page_file(site, u).exists() else ""
        if GOOGLE_NOINDEX not in s:
            out.append(f"sitemap-noindex.xml：載っているのに、Google に載せない設定になっていない：{u}")
            break
    if "sitemap-noindex" in read(site, "robots.txt"):
        out.append("robots.txt：sitemap-noindex.xml が書かれている（Bing にも知らせてしまう）")
    return out


def check_sitemap_pages_are_indexable(site: Path) -> list[str]:
    """ふだんのサイトマップに載せたページは、検索に載せない設定になっていない（抜き取り）。"""
    locs = sitemap_locs(read(site, "sitemap.xml") or "<urlset/>")
    if not locs:
        return ["sitemap.xml：1件も載っていない"]
    for u in locs[:20] + locs[::40]:
        f = page_file(site, u)
        s = f.read_text(encoding="utf-8")[:3000] if f.exists() else ""
        if not s:
            return [f"sitemap.xml：載っているページのファイルが無い：{u}"]
        if GOOGLE_NOINDEX in s or '<meta name="robots" content="noindex">' in s:
            return [f"sitemap.xml：検索に載せない設定のページが載っている：{u}"]
    return []


def check_feed(site: Path) -> list[str]:
    """RSS が読める形で、コラムも載っている。"""
    xml = read(site, "feed.xml")
    try:
        items = ET.fromstring(xml).findall("./channel/item")
    except ET.ParseError as e:
        return [f"feed.xml：XML として読めない（{e}）"]
    out = []
    links = [i.findtext("link") or "" for i in items]
    if not any("/column/" in u for u in links):
        out.append("feed.xml：コラムが1本も載っていない")
    if len(set(links)) != len(links):
        out.append("feed.xml：同じページが2回載っている")
    for i in items:
        u = i.findtext("link") or ""
        if not u.startswith(BASE + "/") or not page_file(site, u).exists():
            out.append(f"feed.xml：リンク先のページが無い：{u}")
            break
        try:
            parsedate_to_datetime(i.findtext("pubDate") or "")
        except (TypeError, ValueError):
            out.append(f"feed.xml：日付の形がおかしい：{i.findtext('pubDate')}")
            break
    return out


def check_build_stats(site: Path) -> list[str]:
    """サイトの大きさの記録（毎日の見張りが読む）が、実際の大きさと合っている。"""
    try:
        st = json.loads(read(site, "build-stats.json"))
    except json.JSONDecodeError:
        return ["build-stats.json が無い、または読めない"]
    real = sitekit.dir_stats(site)
    out = []
    if abs(st.get("files", 0) - real["files"]) > 20:
        out.append(f"build-stats.json：ファイル数が実際と合わない（記録 {st.get('files')}・実際 {real['files']}）")
    if abs(st.get("bytes", 0) - real["bytes"]) > real["bytes"] * 0.02:
        out.append(f"build-stats.json：サイズが実際と合わない（記録 {st.get('bytes')}・実際 {real['bytes']}）")
    return out


def check_even_badge(site: Path) -> list[str]:
    """払戻が購入額と同じレースは「元返し」と出る（一覧とレースのページ）。"""
    f = site / "data" / "results_ledger.csv"
    if not f.exists():
        return ["data/results_ledger.csv が無い"]
    with f.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("stake") and r.get("stake") != "0" and r.get("stake") == r.get("return")]
    for r in reversed(rows):
        d = r["date"]
        s = read(site, f"{d[:4]}/{d[4:6]}/{d[6:8]}/index.html")
        if not s:
            continue  # 一覧のページを作っていない古い日
        out = []
        if "的中・元返し ±0円" not in s:
            out.append(f"{d[:4]}/{d[4:6]}/{d[6:8]}/：払戻が購入額と同じレース（{r['race_id']}）があるのに、一覧に「元返し」が無い")
        hrefs = re.findall(r"<a href='(/\d{4}/\d{2}/\d{2}/[^']+/)'>(?:(?!</a>).)*?res hit even", s, re.S)
        if hrefs and "元返し：払戻が購入額と同じ" not in read(site, hrefs[0].lstrip("/") + "index.html"):
            out.append(f"{hrefs[0]}：レースのページの結果に「元返し」が無い")
        return out
    return []


def check_strategy_baseline(site: Path) -> list[str]:
    """買い方別のページに、「1番人気を買うだけ」との比較がある。"""
    s = read(site, "strategy/index.html")
    m = re.search(r"<section class='card' id='baseline'>(.*?)</section>", s, re.S)
    if not m:
        return ["strategy/：「1番人気を買うだけ」との比較の欄が無い"]
    t = text_of(m.group(1))
    return [f"strategy/：比較の欄に「{w}」が無い" for w in ("1番人気の複勝", "1番人気の単勝", "このサイトの買い目") if w not in t]


def check_buy_guide_link(site: Path) -> list[str]:
    """G1 の特集まとめの「次に見る」から、馬券の買い方のガイドへ進める。"""
    out = []
    pages = sorted(site.glob("column/*-guide/index.html"))
    seen = 0
    for f in pages:
        s = f.read_text(encoding="utf-8")
        m = re.search(r"<section class='card nstep'>(.*?)</section>", s, re.S)
        if not m or "data-ns='feature'" not in m.group(1):
            continue
        seen += 1
        hrefs = re.findall(r"href='(/column/guide-(?:jra|chiho)-baken-kaikata/)'", m.group(1))
        if not hrefs:
            out.append(f"{f.relative_to(site)}：「次に見る」に馬券の買い方ガイドへの案内が無い")
        elif not (site / hrefs[0].lstrip("/") / "index.html").exists():
            out.append(f"{f.relative_to(site)}：案内先のページが無い（{hrefs[0]}）")
    if not seen:
        out.append("column/*-guide/：「次に見る」の付いた特集まとめが1つも見つからない")
    return out[:10]


CHECKS = [check_footer_helpline, check_no_webfont, check_race_names, check_gensen_zero_day, check_noindex_sitemap,
          check_sitemap_pages_are_indexable, check_feed, check_build_stats, check_even_badge, check_strategy_baseline,
          check_buy_guide_link]


def main() -> int:
    site = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "_site"
    if not (site / "index.html").exists():
        print(f"サイトが見つからない：{site}")
        return 1
    bad = 0
    for chk in CHECKS:
        try:
            problems = chk(site)
        except Exception as e:  # noqa: BLE001  点検そのものの不具合も「問題」として出す
            problems = [f"点検が途中で止まった：{type(e).__name__}: {e}"]
        print(f"{'NG' if problems else 'ok'}  {chk.__name__[6:]}：{(chk.__doc__ or '').strip().splitlines()[0]}")
        for p in problems:
            print(f"      - {p}")
        bad += bool(problems)
    print(f"\n{len(CHECKS) - bad}/{len(CHECKS)} ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
