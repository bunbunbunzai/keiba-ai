"""JRAの重賞（G1〜G3・J重賞）の過去の成績と今年の日程を集める（重賞データ記事の元）。

  JRA公式「重賞競走一覧」 https://www.jra.go.jp/datafile/seiseki/replay/<年>/jyusyo.html
  を年ごとに読み、各レースの成績ページ（全着順・払戻）をたどる。robots.txt は全許可。5秒に1ページ。

保存先：data/graded_hist/<年>.json
  {"year": 2025, "complete": true, "races": [{date, abbr, grade, venue, cond, course, surface, distance, url,
    title, name, slug, track, rows: [{fin, frame, num, name, sex, age, kg, jockey, time, margin, corners, last3f, pop, trainer}], pay: {...}}]}
  今年の分は、まだ行われていないレースも日程として入る（rows なし）。過去の年は全レースを取れたら complete にして、以後は読まない。

  python graded_hist.py --years 11 --max-minutes 120
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from common import DATA_DIR, PoliteSession

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "site"))
import extra  # noqa: E402

JST = timezone(timedelta(hours=9))
OUT = DATA_DIR / "graded_hist"
BASE = "https://www.jra.go.jp"
LIST = BASE + "/datafile/seiseki/replay/{y}/jyusyo.html"
VENUES = ("札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉")
VSLUG = {"東京": "tokyo", "中山": "nakayama", "京都": "kyoto", "阪神": "hanshin", "中京": "chukyo", "福島": "fukushima", "新潟": "niigata",
         "小倉": "kokura", "札幌": "sapporo", "函館": "hakodate"}
ROMAN = {"Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3", "I": "1", "II": "2", "III": "3"}


def nf(s) -> str:
    return unicodedata.normalize("NFKC", s or "")


def tx(el) -> str:
    return re.sub(r"\s+", " ", nf(el.get_text(" ", strip=True))) if el is not None else ""


def to_int(s):
    m = re.search(r"\d+", nf(str(s or "")).replace(",", ""))
    return int(m.group()) if m else None


def grade_from(cell) -> str:
    """レース名のセルから格を読む（文字または画像の alt）。"""
    s = tx(cell) + " " + " ".join(nf(i.get("alt", "")) for i in cell.find_all("img"))
    m = re.search(r"(J\s*[・･.]?\s*)?G\s*(III|II|I|[123])", s.replace("Ⅲ", "III").replace("Ⅱ", "II").replace("Ⅰ", "I"))
    if not m:
        return ""
    return ("J・" if m.group(1) else "") + "G" + ROMAN.get(m.group(2), m.group(2))


def parse_list(html: str, year: int) -> list[dict]:
    s = BeautifulSoup(html, "html.parser")
    out = []
    for t in s.find_all("table"):
        heads = [tx(th).replace(" ", "") for th in t.find_all("th")]
        if not any("レース名" in h for h in heads) or not any("競馬場" in h for h in heads):
            continue
        first = (t.find("thead") or t).find("tr")
        cols = [tx(c).replace(" ", "") for c in first.find_all(["th", "td"])]
        idx = {k: next((i for i, c in enumerate(cols) if k in c), None) for k in ("月日", "レース名", "競馬場", "性齢", "コース", "結果")}
        if idx["月日"] is None or idx["レース名"] is None:
            continue
        for tr in (t.find("tbody") or t).find_all("tr"):
            tds = tr.find_all(["td", "th"])
            if len(tds) < len(cols):
                continue
            m = re.search(r"(\d+)月\s*(\d+)日", tx(tds[idx["月日"]]))
            if not m:
                continue
            cell = tds[idx["レース名"]]
            a = cell.find("a")
            abbr = re.sub(r"\s*\(?(?:J\s*[・･.]?\s*)?G\s*(?:[ⅠⅡⅢ]|I{1,3}|[123])\)?\s*$", "", tx(a) if a and tx(a) else tx(cell)).strip()
            abbr = re.sub(r"\s+", "", abbr)
            course = tx(tds[idx["コース"]]) if idx["コース"] is not None else ""
            cm = re.search(r"(芝|ダ|障)\D*([\d,]+)", course)
            url = None
            if idx["結果"] is not None:
                ra = tds[idx["結果"]].find("a", href=True)
                if ra:
                    url = ra["href"] if ra["href"].startswith("http") else BASE + ra["href"]
            venue = tx(tds[idx["競馬場"]]) if idx["競馬場"] is not None else ""
            out.append({"date": f"{year}{int(m.group(1)):02d}{int(m.group(2)):02d}", "abbr": abbr, "grade": grade_from(cell),
                        "venue": next((v for v in VENUES if v in venue), venue), "cond": tx(tds[idx["性齢"]]) if idx["性齢"] is not None else "",
                        "course": course, "surface": cm.group(1) if cm else "", "distance": to_int(cm.group(2)) if cm else None, "url": url})
    return out


def parse_result(html: str) -> dict:
    s = BeautifulSoup(html, "html.parser")
    title = ""
    for el in s.find_all(["h1", "h2", "h3", "span", "div", "p"]):
        t = tx(el)
        if re.match(r"^第\s*\d+\s*回\s*\S", t) and len(t) < 60:
            title = t
            break
    if not title:
        m = re.search(r"第\s*\d+\s*回\s*[^\s|｜<]{2,30}", nf(s.title.get_text()) if s.title else "")
        title = m.group() if m else ""
    table = None
    for t in s.find_all("table"):
        heads = [tx(th).replace(" ", "") for th in t.find_all("th")]
        if any("着順" in h for h in heads) and any("馬名" in h for h in heads):
            table = t
            break
    rows = []
    if table is not None:
        first = (table.find("thead") or table).find("tr")
        cols = [tx(c).replace(" ", "") for c in first.find_all(["th", "td"])]

        def col(*keys):
            return next((i for i, c in enumerate(cols) if any(k in c for k in keys)), None)
        ix = {"fin": col("着順"), "frame": col("枠"), "num": col("馬番"), "name": col("馬名"), "sa": col("性齢"), "kg": col("負担重量", "斤量"),
              "jockey": col("騎手"), "time": col("タイム"), "margin": col("着差"), "corners": col("コーナー", "通過"), "last3f": col("上り", "上がり"),
              "pop": col("人気"), "trainer": col("調教師")}
        for tr in (table.find("tbody") or table).find_all("tr"):
            tds = tr.find_all(["td", "th"])
            if len(tds) != len(cols):
                continue

            def g(k):
                return tx(tds[ix[k]]) if ix[k] is not None else ""
            name = re.sub(r"[（(].*?[）)]", "", g("name")).strip()
            if not name or name == "馬名":
                continue
            frame = None
            if ix["frame"] is not None:
                c = tds[ix["frame"]]
                frame = to_int(tx(c)) or next((to_int(i.get("alt", "")) for i in c.find_all("img") if to_int(i.get("alt", ""))), None)
            sm = re.match(r"(牡|牝|せん|セ|騸)\s*(\d+)", g("sa"))
            fin = g("fin")
            rows.append({"fin": to_int(fin) if re.match(r"^\d+", fin) else fin, "frame": frame, "num": to_int(g("num")), "name": name,
                         "sex": ("せん" if sm.group(1) in ("セ", "騸") else sm.group(1)) if sm else "", "age": int(sm.group(2)) if sm else None,
                         "kg": g("kg"), "jockey": re.sub(r"[▲△☆★◇]", "", g("jockey")).replace(" ", ""), "time": g("time"), "margin": g("margin"),
                         "corners": "-".join(re.findall(r"\d+", g("corners"))), "last3f": g("last3f"), "pop": to_int(g("pop")),
                         "trainer": g("trainer").replace(" ", "")})
    pay = {}
    for dl in s.find_all("dl"):
        kind = tx(dl.find("dt"))
        if kind not in ("単勝", "複勝", "枠連", "ワイド", "馬連", "馬単", "3連複", "3連単"):
            continue
        items = []
        for line in dl.select("div.line"):
            c, y = line.select_one("div.num"), line.select_one("div.yen")
            if c is not None and y is not None and to_int(tx(y)):
                items.append([tx(c).replace(" ", ""), to_int(tx(y)), to_int(tx(line.select_one("div.pop")))])
        if items:
            pay[kind] = items
    if not pay:  # 表組みの払戻（古い年の形）
        for th in s.find_all(["th", "dt"]):
            kind = tx(th).replace(" ", "")
            if kind not in ("単勝", "複勝", "枠連", "ワイド", "馬連", "馬単", "3連複", "3連単") or kind in pay:
                continue
            tr = th.find_parent("tr")
            if tr is None:
                continue
            cells = [tx(td) for td in tr.find_all("td")]
            body = " ".join(cells)
            items = [[m.group(1).replace(" ", ""), int(m.group(2).replace(",", "")), None]
                     for m in re.finditer(r"(\d+(?:\s*-\s*\d+){0,2})\s+([\d,]+)\s*円", body)]
            if items:
                pay[kind] = items
    text = tx(s.body) if s.body else ""
    tm = re.search(r"(芝|ダート)\s*[:：]?\s*(不良|稍重|良|重)", text)
    wm = re.search(r"天候\s*[:：]?\s*(晴|曇|小雨|雨|小雪|雪)", text)
    return {"title": title, "rows": rows, "pay": pay, "track": tm.group(2) if tm else "", "weather": wm.group(1) if wm else ""}


def slug_for(title: str, abbr: str, venue: str) -> tuple[str, str]:
    name = extra.clean_name(title) if title else abbr
    slug = extra.graded_slug(name, VSLUG.get(venue, "venue"))
    return name, slug


def load_year(y: int) -> dict:
    f = OUT / f"{y}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"year": y, "complete": False, "races": []}


def save_year(d: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{d['year']}.json").write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=11, help="今年を含めてさかのぼる年数")
    ap.add_argument("--max-minutes", type=float, default=120)
    ap.add_argument("--sample", action="store_true", help="成績ページを2つだけ読んで、生のHTMLも data/raw/graded_hist に残す（形の確認用）")
    a = ap.parse_args()
    deadline = time.monotonic() + a.max_minutes * 60
    now = datetime.now(JST)
    sess = PoliteSession(min_interval=5.0, encoding="shift_jis")
    fetched = 0
    for y in range(now.year, now.year - a.years, -1):
        if time.monotonic() > deadline:
            break
        cur = load_year(y)
        if cur.get("complete") and y < now.year:
            continue
        try:
            html = sess.get(LIST.format(y=y)).text
        except Exception as e:  # noqa: BLE001
            print("list error", y, e, flush=True)
            continue
        listed = parse_list(html, y)
        if a.sample:
            raw = DATA_DIR / "raw" / "graded_hist"
            raw.mkdir(parents=True, exist_ok=True)
            (raw / f"list_{y}.html").write_text(html, encoding="utf-8")
        if not listed:
            print("list empty", y, flush=True)
            continue
        old = {(r["date"], r["abbr"]): r for r in cur.get("races", [])}
        races = []
        for r in listed:
            o = old.get((r["date"], r["abbr"]))
            if o and o.get("rows") and o.get("pay"):
                races.append({**o, **{k: r[k] for k in ("grade", "venue", "cond", "course", "surface", "distance") if r.get(k)}})
                continue
            if r["url"] and time.monotonic() < deadline and not (a.sample and fetched >= 2):
                try:
                    rh = sess.get(r["url"]).text
                    p = parse_result(rh)
                    fetched += 1
                    if a.sample:
                        (DATA_DIR / "raw" / "graded_hist" / f"result_{r['date']}_{fetched}.html").write_text(rh, encoding="utf-8")
                    r.update(p)
                    if not p["rows"] or not p["pay"]:
                        print("parse incomplete", y, r["abbr"], len(p["rows"]), list(p["pay"]), r["url"], flush=True)
                except Exception as e:  # noqa: BLE001
                    print("result error", r["abbr"], e, flush=True)
            r["name"], r["slug"] = slug_for(r.get("title", ""), r["abbr"], r["venue"])
            races.append(r)
        done = all(r.get("rows") and r.get("pay") for r in races if r.get("url"))
        cur = {"year": y, "updated": now.strftime("%Y-%m-%d %H:%M"), "races": races,
               "complete": bool(y < now.year and done and all(r.get("url") for r in races))}
        save_year(cur)
        print(y, "races", len(races), "with rows", sum(1 for r in races if r.get("rows")), "complete", cur["complete"], flush=True)
        if a.sample and fetched >= 2:
            break
    print("fetched result pages:", fetched, flush=True)


if __name__ == "__main__":
    main()
