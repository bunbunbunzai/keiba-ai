"""楽天競馬（keiba.rakuten.co.jp）の取得。地方競馬用。

robots.txt の Crawl-delay: 60 を守る（1ページ/60秒）。
禁止パス（/app/、/pcs/prediction/detail/）には触れない。

RACEID（18桁）の例：202609303601130210 → 先頭8桁が日付、末尾2桁がレース番号
（00 は開催場のレース一覧）。
第1段階（discover）：対象日の各場のレース一覧→各レースの出馬表・単複オッズ・
競走成績・払戻を生HTMLで保存する。
"""
from __future__ import annotations

import argparse
import re
from datetime import date as Date

from common import PoliteSession, save_json, save_raw

BASE = "https://keiba.rakuten.co.jp"
RACEID_RE = re.compile(r"/race_card/list/RACEID/(\d{18})")
PAGES = {
    "card": "/race_card/list/RACEID/{rid}",
    "odds": "/odds/tanfuku/RACEID/{rid}",
    "performance": "/race_performance/list/RACEID/{rid}",
    "dividend": "/race_dividend/list/RACEID/{rid}",
}


def venue_lists(sess: PoliteSession, target: str) -> list[str]:
    """対象日の開催場ごとのレース一覧RACEID（末尾00）を集める。"""
    ids: set[str] = set()
    # トップ（本日分）→ 日付指定の一覧、の順に試す
    for name, url in (("top", f"{BASE}/"), ("index", f"{BASE}/race_card/list/RACEID/{target}0000000000")):
        try:
            html = sess.get(url).text
        except Exception:  # noqa: BLE001
            continue
        save_raw("rakuten_index", target, name, html)
        ids |= {m for m in RACEID_RE.findall(html) if m.startswith(target)}
        if ids:
            break
    return sorted({i[:16] + "00" for i in ids})


def race_ids(sess: PoliteSession, target: str, venue_rid: str) -> list[str]:
    html = sess.get(BASE + PAGES["card"].format(rid=venue_rid)).text
    save_raw("rakuten_venue", target, venue_rid, html)
    return sorted({m for m in RACEID_RE.findall(html) if m[:16] == venue_rid[:16] and not m.endswith("00")})


def _started(target: str, rid: str) -> bool:
    """前日に保存した出馬表の発走時刻を見て、発走10分前を過ぎていれば True。"""
    import json
    from datetime import datetime, timedelta, timezone

    from common import DATA_DIR

    f = DATA_DIR / "races" / target / f"{rid}.json"
    if not f.exists():
        return False
    pt = json.loads(f.read_text(encoding="utf-8")).get("post_time") or ""
    if not re.fullmatch(r"\d{1,2}:\d{2}", pt):
        return False
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    h, m = map(int, pt.split(":"))
    post = datetime.strptime(target, "%Y%m%d").replace(hour=h, minute=m, tzinfo=jst)
    return now > post - timedelta(minutes=10)


def discover(target: str, kinds: list[str], limit_races: int | None = None, after_now: bool = False) -> dict:
    sess = PoliteSession(min_interval=60.0)
    log = {"date": target, "venues": [], "pages": []}
    for v in venue_lists(sess, target):
        rids = race_ids(sess, target, v)
        log["venues"].append({"venue_rid": v, "races": rids})
        for rid in rids[:limit_races]:
            if after_now and _started(target, rid):
                continue
            for kind in kinds:
                url = BASE + PAGES[kind].format(rid=rid)
                try:
                    html = sess.get(url).text
                    save_raw(f"rakuten_{kind}", target, rid, html)
                    log["pages"].append({"kind": kind, "rid": rid})
                except Exception as e:  # noqa: BLE001
                    log["pages"].append({"kind": kind, "rid": rid, "error": str(e)})
    save_json(f"raw/{target}/rakuten_discover_log.json", log)
    return log


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=Date.today().strftime("%Y%m%d"))
    ap.add_argument("--kinds", default="card")
    ap.add_argument("--limit-races", type=int, default=None, help="各場の先頭Nレースだけ（試運転用）")
    ap.add_argument("--after-now", action="store_true", help="まだ発走していないレースだけ取る（当日昼用）")
    a = ap.parse_args()
    lg = discover(a.date, a.kinds.split(","), a.limit_races, a.after_now)
    print(f"rakuten {a.date}: venues {len(lg['venues'])}, pages {len(lg['pages'])}")
