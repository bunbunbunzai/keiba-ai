"""JRAの出馬表から、これから数日のうちに行われる重賞の出走馬・枠順だけを取り、data/waku に保存する。AIは呼ばない。

JRAの発表（https://www.jra.go.jp/faq/pop02/2_2.html）：
- 出走馬（馬番・枠番なし）：木曜の16時すぎ（有馬記念の週の有馬記念は14時すぎ）
- 枠順（馬番・枠番あり）：G1など前日発売のある重賞は金曜の朝（G1の週は9時すぎ、ほかは10時すぎ）。
  有馬記念は木曜の夕方の公開枠順抽選（17〜18時ごろ）で決まる
予想の元データの出馬表（data/races。近走つき）は金曜の昼の「重賞の早出し予想」と前日の夕方に取る。
それより前に、特集まとめ・重賞ページの「出走馬・枠順」の表と題名に使うためのもの。
予想の流れと混ざらないよう data/races には書かない。JRAのサイトは1ページごとに5秒あける。

保存：data/waku/<日付>_<場>_<R>.json
  {fetched, date, race_no, venue, post_time, title_text, grade, race_name, distance, surface, course_text,
   numbered（全頭に馬番があるか）, field, horses: [{frame, number, name, horse_url, sex_age, weight, jockey, trainer}], source}
中身が変わったときだけ書き直す。馬番のある表を、あとから馬番の無い表で上書きしない。終わったレースは1週間で消す。

  python jra_waku.py             # 今日から3日先までの重賞
  python jra_waku.py --days 4
  python jra_waku.py --probe     # 生のHTMLも data/raw/<今日>/jra_waku に残す（形の確認用。表が読めなかったときは毎回残す）
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone

from common import DATA_DIR, PoliteSession, save_json, save_raw
from jra import open_action
from jra_cards import find_all_race_pages, parse_all_races

JST = timezone(timedelta(hours=9))
GRADES = ("G1", "G2", "G3", "J・G1", "J・G2", "J・G3")
KEEP = ("frame", "number", "name", "horse_url", "sex_age", "weight", "jockey", "trainer")
RACE_KEYS = ("race_no", "venue", "post_time", "title_text", "grade", "race_name", "distance", "surface", "course_text")


def graded_dates(today: str, days: int) -> list[str]:
    """data/graded_hist/<年>.json の日程（JRA公式の重賞の一覧）から、今日から days 日先までに重賞がある日。"""
    hi = (datetime.strptime(today, "%Y%m%d") + timedelta(days=days)).strftime("%Y%m%d")
    out = set()
    for y in sorted({today[:4], hi[:4]}):
        f = DATA_DIR / "graded_hist" / f"{y}.json"
        if not f.exists():
            continue
        for r in json.loads(f.read_text(encoding="utf-8")).get("races") or []:
            if today <= (r.get("date") or "") <= hi:
                out.add(r["date"])
    return sorted(out)


def run(days: int, probe: bool) -> int:
    now = datetime.now(JST)
    today = now.strftime("%Y%m%d")
    dates = graded_dates(today, days)
    if not dates:
        print("対象の重賞なし")
        return 0
    sess = PoliteSession(min_interval=5.0, encoding="shift_jis")
    saved = 0
    for d in dates:
        try:
            pages = find_all_race_pages(sess, d)
        except Exception as e:  # noqa: BLE001
            print(f"{d}: 出馬表の一覧を開けず（{e}）")
            continue
        if not pages:
            print(f"{d}: 出馬表はまだ出ていない")
            continue
        for path, cname in pages:
            try:
                html = open_action(sess, path, cname)
            except Exception as e:  # noqa: BLE001
                print(f"{cname}: 開けず（{e}）")
                continue
            races = parse_all_races(html)
            if probe or not races:
                save_raw("jra_waku", today, re.sub(r"[^0-9A-Za-z]", "_", cname), html)
            if not races:
                print(f"{cname}: 表を読めず（data/raw に保存）")
            for r in races:
                if r.get("grade") not in GRADES or not r.get("horses") or (r.get("date") or "").replace("-", "") != d:
                    continue
                hs = [{k: h.get(k) for k in KEEP} for h in r["horses"]]
                numbered = all(h.get("number") for h in hs)
                key = f"{d}_{r.get('venue') or 'X'}_{r['race_no']:02d}"
                f = DATA_DIR / "waku" / f"{key}.json"
                old = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
                body = {"date": d, **{k: r.get(k) for k in RACE_KEYS}, "numbered": numbered, "field": len(hs), "horses": hs, "source": "jra"}
                if old and {k: v for k, v in old.items() if k != "fetched"} == body:
                    print(f"{key}: 変わらず")
                    continue
                if old.get("numbered") and not numbered:
                    print(f"{key}: 馬番の無い表なので上書きしない（枠順は取得済み）")
                    continue
                save_json(f"waku/{key}.json", {"fetched": now.strftime("%Y-%m-%d %H:%M"), **body})
                saved += 1
                print(f"{key}: {r.get('race_name')}（{r.get('grade')}） {len(hs)}頭・{'枠順あり' if numbered else '馬番なし'}")
    old_day = (now - timedelta(days=7)).strftime("%Y%m%d")
    for f in (DATA_DIR / "waku").glob("*.json"):
        if f.stem[:8] < old_day:
            f.unlink()
    print(f"保存 {saved}")
    return saved


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    run(a.days, a.probe)
