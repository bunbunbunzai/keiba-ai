"""過去のレース結果をさかのぼって集める（全頭くんの「世の中のデータ」用の土台）。

集めるのは公式に公開されている結果だけ（着順・馬番・4角位置・人気・払戻・コース）。
AIの予想はここには無い（印の成績はサイトの予想記録から別に数える）。

  JRA ：jra.go.jp の「過去レース結果検索」を月→開催日→レースの順にたどる。robots.txt は全許可。5秒に1ページ。
  地方：楽天競馬の競走成績ページ（着順と払戻が1ページに載る）。robots.txt の Crawl-delay: 60 を守る。
        地方競馬情報サイト（keiba.go.jp）は結果ページへの bot アクセスを robots.txt で禁止しているので使わない。

保存先：data/history/<jra|local>/<YYYY>/<YYYYMMDD>.jsonl（1行1レース）。日単位で、全レースを取れたら書く。
新しい日から順にさかのぼり、--max-minutes の時間で止まる（次回は続きから）。

  python history.py --src jra --since 2023-11 --max-minutes 300
  python history.py --src local --since 2025-11 --max-minutes 520
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date as Date, datetime, timedelta, timezone

from bs4 import BeautifulSoup

from common import DATA_DIR, PoliteSession

JST = timezone(timedelta(hours=9))
HIST = DATA_DIR / "history"
JRA_VENUES = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京", "06": "中山",
              "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}
SURF = {"ダート": "ダ", "ダ": "ダ", "芝": "芝", "障害": "障"}


def day_file(src: str, d: str):
    return HIST / src / d[:4] / f"{d}.jsonl"


def write_day(src: str, d: str, recs: list[dict]) -> None:
    f = day_file(src, d)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in recs), encoding="utf-8")


def compact_pay(pay: dict) -> dict:
    return {k: [[x["combo"], x["yen"]] for x in v] for k, v in (pay or {}).items() if not k.startswith("_") and v}


# ---------------- JRA ----------------
def jra_months(sess: PoliteSession, months: list[str], deadline: float, until: str) -> int:
    from jra import BASE, actions, open_action
    from jra_cards import parse_result

    top = open_action(sess, "/JRADB/accessS.html", "pw01skl00999999/B3")
    table = dict(re.findall(r'objParam\["(\d{4})"\]="([0-9A-F]{2})"', top))
    n = 0
    for ym in months:
        if time.monotonic() > deadline:
            break
        chk = table.get(ym[2:6])
        if not chk:
            print("no checksum for", ym, flush=True)
            continue
        mhtml = open_action(sess, "/JRADB/accessS.html", f"pw01skl10{ym}/{chk}")
        days: dict[str, list[str]] = {}
        for _, c, _ in actions(mhtml):
            m = re.match(r"pw01srl\d{2}\d{2}\d{4}\d{2}\d{2}(\d{8})/", c)
            if m and m.group(1).startswith(ym):
                days.setdefault(m.group(1), []).append(c)
        for d in sorted(days, reverse=True):
            if d >= until or day_file("jra", d).exists():
                continue
            if time.monotonic() > deadline:
                return n
            recs = []
            for c in sorted(set(days[d])):
                dhtml = open_action(sess, "/JRADB/accessS.html", c)
                links = sorted({x for x in re.findall(r"pw01sde[0-9A-Za-z/]+", dhtml)})
                for cn in links:
                    m = re.match(r"pw01sde\d{2}(\d{2})\d{4}\d{2}\d{2}(\d{2})", cn)
                    if not m:
                        continue
                    try:
                        html = sess.get(f"{BASE}/JRADB/accessS.html?CNAME={cn}").text
                    except Exception as e:  # noqa: BLE001
                        print("skip", cn, e, flush=True)
                        continue
                    res = parse_result(html)
                    cm = re.search(r"コース\s*[：:]\s*([\d,]+)\s*メートル\s*[（(]\s*(芝|ダート|障害)", re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" ")))
                    rows = [[r.get("finish"), r.get("number"), None, _pos4(r.get("corners")), r.get("popularity")]
                            for r in res.get("rows", [])]
                    if not rows:
                        continue
                    recs.append({"d": d, "v": JRA_VENUES.get(m.group(1), m.group(1)), "r": int(m.group(2)),
                                 "s": SURF.get(cm.group(2)) if cm else None,
                                 "m": int(cm.group(1).replace(",", "")) if cm else None,
                                 "n": len(rows), "rows": rows, "pay": compact_pay(res.get("payouts"))})
            write_day("jra", d, recs)
            n += 1
            print(f"jra {d}: {len(recs)} races", flush=True)
    return n


def _pos4(corners) -> int | None:
    if not corners:
        return None
    try:
        return int(str(corners).split("-")[-1].split()[-1])
    except ValueError:
        return None


# ---------------- 地方（楽天競馬） ----------------
def local_days(sess: PoliteSession, days: list[str], deadline: float, night_only: bool = True) -> int:
    from rakuten import BASE, PAGES, RACEID_RE
    from results import parse_rakuten_payouts, parse_rakuten_performance

    def venue_lists(_s, d):
        html = _s.get(f"{BASE}/race_card/list/RACEID/{d}0000000000").text
        return sorted({i[:16] + "00" for i in RACEID_RE.findall(html) if i.startswith(d) and i[8:10] != "00"})

    def race_ids(_s, d, v):
        html = _s.get(BASE + PAGES["card"].format(rid=v)).text
        return sorted({i for i in RACEID_RE.findall(html) if i[:16] == v[:16] and not i.endswith("00")})

    n = 0
    for d in days:
        if day_file("local", d).exists():
            continue
        # 1日分（数場×十数レース、1ページ60秒）が時間内に終わる見込みが無ければ止める
        if time.monotonic() + 90 * 60 > deadline:
            break
        # 楽天競馬への取得は、日々の取得と重ならない深夜〜朝（JST 0:00〜9:00）だけ
        if night_only and not (0 <= datetime.now(JST).hour < 8):
            print("夜間の時間帯を過ぎたので止める", flush=True)
            break
        recs = []
        try:
            venues = venue_lists(sess, d)
        except Exception as e:  # noqa: BLE001
            print("venue list failed", d, e, flush=True)
            continue
        ok = True
        for v in venues:
            try:
                ids = race_ids(sess, d, v)
            except Exception as e:  # noqa: BLE001
                print("race list failed", d, v, e, flush=True)
                ok = False
                continue
            for rid in ids:
                try:
                    html = sess.get(BASE + PAGES["performance"].format(rid=rid)).text
                except Exception as e:  # noqa: BLE001
                    print("skip", rid, e, flush=True)
                    continue
                rows = parse_rakuten_performance(html)
                if not rows:
                    continue
                t = BeautifulSoup(html, "html.parser")
                title = t.title.get_text() if t.title else ""
                vm = re.match(r"\s*(\S+?)競馬場", title)
                cm = re.search(r"(ダ|芝)([\d,]+)m", t.get_text(" "))
                recs.append({"d": d, "v": vm.group(1) if vm else rid[10:12], "r": int(rid[-2:]),
                             "s": cm.group(1) if cm else None, "m": int(cm.group(2).replace(",", "")) if cm else None,
                             "n": len(rows),
                             "rows": [[r.get("finish"), r.get("number"), r.get("frame"), r.get("pos4"), r.get("popularity")] for r in rows],
                             "pay": compact_pay(parse_rakuten_payouts(html))})
        if ok:
            write_day("local", d, recs)
            n += 1
            print(f"local {d}: {len(recs)} races", flush=True)
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", choices=["jra", "local"], required=True)
    ap.add_argument("--since", required=True, help="さかのぼる最も古い年月 YYYY-MM")
    ap.add_argument("--until", default="", help="この日より前だけ（YYYYMMDD。既定はサイトの予想開始日 20261026）")
    ap.add_argument("--max-minutes", type=float, default=300)
    ap.add_argument("--any-time", action="store_true", help="地方：夜間以外でも取得する（手動の試験用）")
    a = ap.parse_args()
    deadline = time.monotonic() + a.max_minutes * 60
    until = a.until or "20261026"
    since = a.since.replace("-", "")
    if a.src == "jra":
        months, y, m = [], int(until[:4]), int(until[4:6])
        while f"{y:04d}{m:02d}" >= since:
            months.append(f"{y:04d}{m:02d}")
            y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        sess = PoliteSession(min_interval=5.0, encoding="shift_jis")
        n = jra_months(sess, months, deadline, until)
    else:
        end = datetime.strptime(until, "%Y%m%d").date() - timedelta(days=1)
        start = datetime.strptime(since + "01", "%Y%m%d").date()
        days, d = [], end
        while d >= start:
            days.append(d.strftime("%Y%m%d"))
            d -= timedelta(days=1)
        sess = PoliteSession(min_interval=60.0)
        n = local_days(sess, days, deadline, night_only=not a.any_time)
    print(f"{a.src}: wrote {n} days", flush=True)


if __name__ == "__main__":
    main()
