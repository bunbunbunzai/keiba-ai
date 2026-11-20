"""JRAの「特別レース登録馬」（その週の特別レースに登録した馬）から、馬名と馬ページのリンクを取る。AIは呼ばない。

G1の出走予定馬（data/entries。JRAのプレレーティングで、馬ページのリンクが無い）や重賞の登録馬について、
JRAの馬ページ（horse_info.py）を取るために使う。入口はJRAのメニューの「特別レース登録馬」。JRAのサイトは1ページごとに5秒あける。
保存：data/nominations/<登録馬の一覧ページのID>.json
  {fetched, cname, race, title, grade, date, horses: [{name, url, sex_age}]}（1ページ1レース）

  python jra_nominations.py            # 取って保存
  python jra_nominations.py --probe    # 生のHTMLも data/raw/<今日>/jra_nominations に残す（形の確認用）
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from common import DATA_DIR, PoliteSession, save_json, save_raw
from jra import actions, open_action

JST = timezone(timedelta(hours=9))
ENTRY = ("/JRADB/accessT.html", "pw03trl00/29")
HORSE = re.compile(r"pw01dud[0-9A-Za-z]+/[0-9A-Fa-f]{2}")
MAX_PAGES = 40


def nf(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def horse_links(html: str) -> list[dict]:
    """ページ内の馬ページへのリンク（GETのリンクとdoActionの両方）を、馬名つきで拾う。"""
    s = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in s.find_all("a"):
        blob = (a.get("href") or "") + " " + (a.get("onclick") or "")
        m = HORSE.search(blob)
        if not m:
            continue
        name = nf(a.get_text())
        if not name or len(name) > 12 or name in seen:
            continue
        seen.add(name)
        tr = a.find_parent("tr")
        sa = ""
        if tr:
            mm = re.search(r"(牡|牝|せん|セ)\s*(\d+)", tr.get_text(" "))
            sa = f"{mm.group(1)}{mm.group(2)}" if mm else ""
        out.append({"name": name, "url": f"/JRADB/accessU.html?CNAME={m.group(0)}", "sex_age": sa})
    return out


GRADE = {"GⅠ": "G1", "GⅡ": "G2", "GⅢ": "G3", "J・GⅠ": "J・G1", "J・GⅡ": "J・G2", "J・GⅢ": "J・G3", "L": "L"}


def race_info(html: str) -> dict:
    """登録馬のページの、レース名（「マイルチャンピオンシップ」）・条件つきの題名・格（G1など。無ければ空）。"""
    s = BeautifulSoup(html, "html.parser")
    one = lambda sel: " ".join((s.select_one(sel).get_text(" ") if s.select_one(sel) else "").split())
    img = s.select_one(".grade_icon img")
    g = (img.get("alt") or "").strip() if img else ""
    return {"race": one("span.race_name") or one(".race_name"), "title": one(".race_title")[:120], "grade": GRADE.get(g, g)}


def run(probe: bool) -> int:
    sess = PoliteSession(min_interval=5.0, encoding="shift_jis")
    today = datetime.now(JST).strftime("%Y%m%d")
    queue = [(ENTRY[0], ENTRY[1], 0)]
    seen: set[str] = set()
    saved = pages = 0
    while queue and pages < MAX_PAGES:
        path, cname, depth = queue.pop(0)
        if cname in seen:
            continue
        seen.add(cname)
        try:
            html = open_action(sess, path, cname)
        except Exception as e:  # noqa: BLE001
            print(f"{cname}: 開けず（{e}）")
            continue
        pages += 1
        key = re.sub(r"[^0-9A-Za-z]", "_", cname)
        if probe:
            save_raw("jra_nominations", today, key, html)
        hs = horse_links(html)
        if hs:
            d = re.search(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日", BeautifulSoup(html, "html.parser").get_text(" "))
            ri = race_info(html)
            save_json(f"nominations/{key}.json", {"fetched": datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "cname": cname, **ri,
                                                  "date": f"{d.group(1)}{int(d.group(2)):02d}{int(d.group(3)):02d}" if d else "",
                                                  "horses": hs})
            saved += 1
            print(f"{cname}: {ri['race']}（{ri['grade'] or '-'}） {len(hs)}頭")
            continue
        if depth >= 2:
            continue
        for p, c, label in actions(html):
            if c.startswith("pw03") and c not in seen:  # 特別レース登録馬の中だけをたどる
                queue.append((p, c, depth + 1))
    # 終わったレースの登録馬は1週間で消す（馬ページのリンクは horse_info に残る）
    old = (datetime.now(JST) - timedelta(days=7)).strftime("%Y%m%d")
    for f in (DATA_DIR / "nominations").glob("*.json"):
        m = re.search(r"(20\d{6})_[0-9A-Fa-f]{2}$", f.stem)
        if m and m.group(1) < old:
            f.unlink()
    print(f"ページ {pages}・保存 {saved}")
    return saved


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    run(a.probe)
