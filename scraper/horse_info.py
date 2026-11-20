"""JRAの馬ページから、毛色・馬名の意味・取引市場・賞金・全成績を取る（コラムや馬のページ用）。

対象は data/races の中央の出馬表に載った馬（馬ページのリンクを持っている馬）。
  --names A,B,C            : その馬だけ
  --from YYYYMMDD          : その日以降の出馬表に出た馬すべて（--min-age で年齢をしぼる）
保存：data/horse_info/<馬名のmd5の先頭10文字>.json（--from だけで動かしたときは data/horse_info_scan.json に見た期間も残す）
すでに --fresh 日以内に取った馬は取り直さない。JRAのサイトは1ページごとに5秒あける。
毎月最初の火曜に horse_info.yml が、28日前からの出馬表に出た3歳以上の馬を取り直す。

使い方: python horse_info.py --names ボクマダネムイヨ,ジョスラン
        python horse_info.py --from 20261025 --min-age 3
        python horse_info.py --entrants    # これからのG1の出走予定馬と重賞の特別登録馬（entries の毎日の回で使う）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from common import DATA_DIR, PoliteSession, save_json
from jra import BASE
from jra_cards import parse_horse, text

JST = timezone(timedelta(hours=9))
OUT = DATA_DIR / "horse_info"
KEYS = ("父", "母", "母の父", "母の母", "生年月日", "性別", "馬齢", "毛色", "産地", "馬名意味", "取引市場", "調教師名", "馬主名",
        "生産牧場", "総賞金", "内付加賞", "内地方賞金", "内海外賞金", "収得賞金（平地）", "収得賞金（障害）")


def sid(name: str) -> str:
    return hashlib.md5(name.encode()).hexdigest()[:10]


def now() -> datetime:
    return datetime.now(JST)


def card_horses(since: str = "", names: set[str] | None = None, min_age: int = 0) -> dict[str, dict]:
    """出馬表から 馬名 → {url, date, sex_age}（いちばん新しい出馬表のもの）。"""
    out: dict[str, dict] = {}
    for f in sorted((DATA_DIR / "races").glob("2*/jra_*.json")):
        d = f.parent.name
        if since and d < since:
            continue
        try:
            race = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for h in race.get("horses", []):
            nm = (h.get("name") or "").replace(" ", "").replace("　", "")
            if not nm or not h.get("horse_url"):
                continue
            if names is not None and nm not in names:
                continue
            m = re.search(r"(\d+)", h.get("sex_age") or "")
            # 年齢は1月1日にひとつ上がるので、去年の出馬表の年齢は今年の年齢に直して比べる
            if min_age and (not m or int(m.group(1)) + now().year - int(d[:4]) < min_age):
                continue
            out[nm] = {"url": h["horse_url"], "date": d, "sex_age": h.get("sex_age")}
    if names is not None:  # 馬名を指定したときは、特別レース登録馬（jra_nominations.py）のリンクも使う（出馬表に出る前の週でも取れる）
        for f in sorted((DATA_DIR / "nominations").glob("*.json")):
            try:
                race = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for h in race.get("horses", []):
                nm = (h.get("name") or "").replace(" ", "").replace("　", "")
                if nm in names and h.get("url") and nm not in out:
                    out[nm] = {"url": h["url"], "date": race.get("date") or "", "sex_age": h.get("sex_age")}
    return out


def entrants() -> list[str]:
    """これからのG1の出走予定馬（data/entries）と、これからの重賞の特別登録馬（data/nominations）の馬名。"""
    today = now().strftime("%Y%m%d")
    out: list[str] = []
    for f in sorted((DATA_DIR / "entries").glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if d.get("date", "") >= today:
            out += [h.get("name") or "" for h in d.get("horses") or [] if not h.get("foreign")]
    for f in sorted((DATA_DIR / "nominations").glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if d.get("date", "") >= today and d.get("grade"):
            out += [h.get("name") or "" for h in d.get("horses") or []]
    return list(dict.fromkeys(n.replace(" ", "").replace("　", "") for n in out if n))


def parse(html: str) -> dict:
    s = BeautifulSoup(html, "html.parser")
    prof: dict[str, str] = {}
    for dl in s.find_all("dl"):
        dt, dd = dl.find("dt"), dl.find("dd")
        if not dt or not dd:
            continue
        k = text(dt)
        if k not in KEYS or k in prof:
            continue
        for sp in dd.find_all("span", class_="sanku"):  # 「産駒」のリンクは外す
            sp.decompose()
        prof[k] = text(dd).replace("\xa0", " ")
    info = parse_horse(html)
    for k, v in info["profile"].items():
        prof.setdefault(k, v)
    runs = [{k: r.get(k) for k in ("date", "venue", "race_name", "surface", "distance", "field", "popularity", "finish", "jockey")}
            for r in info["runs"]]
    fin = [r["finish"] for r in runs if r.get("finish")]
    ran = [x for x in fin if x.isdigit()]
    rec = {"starts": len(ran), "wins": sum(x == "1" for x in ran), "second": sum(x == "2" for x in ran),
           "third": sum(x == "3" for x in ran)}
    return {"profile": prof, "record": rec, "runs": runs}


def run(names: list[str], since: str, min_age: int, fresh: int, limit: int) -> int:
    targets = card_horses(since, set(names) if names else None, min_age)
    missing = [n for n in names if n not in targets]
    if missing:
        print("出馬表に馬ページのリンクが無い馬:", "、".join(missing))
    OUT.mkdir(parents=True, exist_ok=True)
    # 全頭の取り直し（--from だけ）のときは、どの日からの出馬表を見たかを残す（データ記事の対象期間に使う）
    scan = {"from": since, "min_age": min_age, "started": now().strftime("%Y-%m-%d %H:%M"), "targets": len(targets)} if since and not names else None
    if scan:
        save_json("horse_info_scan.json", scan)
    sess = PoliteSession(min_interval=5.0, encoding="shift_jis")
    n = 0
    for nm, t in sorted(targets.items(), key=lambda kv: kv[1]["date"], reverse=True):
        f = OUT / f"{sid(nm)}.json"
        if f.exists() and fresh > 0:
            try:
                old = json.loads(f.read_text(encoding="utf-8"))
                if old.get("fetched", "") >= (now() - timedelta(days=fresh)).strftime("%Y-%m-%d"):
                    continue
            except Exception:  # noqa: BLE001
                pass
        if limit and n >= limit:
            break
        try:
            html = sess.get(BASE + t["url"]).text
            got = parse(html)
        except Exception as e:  # noqa: BLE001
            print(f"{nm}: 取得できず（{e}）")
            continue
        got.update(name=nm, url=t["url"], last_card=t["date"], fetched=now().strftime("%Y-%m-%d %H:%M"))
        save_json(f"horse_info/{sid(nm)}.json", got)
        n += 1
        p = got["profile"]
        if names or n % 100 == 0:
            print(f"{n} {nm}: {p.get('毛色', '')} {p.get('馬名意味', '')[:30]} {got['record']}")
    print(f"保存 {n}頭")
    if scan:
        save_json("horse_info_scan.json", {**scan, "finished": now().strftime("%Y-%m-%d %H:%M"), "saved": n})
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", default="", help="カンマ区切りの馬名")
    ap.add_argument("--from", dest="since", default="", help="この日以降の出馬表に出た馬（YYYYMMDD）")
    ap.add_argument("--min-age", type=int, default=0)
    ap.add_argument("--fresh", type=int, default=7, help="この日数以内に取った馬は取り直さない（0で毎回取る）")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--entrants", action="store_true", help="これからのG1の出走予定馬と重賞の特別登録馬を取る")
    a = ap.parse_args()
    nm = [x.strip() for x in re.split(r"[,、\s]+", a.names) if x.strip()]
    if a.entrants:
        nm = list(dict.fromkeys(nm + entrants()))
        print("出走予定・登録馬", len(nm), "頭")
        if not nm:
            raise SystemExit(0)
    if not nm and not a.since:
        ap.error("--names か --from のどちらかを指定する")
    run(nm, a.since, a.min_age, a.fresh, a.limit)
