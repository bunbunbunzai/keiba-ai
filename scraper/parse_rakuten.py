"""楽天競馬の出馬表HTMLを、分析用のJSONに変換する。

使い方: python scraper/parse_rakuten.py --date 20261026
  → data/raw/<date>/rakuten_card/*.html を読み、data/races/<date>/<RACEID>.json を書く
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

from common import DATA_DIR, save_json

VENUE_RE = re.compile(r"^(.+?)競馬場 出馬表 \| (\d{4}/\d{2}/\d{2}) (\d+)R")


def lines(el: Tag) -> list[str]:
    """<br>区切りで要素内のテキストを行に分ける（入れ子のspan等も含む）。"""
    out, cur = [], []
    for node in el.descendants:
        if isinstance(node, Tag) and node.name == "br":
            out.append(" ".join(cur).strip())
            cur = []
        elif isinstance(node, NavigableString):
            if node.parent.name in ("script", "style"):
                continue
            t = " ".join(str(node).split())
            if t:
                cur.append(t)
    if cur:
        out.append(" ".join(cur).strip())
    return [x for x in out if x]


def _num(s: str | None, cast=float):
    if s is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
    return cast(m.group()) if m else None


def parse_past(td: Tag) -> dict | None:
    """前5走の1マス。空欄（出走なし）は None。"""
    first = td.find("div", class_="firstInfo")
    if not first:
        return None
    pos = first.find("span", class_="place")
    state = first.find("span", class_="stateInfo")
    heads = first.find("span", class_="numberInfo")
    rn = td.find("span", class_="raceName")
    link = rn.find("a")["href"] if rn and rn.find("a") else ""
    first.extract()
    ls = lines(td)
    # 行の並び：場 日付 / レース名 / 格組 / 距離回りダ 人気 / 騎手 斤量 / タイム(差) / 上がり 体重 ゲート / 通過順 / 勝ち馬
    rec: dict = {
        "finish": pos.get_text(strip=True) if pos else None,  # 数字以外（取消・中止など）もあり得る
        "track": state.get_text(strip=True) if state else None,
        "field": _num(heads.get_text() if heads else None, int),
        "race_id": (re.search(r"RACEID/(\d+)", link) or [None, None])[1],
    }
    if ls:
        m = re.match(r"(\S+)\s+(\d{2}\.\d{2}\.\d{2})", ls[0])
        if m:
            rec["venue"], rec["date"] = m.group(1), "20" + m.group(2).replace(".", "-")
    for s in ls[1:]:
        if "race_name" not in rec and rn and s == " ".join(rn.get_text(" ", strip=True).split()):
            rec["race_name"] = s
            continue
        m = re.match(r"(\d{3,4})(右|左|直)?(芝|ダ|障)\s*(\d+)人", s)
        if m:
            rec.update(distance=int(m.group(1)), turn=m.group(2), surface=m.group(3), popularity=int(m.group(4)))
            continue
        m = re.match(r"(\d+:\d{2}\.\d|\d+\.\d)\s*\((-?\d+\.\d)\)", s)
        if m:
            rec.update(time=m.group(1), margin=float(m.group(2)))
            continue
        m = re.match(r"(\d+\.\d)\s+(\d+)k\s*(\d+)?番?", s)
        if m:
            rec.update(last3f=float(m.group(1)), body_weight=int(m.group(2)), gate=_num(m.group(3), int))
            continue
        if re.fullmatch(r"\d+(-\d+)*", s):
            rec["corners"] = s
            continue
        m = re.match(r"(\S+)\s+(\d+\.\d)$", s)
        if m and "jockey" not in rec:
            rec.update(jockey=m.group(1), weight=float(m.group(2)))
            continue
        if "corners" in rec or "last3f" in rec:
            rec.setdefault("opponent", s)  # 1着馬（自身が1着なら2着馬）
        else:
            rec.setdefault("class", s)
    return rec


def parse_card(html: str, race_id: str) -> dict:
    s = BeautifulSoup(html, "html.parser")
    title = s.title.get_text(strip=True) if s.title else ""
    m = VENUE_RE.match(title)
    race = {"race_id": race_id, "source": "rakuten", "title": title}
    if m:
        race.update(venue=m.group(1), date=m.group(2).replace("/", "-"), race_no=int(m.group(3)))
    note = s.find("div", class_="raceNote")
    if note:
        dist = note.find("li", class_="distance")
        if dist:
            dm = re.match(r"(芝|ダ|障)?([\d,]+)m", dist.get_text(strip=True))
            if dm:
                race.update(surface=dm.group(1), distance=int(dm.group(2).replace(",", "")))
        dd = note.find("dd")
        race["post_time"] = dd.get_text(strip=True) if dd else None
        h2 = note.find("h2")
        race["race_name"] = " ".join(h2.get_text(" ", strip=True).split()) if h2 else None
        cond = note.find("ul", class_="horseCondition")
        race["conditions"] = cond.get_text(" ", strip=True) if cond else None
    horses = []
    tb = s.find("table", class_="dataTable")
    for tr in tb.find_all("tr") if tb else []:
        num = tr.find("td", class_="number")
        name_td = tr.find("td", class_="name")
        if not (num and name_td):
            continue
        frame = tr.find("th", class_="position")
        main = name_td.find("span", class_="mainHorse")
        nl = lines(name_td)
        prof = lines(tr.find("td", class_="profile"))
        odds_txt = (name_td.find("span", class_="rate") or {}).get_text(strip=True) if name_td.find("span", class_="rate") else ""
        om = re.match(r"([\d.]+|-)（(\d+|-)人気）", odds_txt)
        h = {
            "frame": _num(frame.get_text() if frame else None, int),
            "number": _num(num.get_text(), int),
            "name": main.get_text(strip=True) if main else None,
            "horse_id": (re.search(r"HORSEID/(\d+)", main.find("a")["href"]) or [None, None])[1] if main and main.find("a") else None,
            "sire": nl[0] if nl else None,
            "dam": nl[2].split(" (")[0] if len(nl) > 2 else None,
            "damsire": (re.search(r"\((.+?)\)", name_td.get_text()) or [None, None])[1],
            "odds": _num(om.group(1)) if om and om.group(1) != "-" else None,
            "popularity": _num(om.group(2), int) if om and om.group(2) != "-" else None,
            "sex_age": prof[0] if prof else None,
            "weight": _num(prof[2]) if len(prof) > 2 else None,
            "jockey": prof[3] if len(prof) > 3 else None,
            "trainer": prof[-1] if prof else None,
            "body_weight_change": tr.find("td", class_="weightDistance").get_text(strip=True) if tr.find("td", class_="weightDistance") else None,
            "past": [p for p in (parse_past(td) for td in tr.find_all("td", class_="race")) if p],
        }
        horses.append(h)
    race["horses"] = horses
    race["field"] = len(horses)
    return race


def run(date: str) -> int:
    src = DATA_DIR / "raw" / date / "rakuten_card"
    n = 0
    for f in sorted(Path(src).glob("*.html")):
        rid = f.stem
        race = parse_card(f.read_text(encoding="utf-8"), rid)
        save_json(f"races/{date}/{rid}.json", race)
        n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    print("parsed", run(ap.parse_args().date))
