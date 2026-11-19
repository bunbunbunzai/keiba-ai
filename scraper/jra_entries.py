"""JRA：G1の出走予定馬を取る（JRAの「GⅠ競走プレレーティング」のページ）。

JRAは G1 の週の月曜11時ごろ（土曜のG1も同じ週の月曜）に、出走予定馬のプレレーティングを
  https://www.jra.go.jp/datafile/ranking/g1/<年>/<略号>.html
に出す。出走できる頭数までの馬名・性・年齢・調教師と、今年のレーティング最高値（とそのレース）が表で載る。
特別登録の締切日（日曜夕方）に出る「出走馬決定順一覧」はPDFに文字が埋め込まれていないので使わない。

対象は、今日から --days 日以内に行われるJRAのG1（日程は data/graded_hist、ページの略号は下の KEY か、
「GⅠレース出走馬決定順一覧」のページのリンクから日付で引く）。発表前のページには表が無いので、そのときは何もしない。

保存：data/entries/<slug>-<日付>.json（中身が変わったときだけ書き直す。取った時刻だけの違いでは書かない）
  --probe：取ったページを data/raw/<今日>/jra_entries/ にも残す（読み取りの確認用）

  python jra_entries.py --days 10
  python jra_entries.py --slug mile-championship --date 20261122 --probe
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from common import DATA_DIR, PoliteSession, save_raw

JST = timezone(timedelta(hours=9))
OUT = DATA_DIR / "entries"
HOSTS = ("https://www.jra.go.jp", "https://jra.jp")
INDEX = "/keiba/tokubetsu/"
# このサイトの重賞ページの URL名 → JRA のページの略号（G1）。無いレースは一覧ページのリンクから日付で引く
KEY = {
    "february-stakes": "feb", "takamatsunomiya-kinen": "takamatsu", "osaka-hai": "osaka", "oka-sho": "ouka",
    "nakayama-grand-jump": "ngj", "satsuki-sho": "satsuki", "tenno-sho-spring": "haruten", "nhk-mile-cup": "nmc",
    "victoria-mile": "victoria", "yushun-himba": "oaks", "oaks": "oaks", "derby": "derby", "tokyo-yushun": "derby",
    "yasuda-kinen": "yasuda", "takarazuka-kinen": "takara", "sprinters-stakes": "sprint", "shuka-sho": "shuka",
    "kikka-sho": "kikka", "tenno-sho-autumn": "akiten", "queen-elizabeth-cup": "eliza", "mile-championship": "mile",
    "japan-cup": "jc", "champions-cup": "cc", "hanshin-juvenile-fillies": "hjf", "asahi-hai-fs": "afs",
    "nakayama-daishogai": "daishogai", "hopeful-stakes": "hopeful", "arima-kinen": "arima",
}


def now() -> datetime:
    return datetime.now(JST)


def nfkc(s) -> str:
    return unicodedata.normalize("NFKC", str(s or "")).strip()


def upcoming_g1(today: str, days: int) -> list[dict]:
    """今日から days 日以内のJRAのG1：[{date, slug, abbr, grade, venue}]。"""
    import graded_cols as G  # noqa: PLC0415
    with contextlib.redirect_stdout(io.StringIO()):
        keyed = G.keyed(G.load_all())
    hi = (datetime.strptime(today, "%Y%m%d") + timedelta(days=days)).strftime("%Y%m%d")
    out = []
    for slug, years in keyed.items():
        for r in years.values():
            if today <= r.get("date", "") <= hi and "G1" in (r.get("grade") or "").replace("Ⅰ", "1"):
                out.append({"date": r["date"], "slug": slug, "abbr": r.get("abbr", ""), "grade": r.get("grade", ""), "venue": r.get("venue", "")})
    return sorted(out, key=lambda x: x["date"])


def _get(sess: PoliteSession, path: str) -> tuple[str, str]:
    last = None
    for h in HOSTS:
        try:
            r = sess.get(h + path)
            r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii") else r.encoding
            return h + path, r.text
        except Exception as e:  # noqa: BLE001
            last = e
    raise last  # type: ignore[misc]


def keys_from_index(html: str, year: str) -> dict[str, str]:
    """「GⅠレース出走馬決定順一覧」のページから {YYYYMMDD: 略号}（同じ日に2つあれば 日付+レース名）。"""
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for tr in soup.find_all("tr"):
        t = nfkc(tr.get_text(" ", strip=True))
        m = re.search(r"(\d{1,2})月(\d{1,2})日", t)
        a = tr.find("a", href=re.compile(r"/keiba/g1/([a-z0-9]+)\.html"))
        if m and a:
            key = re.search(r"/keiba/g1/([a-z0-9]+)\.html", a["href"]).group(1)
            d = f"{year}{int(m.group(1)):02d}{int(m.group(2)):02d}"
            out.setdefault(d, key)
            out[d + nfkc(a.get_text(strip=True))] = key
    return out


def _header(tbl) -> tuple[list[str], int]:
    """表の見出し行（th だけの行）を、rowspan・colspan をほどいて列ごとの名前にする。(列名, 見出しの行数)"""
    rows = tbl.find_all("tr")
    hdr = []
    for tr in rows:
        cells = tr.find_all(["th", "td"])
        if cells and all(c.name == "th" for c in cells):
            hdr.append(cells)
        else:
            break
    grid: dict[tuple[int, int], str] = {}
    for ri, cells in enumerate(hdr):
        ci = 0
        for c in cells:
            while (ri, ci) in grid:
                ci += 1
            rs, cs = int(c.get("rowspan") or 1), int(c.get("colspan") or 1)
            label = nfkc(c.get_text(" ", strip=True))
            for dr in range(rs):
                for dc in range(cs):
                    grid[(ri + dr, ci + dc)] = label
            ci += cs
    ncol = max((k[1] for k in grid), default=-1) + 1
    names = []
    for ci in range(ncol):
        parts = []
        for ri in range(len(hdr)):
            v = grid.get((ri, ci), "")
            if v and (not parts or parts[-1] != v):
                parts.append(v)
        names.append(" ".join(parts))
    return names, len(hdr)


def parse_prerating(html: str) -> dict | None:
    """表があれば {published, max_runners, horses:[...]}。発表前（表が無い）なら None。"""
    soup = BeautifulSoup(html, "html.parser")
    text = nfkc(soup.get_text(" ", strip=True))
    horses = []
    for tbl in soup.find_all("table"):
        cols, nh = _header(tbl)
        hj = " ".join(cols)
        if "馬名" not in hj:
            continue
        for tr in tbl.find_all("tr")[nh:]:
            cells = [nfkc(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
            if len(cells) < 3:
                continue
            row = dict(zip(cols, cells)) if len(cols) == len(cells) else dict(zip(
                ["馬名", "性", "年齢", "調教師", "レーティング 最高値", "レーティング 該当レース"], cells))
            name = re.sub(r"\s+", "", row.get("馬名", "") or "")
            if not name or name == "馬名":
                continue
            h = {"name": name}
            for k, v in row.items():
                if k == "馬名":
                    continue
                if k in ("性", "性別"):
                    h["sex"] = v
                elif "年齢" in k or k == "齢":
                    h["age"] = v
                elif k.startswith("性齢"):
                    h["sex"], h["age"] = v[:1], re.sub(r"\D", "", v)
                elif "調教師" in k:
                    h["trainer"] = re.sub(r"\s+", "", v)
                elif "国" in k:
                    h["country"] = v
                elif "レース" in k:
                    h["rating_race"] = v
                elif "最高値" in k or "レーティング" in k:
                    h["rating"] = "" if v in ("-", "－", "―", "") else v
                else:
                    h.setdefault("extra", {})[k] = v
            horses.append(h)
    if not horses:
        return None
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    pub = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""
    g = re.search(r"出走可能頭数\s*(\d+)\s*頭", text)
    return {"published": pub, "max_runners": int(g.group(1)) if g else None, "horses": horses}


def run(today: str, days: int, only_slug: str = "", only_date: str = "", probe: bool = False) -> int:
    races = upcoming_g1(today, days)
    if only_slug:
        races = [r for r in races if r["slug"] == only_slug] or ([{"date": only_date, "slug": only_slug, "abbr": "", "grade": "G1", "venue": ""}] if only_date else [])
    if not races:
        print("対象のG1なし")
        return 0
    sess = PoliteSession(min_interval=5.0)  # JRA は1ページごとに5秒あける
    idx = None
    n = 0
    for r in races:
        year = r["date"][:4]
        key = KEY.get(r["slug"])
        if not key:
            if idx is None:
                try:
                    url_i, h = _get(sess, INDEX)
                    idx = keys_from_index(h, year)
                    if probe:
                        save_raw("jra_entries", today, "index", h)
                except Exception as e:  # noqa: BLE001
                    print("一覧ページを読めない:", e)
                    idx = {}
            key = idx.get(r["date"])
        if not key:
            print(f"{r['date']} {r['slug']}: JRAのページの略号が分からない")
            continue
        path = f"/datafile/ranking/g1/{year}/{key}.html"
        try:
            url, html = _get(sess, path)
        except Exception as e:  # noqa: BLE001
            print(f"{r['date']} {r['slug']}: 読めない {e}")
            continue
        if probe:
            save_raw("jra_entries", today, f"{key}_{r['date']}", html)
        got = parse_prerating(html)
        if not got:
            print(f"{r['date']} {r['slug']}: まだ発表されていない（{url}）")
            continue
        obj = {"slug": r["slug"], "date": r["date"], "race": r["abbr"], "grade": r["grade"], "venue": r["venue"], "key": key,
               "source": "https://www.jra.go.jp" + path, "kind": "prerating", **got}
        f = OUT / f"{r['slug']}-{r['date']}.json"
        old = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
        if old and {k: v for k, v in old.items() if k != "fetched"} == obj:
            print(f"{r['date']} {r['slug']}: 変わりなし（{len(got['horses'])}頭）")
            continue
        obj["fetched"] = now().strftime("%Y-%m-%d %H:%M")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{r['date']} {r['slug']}: {len(got['horses'])}頭を保存（発表 {got['published']}）")
        n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--today", default=now().strftime("%Y%m%d"))
    ap.add_argument("--slug", default="")
    ap.add_argument("--date", default="", help="--slug と一緒に：日程に無いときの開催日（確認用）")
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    sys.exit(0 if run(a.today, a.days, a.slug, a.date, a.probe) >= 0 else 1)
