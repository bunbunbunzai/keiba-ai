"""作ったサイト（_site）を本物のブラウザで開いて、画面の動きを確かめる（手元で実行。公開の手順では動かさない）。

使い方: python tests/site_smoke_js.py [サイトのフォルダ] [--chrome /usr/bin/google-chrome]
- Playwright（pip install playwright）と Chrome が要る。外部への通信（広告・解析）は止めて開く。
- 時計を決まった時刻に止めて、「最終更新から時間がたっています」が出る・出ないを確かめる。
"""
from __future__ import annotations

import argparse
import functools
import http.server
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

JST = timezone(timedelta(hours=9))


def serve(root: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):  # noqa: ARG002  開いたファイルを1行ずつ出さない
            pass

    h = functools.partial(Quiet, directory=str(root))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def open_at(browser, url: str, when: datetime | None = None, built: datetime | None = None):
    """url を開く。when でブラウザの時計を止め、built でページを作った時刻（body の data-built）を差し替える。"""
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    pg = ctx.new_page()

    def route(r):
        if not r.request.url.startswith("http://127.0.0.1"):
            return r.abort()
        if built and r.request.url == url:
            res = r.fetch()
            body = re.sub(r'data-built="[^"]+"', f'data-built="{built.isoformat()}"', res.text(), count=1)
            return r.fulfill(response=res, body=body)
        return r.continue_()

    pg.route("**/*", route)
    if when:
        pg.clock.install(time=when)
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url, wait_until="load")
    pg.wait_for_timeout(300)
    return ctx, pg, errs


def built_at(site: Path, rel: str) -> datetime:
    s = (site / rel).read_text(encoding="utf-8")
    return datetime.fromisoformat(re.search(r'data-built="([^"]+)"', s).group(1))


def post_times(site: Path, rel: str) -> list[datetime]:
    s = (site / rel).read_text(encoding="utf-8")
    return sorted({datetime.strptime(p, "%Y%m%d%H%M").replace(tzinfo=JST) for p in re.findall(r"data-post='(\d{12})'", s)})


# ---- 点検 ----
def check_race_toc(browser, base: str, site: Path) -> list[str]:
    """レースページの目次（ページの上のボタンの並び）に、1文字だけの項目（全頭くんの「×」など）が無い。"""
    races = sorted(site.glob("20[0-9][0-9]/*/*/*/*r/index.html"))
    with_ask = [f for f in races if "class='zkh'" in f.read_text(encoding="utf-8")]
    out = []
    for f in (with_ask or races)[-2:]:
        rel = "/" + str(f.parent.relative_to(site)) + "/"
        ctx, pg, errs = open_at(browser, base + rel)
        items = pg.eval_on_selector_all("ul.rtoc a", "els => els.map(e => e.textContent.trim())")
        if not items:
            out.append(f"{rel}：目次が無い")
        if short := [t for t in items if len(t) <= 1]:
            out.append(f"{rel}：目次に1文字の項目がある：{short}")
        if errs:
            out.append(f"{rel}：スクリプトのエラー：{errs[:2]}")
        ctx.close()
    return out


def check_stale_notice(browser, base: str, site: Path) -> list[str]:
    """「最終更新から時間がたっています」は、ページが6時間より古く、発走を過ぎても結果が無いレースがあるときだけ出る。"""
    built = built_at(site, "index.html")
    posts = post_times(site, "index.html")
    if not posts:
        return ["index.html：発走時刻の付いたレースが無く、確かめられない"]
    out = []

    def shown(when: datetime, as_built: datetime | None = None) -> bool:
        ctx, pg, errs = open_at(browser, base + "/", when, as_built)
        v = pg.evaluate("(() => { const e = document.querySelector('.notice.stale'); return !!e && !e.hidden; })()")
        if errs:
            out.append(f"スクリプトのエラー（{when:%H:%M}）：{errs[:2]}")
        ctx.close()
        return v

    # 1. 作ってすぐ（1時間後）は、何があっても出ない
    if shown(built + timedelta(hours=1)):
        out.append(f"作って1時間後（{built + timedelta(hours=1):%m/%d %H:%M}）なのに出ている")
    # 2. 朝：前の晩に作ったページ（10時間前）でも、最初のレースの発走前なら出ない（結果待ちのレースが無い）
    morning = posts[0] - timedelta(hours=1)
    if shown(morning, as_built=posts[0] - timedelta(hours=10)):
        out.append(f"最初のレース（{posts[0]:%H:%M}発走）の前の {morning:%H:%M} に、まだ結果待ちのレースが無いのに出ている")
    late = built + timedelta(hours=7)
    # 3. 作ったあとに発走するレースがあり、その発走を過ぎて7時間以上たてば出る（結果の反映が止まっている）
    after = [t for t in posts if t > built]
    if after:
        when = max(after[0] + timedelta(minutes=5), late)
        if not shown(when):
            out.append(f"{when:%m/%d %H:%M}：{after[0]:%H:%M}発走のレースの結果が無いまま7時間たったのに出ていない")
    return out


CHECKS = [check_race_toc, check_stale_notice]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("site", nargs="?", default=str(Path(__file__).resolve().parent.parent / "_site"))
    ap.add_argument("--chrome", default="")
    a = ap.parse_args()
    site = Path(a.site)
    srv, base = serve(site)
    bad = 0
    with sync_playwright() as p:
        b = p.chromium.launch(**({"executable_path": a.chrome} if a.chrome else {}), args=["--no-sandbox"])
        for chk in CHECKS:
            try:
                problems = chk(b, base, site)
            except Exception as e:  # noqa: BLE001
                problems = [f"点検が途中で止まった：{type(e).__name__}: {e}"]
            print(f"{'NG' if problems else 'ok'}  {chk.__name__[6:]}：{(chk.__doc__ or '').strip().splitlines()[0]}")
            for x in problems:
                print(f"      - {x}")
            bad += bool(problems)
        b.close()
    srv.shutdown()
    print(f"\n{len(CHECKS) - bad}/{len(CHECKS)} ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
