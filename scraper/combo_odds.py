"""3連複の発表オッズを取る（買い目をオッズで組むため。bets.py が使う）。

JRA：オッズのトップ → 開催ごとのオッズ一覧 → 各レースの3連複オッズ（馬番順）の1ページに全組み合わせが載っている。
     3秒間隔。対象は指定したレースだけ。
楽天競馬（地方）：3連複オッズのページの有無を確かめる段階（--probe）。robots.txt の Crawl-delay 60秒を守る。

保存先：data/odds/<日付>/<race_id>.json  {"fetched_at": "HH:MM", "fetched_ts": ISO, "source": "jra", "3連複": {"1-2-3": 35.9, ...}}

  python combo_odds.py --date 20261108 --race jra_20261108_東京_11
  python combo_odds.py --date 20261108 --all-a          # その日の自信度Aの中央のレースすべて
  python combo_odds.py --date 20261108 --probe-rakuten  # 楽天の3連複オッズページを試す（1レース分）
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from common import DATA_DIR, PoliteSession, save_json, save_raw

JST = timezone(timedelta(hours=9))
ROOT = DATA_DIR.parent
JRA_VENUE = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京", "06": "中山",
             "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}
RE_MEET = re.compile(r"^pw15orl\w{2}(\d{2})(\d{4})(\d{2})(\d{2})(\d{8})/")
RE_TRIO = re.compile(r"^pw157ou\w{2}(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})(\d{8})Z\w*/[0-9A-F]{2}$")


def parse_trio(html: str) -> dict[str, float]:
    """JRAの3連複オッズ（馬番順）ページ → {"a-b-c": オッズ}。取消などの数字でない欄は飛ばす。"""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, float] = {}
    for t in soup.select("table.fuku3"):
        cap = t.caption.get_text(strip=True) if t.caption else ""
        m = re.fullmatch(r"(\d+)-(\d+)", cap)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        for tr in t.select("tr"):
            th, td = tr.find("th"), tr.find("td")
            if not th or not td:
                continue
            try:
                c, o = int(th.get_text(strip=True)), float(td.get_text(strip=True).replace(",", ""))
            except ValueError:
                continue
            out["-".join(map(str, sorted((a, b, c))))] = o
    return out


def _save(date: str, rid: str, source: str, odds: dict[str, float]) -> None:
    now = datetime.now(JST)
    save_json(f"odds/{date}/{rid}.json", {"race_id": rid, "source": source, "fetched_at": now.strftime("%H:%M"),
                                          "fetched_ts": now.isoformat(timespec="seconds"), "3連複": odds})


def jra(date: str, race_ids: list[str] | None = None) -> list[str]:
    from jra import ENTRY, actions, open_action

    want = set(race_ids or [])
    sess = PoliteSession(min_interval=3.0, encoding="shift_jis")
    path, cname = ENTRY["odds"]
    idx = open_action(sess, path, cname)
    meets = [(p, c) for p, c, _ in actions(idx) if (m := RE_MEET.match(c)) and m.group(5) == date]
    got = []
    for p, c in meets:
        venue = JRA_VENUE.get(RE_MEET.match(c).group(1), "")
        if want and not any(r.startswith(f"jra_{date}_{venue}_") for r in want):
            continue
        html = open_action(sess, p, c)
        for p2, c2, _ in actions(html):
            m = RE_TRIO.match(c2)
            if not m or m.group(6) != date:
                continue
            rid = f"jra_{date}_{JRA_VENUE.get(m.group(1), m.group(1))}_{int(m.group(5)):02d}"
            if want and rid not in want:
                continue
            page = open_action(sess, p2, c2)
            odds = parse_trio(page)
            if odds:
                _save(date, rid, "jra", odds)
                got.append(rid)
                print("ok", rid, len(odds), "combos", flush=True)
            else:
                save_raw("jra_trio_unparsed", date, re.sub(r"[^0-9A-Za-z]", "_", c2), page)
                print("parse failed", rid, flush=True)
    return got


def probe_rakuten(date: str) -> None:
    """楽天競馬に3連複オッズのページがあるかを確かめる（結果は data/odds/rakuten_probe.json）。"""
    rids = sorted(f.stem for f in (DATA_DIR / "races" / date).glob("*.json") if not f.stem.startswith("jra_"))
    if not rids:
        print("楽天のレースが無い")
        return
    rid = rids[len(rids) // 2]
    sess = PoliteSession(min_interval=61.0)
    res = {"date": date, "race_id": rid, "tried": []}
    for path in (f"/odds/sanrenpuku/RACEID/{rid}", f"/odds/3renpuku/RACEID/{rid}", f"/odds/trio/RACEID/{rid}"):
        url = "https://keiba.rakuten.co.jp" + path
        try:
            r = sess.s.get(url, timeout=30)
            sess._last = __import__("time").monotonic()
            code, html = r.status_code, r.text
        except Exception as e:  # noqa: BLE001
            code, html = str(e)[:80], ""
        res["tried"].append({"url": url, "status": code, "len": len(html),
                             "title": (re.search(r"<title>(.*?)</title>", html, re.S) or [None, ""])[1].strip()[:80]})
        if html:
            save_raw("rakuten_trio_probe", date, path.split("/")[2], html)
        print(res["tried"][-1], flush=True)
        if code == 200 and "3連複" in html:
            break
        sess._wait()
    save_json("odds/rakuten_probe.json", res)


def a_races(date: str) -> list[str]:
    out = []
    for f in sorted((ROOT / "predictions" / date).glob("jra_*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        if p.get("confidence") == "A":
            out.append(p["race_id"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--race", action="append", default=[])
    ap.add_argument("--all-a", action="store_true")
    ap.add_argument("--probe-rakuten", action="store_true")
    a = ap.parse_args()
    if a.probe_rakuten:
        probe_rakuten(a.date)
        return
    ids = a.race or (a_races(a.date) if a.all_a else None)
    if a.all_a and not ids:
        print("自信度Aの中央のレースが無い")
        return
    got = jra(a.date, ids)
    print(f"combo_odds: {len(got)} races")


if __name__ == "__main__":
    main()
