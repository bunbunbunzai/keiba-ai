"""JRA：出馬表＋近走（馬ごとのページ）＋過去レースの結果（通過順・上がり）を取得してJSON化。

流れ
1. 入口（出馬表メニュー）から、対象日の「全てのレースを表示」ページ（pw01des…<日付>）を開く
2. 各レースの出走馬と、馬ページのリンク（/JRADB/accessU.html?CNAME=pw01dud…）を取る
3. 馬ページから過去の出走レース一覧を取る（年月日・場・レース名・距離・馬場・頭数・人気・着順・騎手・斤量・体重・タイム）
4. 過去レースの結果ページ（accessS.html?CNAME=pw01sde…）から、通過順・上がり・着差を補う
   結果ページは内容が変わらないので data/cache/jra_result/ に保存して再利用する

使い方: python scraper/jra_cards.py --date 20261101 [--max-horses 999] [--past 5]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from bs4 import BeautifulSoup

from common import DATA_DIR, PoliteSession, save_json, save_raw
from jra import BASE, ENTRY, actions, open_action

CNAME_RE = re.compile(r"CNAME=([^\"'&\s]+)")


def text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def num(s, cast=float):
    m = re.search(r"-?\d+(?:\.\d+)?", (s or "").replace(",", ""))
    return cast(m.group()) if m else None


# ---------- 1. 全レースページ ----------
def find_all_race_pages(sess: PoliteSession, target: str) -> list[tuple[str, str]]:
    path, cname = ENTRY["card"]
    html = open_action(sess, path, cname)
    out, seen = [], set()
    frontier = [(p, c) for p, c, _ in actions(html)]
    for p, c in frontier:  # 2階層まで：開催一覧→開催ごとのレース一覧→全レース
        if c in seen:
            continue
        seen.add(c)
        if c.startswith("pw01des") and c.split("/")[0].endswith(target):
            out.append((p, c))
        elif c.startswith("pw01drl") and target in c:
            for p2, c2, _ in actions(open_action(sess, p, c)):
                if c2.startswith("pw01des") and c2.split("/")[0].endswith(target) and c2 not in seen:
                    seen.add(c2)
                    out.append((p2, c2))
    return out


def parse_all_races(html: str) -> list[dict]:
    s = BeautifulSoup(html, "html.parser")
    races = []
    for li in s.select("ul.syutsuba_unit_list > li[id^=syutsuba_]"):
        rno = num(li["id"], int)
        head = text(li.find(class_=re.compile("race_header|header")) or li)[:400]
        r = {"race_no": rno, "header_text": head}
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日.*?(\d+回\S+?\d+日)", head)
        if m:
            r["date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            r["meeting"] = m.group(4)
            r["venue"] = re.sub(r"^\d+回|\d+日$", "", m.group(4))
        m = re.search(r"発走時刻：?\s*(\d+)時(\d+)分", head)
        if m:
            r["post_time"] = f"{int(m.group(1)):02d}:{m.group(2)}"
        m = re.search(r"\d+時\d+分\s+(.*?)\s+コース", head)
        if m:
            r["title_text"] = m.group(1)
        m = re.search(r"コース：?\s*([\d,]+)\s*メートル\s*（(芝|ダート|障害)[^）]*）", head)
        if m:
            r["distance"] = int(m.group(1).replace(",", ""))
            r["surface"] = {"芝": "芝", "ダート": "ダ", "障害": "障"}[m.group(2)]
            r["course_text"] = m.group(0)
        horses = []
        for tr in li.select("table tbody tr"):
            a = tr.select_one("td.horse a")
            if not a:
                continue
            img = tr.select_one("td.waku img")
            hw = tr.select_one("td.h_weight")
            horses.append({
                "frame": num(img.get("alt") if img else None, int),
                "number": num(text(tr.select_one("td.num")), int),
                "name": text(a),
                "horse_url": a["href"],
                "body_weight": num(hw.contents[0] if hw and hw.contents else None, int),
                "body_weight_change": text(hw.select_one(".change")) if hw else None,
                "sex_age": text(tr.select_one("td.age")),
                "weight": num(text(tr.select_one("td.weight"))),
                "jockey": text(tr.select_one("td.jockey")),
                "trainer": text(tr.select_one("td.trainer")),
                "odds": num(text(tr.select_one("td.odds"))),
            })
        r["horses"] = horses
        r["field"] = len(horses)
        races.append(r)
    return races


# ---------- 2. 表の汎用読み取り（見出し名で列を引く） ----------
def table_by_headers(soup, must: list[str]):
    for t in soup.find_all("table"):
        ths = [text(th) for th in t.find_all("th")]
        if all(any(m in h for h in ths) for m in must):
            return t
    return None


def rows_as_dicts(t) -> list[dict]:
    head = t.find("thead")
    cols = [text(th).replace(" ", "") for th in (head or t).find_all("tr")[0].find_all(["th", "td"])]
    out = []
    for tr in (t.find("tbody") or t).find_all("tr"):
        tds = tr.find_all(["td", "th"])
        if len(tds) != len(cols) or tds[0].name == "th" and not text(tds[0])[:1].isdigit():
            continue
        d = {}
        for c, td in zip(cols, tds):
            d[c] = text(td)
            a = td.find("a", href=True)
            if a and "CNAME=" in a["href"]:
                d[c + "#link"] = a["href"]
        out.append(d)
    return out


# ---------- 3. 馬ページ ----------
def parse_horse(html: str) -> dict:
    s = BeautifulSoup(html, "html.parser")
    prof = {}
    for dt in s.find_all(["dt", "th"]):
        k = text(dt)
        if k in ("父", "母", "母の父", "生年月日", "調教師名", "馬主名", "生産牧場", "性別", "馬齢"):
            dd = dt.find_next_sibling(["dd", "td"])
            if dd:
                prof[k] = text(dd)
    runs = []
    t = table_by_headers(s, ["年月日", "レース名", "着順"])
    for d in rows_as_dicts(t) if t else []:
        dist = d.get("距離", "")
        m = re.match(r"(芝|ダ|障)\D*(\d+)", dist)
        runs.append({
            "date": d.get("年月日"),
            "venue": d.get("場"),
            "race_name": d.get("レース名"),
            "surface": m.group(1) if m else None,
            "distance": int(m.group(2)) if m else None,
            "track": d.get("馬場"),
            "field": num(d.get("頭数"), int),
            "popularity": num(d.get("人気"), int),
            "finish": d.get("着順"),
            "jockey": d.get("騎手名"),
            "weight": num(d.get("負担重量")),
            "body_weight": num(d.get("馬体重"), int),
            "time": d.get("タイム"),
            "opponent": d.get("1着馬（2着馬）") or d.get("1着馬(2着馬)"),
            "result_url": d.get("レース名#link"),
        })
    return {"profile": prof, "runs": runs}


# ---------- 4. 結果ページ ----------
def parse_result(html: str) -> dict:
    s = BeautifulSoup(html, "html.parser")
    t = table_by_headers(s, ["着順", "馬名", "タイム"])
    rows = []
    for d in rows_as_dicts(t) if t else []:
        rows.append({
            "finish": d.get("着順"),
            "number": num(d.get("馬番"), int),
            "name": re.sub(r"（.*?）|\(.*?\)", "", d.get("馬名", "")).strip(),
            "time": d.get("タイム"),
            "margin": d.get("着差"),
            "corners": "-".join(re.findall(r"\d+", d.get("コーナー通過順位", ""))),
            "last3f": num(d.get("推定上り")),
            "popularity": num(d.get("単勝人気"), int),
        })
    pay = {}
    for dl in s.find_all("dl"):
        dt = dl.find("dt")
        kind = text(dt)
        if kind not in ("単勝", "複勝", "枠連", "ワイド", "馬連", "馬単", "3連複", "3連単"):
            continue
        items = []
        for line in dl.select("div.line"):
            c, y = line.select_one("div.num"), line.select_one("div.yen")
            if c and y and num(text(y), int):
                items.append({"combo": text(c), "yen": num(text(y), int), "pop": num(text(line.select_one("div.pop")), int)})
        if items:
            pay[kind] = items
    return {"rows": rows, "payouts": pay}


def cached_result(sess: PoliteSession, url: str) -> str | None:
    cm = CNAME_RE.search(url)
    if not cm:
        return None
    key = re.sub(r"[^0-9A-Za-z]", "_", cm.group(1))
    p = DATA_DIR / "cache" / "jra_result" / f"{key}.html"
    if p.exists():
        return p.read_text(encoding="utf-8")
    html = sess.get(BASE + url if url.startswith("/") else url).text
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")
    return html


def run(target: str, past: int = 5, max_horses: int = 10_000) -> int:
    sess = PoliteSession(min_interval=3.0, encoding="shift_jis")
    pages = find_all_race_pages(sess, target)
    n_horse = 0
    written = 0
    for path, cname in pages:
        html = open_action(sess, path, cname)
        save_raw("jra_allraces", target, re.sub(r"[^0-9A-Za-z]", "_", cname), html)
        for race in parse_all_races(html):
            for h in race["horses"]:
                if n_horse >= max_horses:
                    break
                n_horse += 1
                try:
                    hh = sess.get(BASE + h["horse_url"]).text
                except Exception as e:  # noqa: BLE001
                    h["error"] = str(e)
                    continue
                if n_horse <= 3:
                    save_raw("jra_horse_sample", target, f"h{n_horse}", hh)
                info = parse_horse(hh)
                h["profile"] = info["profile"]
                h["past"] = []
                for r in info["runs"][:past]:
                    if r.get("result_url"):
                        try:
                            rh = cached_result(sess, r["result_url"])
                            res = parse_result(rh) if rh else None
                            me = next((x for x in (res or {}).get("rows", []) if x["name"] == h["name"]), None)
                            if me:
                                r.update(corners=me["corners"], last3f=me["last3f"], margin=me["margin"], number=me["number"])
                        except Exception as e:  # noqa: BLE001
                            r["result_error"] = str(e)
                    h["past"].append(r)
            rid = f"jra_{target}_{race.get('venue', 'X')}_{race['race_no']:02d}"
            race.update(race_id=rid, source="jra")
            save_json(f"races/{target}/{rid}.json", race)
            written += 1
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--past", type=int, default=5)
    ap.add_argument("--max-horses", type=int, default=10_000)
    a = ap.parse_args()
    print("JRA races written:", run(a.date, a.past, a.max_horses))
