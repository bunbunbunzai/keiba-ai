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


def has_payouts(f) -> bool:
    if not f.exists():
        return False
    d = json.loads(f.read_text(encoding="utf-8"))
    return not d.get("error") and any(not k.startswith("_") for k in (d.get("payouts") or {}))


def has_full_result(f) -> bool:
    """払戻に加えて着順（と4角位置）まで取れているか。楽天は確定直後だと払戻だけ出て
    全着順が「ページに反映されるまでしばらくお待ちください」のことがあるので、その場合は取り直す。"""
    if not has_payouts(f):
        return False
    rows = json.loads(f.read_text(encoding="utf-8")).get("rows") or []
    return bool(rows) and any(r.get("pos4") is not None for r in rows)


def drop_cache(url: str) -> None:
    from jra_cards import CNAME_RE
    cm = CNAME_RE.search(url)
    if cm:
        (DATA_DIR / "cache" / "jra_result" / f"{re.sub(r'[^0-9A-Za-z]', '_', cm.group(1))}.html").unlink(missing_ok=True)


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
            m = re.search(r"pw01sde\d{2}(\d{2})(\d{4})(\d{2})(\d{2})(\d{2})", url)
            venue_code, rno = (m.group(1), int(m.group(5))) if m else ("XX", 0)
            if has_payouts(DATA_DIR / "results" / target / f"jra_{venue_code}_{rno:02d}.json"):
                continue  # 確定済みは取り直さない
            rh = cached_result(sess, url)
            res = parse_result(rh)
            if not res.get("payouts"):
                drop_cache(url)  # 未確定のページはキャッシュしない（次回取り直す）
            title = BeautifulSoup(rh, "html.parser").title
            res.update(source="jra", date=target, venue_code=venue_code, race_no=rno, url=url,
                       title=text(title))
            save_json(f"results/{target}/jra_{venue_code}_{rno:02d}.json", res)
            n += 1
    return n


# ---------------- 楽天競馬 ----------------
def _finished(target: str, rid: str, minutes: int = 15) -> bool:
    """発走から minutes 分以上たったレースだけ True（日中の取得用）。"""
    from datetime import datetime, timedelta, timezone

    f = DATA_DIR / "races" / target / f"{rid}.json"
    if not f.exists():
        return False
    pt = json.loads(f.read_text(encoding="utf-8")).get("post_time") or ""
    if not re.fullmatch(r"\d{1,2}:\d{2}", pt):
        return False
    jst = timezone(timedelta(hours=9))
    h, m = map(int, pt.split(":"))
    post = datetime.strptime(target, "%Y%m%d").replace(hour=h, minute=m, tzinfo=jst)
    return datetime.now(jst) > post + timedelta(minutes=minutes)

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


def corner_positions(order: str) -> dict:
    """「10,7,(1,5),6=4,3」のような通過順を {馬番: 位置} にする。括弧内は同じ位置。"""
    pos, cur, out = 1, [], {}
    i = 0
    toks = re.findall(r"\(|\)|\d+", order)
    group = None
    for t in toks:
        if t == "(":
            group = []
        elif t == ")":
            for n in group or []:
                out[n] = pos
            pos += len(group or [])
            group = None
        elif group is not None:
            group.append(int(t))
        else:
            out[int(t)] = pos
            pos += 1
    return out


def parse_rakuten_performance(html: str) -> list[dict]:
    s = BeautifulSoup(html, "html.parser")
    t = table_by_headers(s, ["着順", "馬名"])
    # コーナー通過順位表の最後の行（ふつうは4角）から各馬の位置を出す
    ct = s.find("table", attrs={"summary": "コーナー通過順位"})
    last_corner = {}
    if ct:
        tds = ct.find_all("td")
        if tds:
            last_corner = corner_positions(text(tds[-1]))
    rows = []
    for d in rows_as_dicts(t) if t else []:
        n = num(d.get("馬番"), int)
        rows.append({
            "finish": d.get("着順"),
            "frame": num(d.get("枠"), int),
            "number": n,
            "name": d.get("馬名"),
            "time": d.get("タイム"),
            "margin": d.get("着差"),
            "pos4": last_corner.get(n),
            "last3f": num(d.get("推定上がり") or d.get("上がり3F") or d.get("上がり")),
            "popularity": num(d.get("人気"), int),
        })
    return rows


def local_race_ids(target: str) -> list[list[str]]:
    """取得済みの出馬表から楽天のレースIDを発走順に（一覧ページを開かずに済む）。"""
    rs = []
    for f in (DATA_DIR / "races" / target).glob("*.json"):
        if f.stem.startswith("jra_"):
            continue
        pt = json.loads(f.read_text(encoding="utf-8")).get("post_time") or "99:99"
        rs.append((pt.zfill(5), f.stem))
    return [[rid for _, rid in sorted(rs)]]


def rakuten(target: str, limit_races: int | None = None, finished_only: bool = False,
            local: bool = False, after_min: int = 15, max_tries: int = 8) -> int:
    from rakuten import BASE, PAGES, race_ids, venue_lists

    sess = PoliteSession(min_interval=60.0)
    n = 0
    groups = local_race_ids(target) if local else [race_ids(sess, target, v) for v in venue_lists(sess, target)]
    for ids in groups:
        for rid in ids[:limit_races]:
            done = DATA_DIR / "results" / target / f"{rid}.json"
            prev = json.loads(done.read_text(encoding="utf-8")) if done.exists() else {}
            if has_full_result(done):
                continue  # 確定済みはとばす（払戻か着順が出ていなければ取り直す）
            if prev.get("tries", 0) >= max_tries:
                continue  # 取消・中止などで払戻が出ないレースは打ち切る
            if finished_only and not _finished(target, rid, after_min):
                continue
            fetch_one(sess, target, rid, prev)
            n += 1
    return n


def fetch_one(sess, target: str, rid: str, prev: dict | None = None) -> dict:
    from rakuten import BASE, PAGES

    prev = prev or {}
    out = {"source": "rakuten", "date": target, "race_id": rid, "tries": prev.get("tries", 0) + 1}
    try:
        ph = sess.get(BASE + PAGES["performance"].format(rid=rid)).text
        save_raw("rakuten_performance", target, rid, ph)
        out["payouts"] = parse_rakuten_payouts(ph)
        out["rows"] = parse_rakuten_performance(ph)
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    save_json(f"results/{target}/{rid}.json", out)
    return out


def next_unconfirmed(target: str, after_min: int = 8, max_tries: int = 8):
    """発走から after_min 分たって、まだ払戻が取れていない楽天のレースを1つ返す。"""
    for rid in local_race_ids(target)[0]:
        done = DATA_DIR / "results" / target / f"{rid}.json"
        if has_full_result(done) or not _finished(target, rid, after_min):
            continue
        prev = json.loads(done.read_text(encoding="utf-8")) if done.exists() else {}
        if prev.get("tries", 0) < max_tries:
            return rid, prev
    return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--source", default="both")
    ap.add_argument("--limit-races", type=int, default=None)
    ap.add_argument("--finished-only", action="store_true", help="発走済みのレースだけ（日中のバイアス判定用）")
    ap.add_argument("--local", action="store_true", help="レース一覧を取得済みの出馬表から作る")
    ap.add_argument("--after-min", type=int, default=15)
    a = ap.parse_args()
    if a.source in ("jra", "both"):
        print("JRA results:", jra(a.date))
    if a.source in ("rakuten", "both"):
        print("rakuten results:", rakuten(a.date, a.limit_races, a.finished_only, a.local, a.after_min))
