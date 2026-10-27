"""レース結果と払戻の取得 → data/results/<date>/<race_id>.json

JRA   ：レース結果メニュー → 対象日の開催ごとの一覧（pw01srl…<日付>）→ 各レース（pw01sde…）
楽天競馬：対象日の各レースの競走成績（race_performance）と払戻金（race_dividend）

使い方: python scraper/results.py --date 20261025 [--source jra|rakuten|both] [--limit-races N]
"""
from __future__ import annotations

import argparse
import json
import re

from bs4 import BeautifulSoup

from common import DATA_DIR, PoliteSession, save_json, save_raw
from jra import BASE as JRA_BASE, ENTRY, actions, open_action
from jra_cards import cached_result, num, parse_result, rows_as_dicts, table_by_headers, text

KINDS = ("単勝", "複勝", "枠連", "枠複", "ワイド", "馬連", "馬複", "馬単", "3連複", "三連複", "3連単", "三連単")
NORMAL = {"枠複": "枠連", "馬複": "馬連", "三連複": "3連複", "三連単": "3連単"}


# ---------------- JRA ----------------
def jra(target: str) -> int:
    sess = PoliteSession(min_interval=3.0, encoding="shift_jis")
    path, cname = ENTRY["result"]
    top = open_action(sess, path, cname)
    lists = [(p, c) for p, c, _ in actions(top) if c.startswith("pw01srl") and target in c]
    n = 0
    for p, c in lists:
        html = open_action(sess, p, c)
        s = BeautifulSoup(html, "html.parser")
        links = sorted({a["href"] for a in s.find_all("a", href=True) if "pw01sde" in a["href"] and target in a["href"]})
        for url in links:
            rh = cached_result(sess, url)
            res = parse_result(rh)
            m = re.search(r"pw01sde\d{2}(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})", url)
            venue_code, rno = (m.group(1), int(m.group(5))) if m else ("XX", 0)
            title = BeautifulSoup(rh, "html.parser").title
            res.update(source="jra", date=target, venue_code=venue_code, race_no=rno, url=url,
                       title=text(title))
            save_json(f"results/{target}/jra_{venue_code}_{rno:02d}.json", res)
            n += 1
    return n


# ---------------- 楽天競馬 ----------------
def parse_rakuten_payouts(html: str) -> dict:
    """競走成績ページ内の払戻金表（summary="払戻金"）を読む。th の直後の number/money セルが組。"""
    from jra_cards import lines_of

    s = BeautifulSoup(html, "html.parser")
    t = s.find("table", attrs={"summary": "払戻金"})
    pay: dict = {}
    if not t:
        return pay
    for th in t.find_all("th"):
        k = text(th).replace(" ", "")
        if k not in KINDS:
            continue
        nc = th.find_next_sibling("td", class_="number")
        mc = th.find_next_sibling("td", class_="money")
        if not (nc and mc):
            continue
        combos, yens = lines_of(nc), lines_of(mc)
        for c, y in zip(combos, yens):
            yy = num(y, int)
            if yy and re.fullmatch(r"\d+(-\d+)*", c):
                pay.setdefault(NORMAL.get(k, k), []).append({"combo": c, "yen": yy})
    refund = t.find(string=re.compile("返還"))
    if refund:
        pay["_refund"] = re.findall(r"(\d+)番", str(refund.parent.get_text()))
    return pay


def parse_rakuten_performance(html: str) -> list[dict]:
    s = BeautifulSoup(html, "html.parser")
    t = table_by_headers(s, ["着順", "馬名"])
    rows = []
    for d in rows_as_dicts(t) if t else []:
        rows.append({
            "finish": d.get("着順"),
            "number": num(d.get("馬番"), int),
            "name": d.get("馬名"),
            "time": d.get("タイム"),
            "margin": d.get("着差"),
            "corners": "-".join(re.findall(r"\d+", d.get("コーナー通過順", d.get("コーナー通過順位", "")))),
            "last3f": num(d.get("推定上がり") or d.get("上がり3F") or d.get("上がり")),
            "popularity": num(d.get("人気"), int),
            "raw": d,
        })
    return rows


def rakuten(target: str, limit_races: int | None = None) -> int:
    from rakuten import BASE, PAGES, race_ids, venue_lists

    sess = PoliteSession(min_interval=60.0)
    n = 0
    for v in venue_lists(sess, target):
        for rid in race_ids(sess, target, v)[:limit_races]:
            done = DATA_DIR / "results" / target / f"{rid}.json"
            if done.exists() and not json.loads(done.read_text(encoding="utf-8")).get("error"):
                continue  # 取得済みはとばす（再実行時は失敗分だけ取り直す）
            out = {"source": "rakuten", "date": target, "race_id": rid}
            try:
                ph = sess.get(BASE + PAGES["performance"].format(rid=rid)).text
                save_raw("rakuten_performance", target, rid, ph)
                out["payouts"] = parse_rakuten_payouts(ph)
                out["rows"] = parse_rakuten_performance(ph)
            except Exception as e:  # noqa: BLE001
                out["error"] = str(e)
            save_json(f"results/{target}/{rid}.json", out)
            n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--source", default="both")
    ap.add_argument("--limit-races", type=int, default=None)
    a = ap.parse_args()
    if a.source in ("jra", "both"):
        print("JRA results:", jra(a.date))
    if a.source in ("rakuten", "both"):
        print("rakuten results:", rakuten(a.date, a.limit_races))
