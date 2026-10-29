"""日中のライブ集計：数分おきに発走済みレースの結果を取り込み、的中判定・回収率・バイアスを更新して push する。

使い方: python scraper/live.py --date 20261030 --until 21:25 [--interval 300]
- JRA は結果一覧から未取得のレースだけ開く（3秒間隔）
- 楽天競馬は取得済み出馬表のレースIDを使い、発走8分後から払戻が出るまで取り直す（60秒間隔）
- daily（出馬表などの取得）が動いている間は、楽天への同時アクセスを避けるため楽天を休む
- 新しい結果が入ったときだけ score.py・bias.py を回して commit/push する（push でサイトが更新される）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone

from common import DATA_DIR

ROOT = DATA_DIR.parent
JST = timezone(timedelta(hours=9))


def now() -> datetime:
    return datetime.now(JST)


def sh(*cmd, check=False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=check)


def daily_running() -> bool:
    if not os.environ.get("GH_TOKEN"):
        return False
    r = sh("gh", "run", "list", "--workflow", "daily.yml", "--json", "status", "-L", "5")
    try:
        return any(x["status"] in ("in_progress", "queued") for x in json.loads(r.stdout or "[]"))
    except Exception:  # noqa: BLE001
        return False


def confirmed(date: str) -> int:
    d = DATA_DIR / "results" / date
    n = 0
    for f in d.glob("*.json"):
        if f.name == "score.json":
            continue
        p = json.loads(f.read_text(encoding="utf-8")).get("payouts") or {}
        n += any(not k.startswith("_") for k in p)
    return n


def push(date: str, n: int) -> None:
    sh("git", "add", "-A", "data", "results_ledger.csv")
    if sh("git", "diff", "--cached", "--quiet").returncode == 0:
        return
    sh("git", "commit", "-m", f"live {date} {now():%H:%M} 確定{n}R")
    for _ in range(4):
        if sh("git", "pull", "--rebase", "-X", "theirs").returncode == 0 and sh("git", "push").returncode == 0:
            print("pushed", n)
            return
        sh("git", "rebase", "--abort")
        time.sleep(10)
    print("push failed")


def cycle(date: str) -> None:
    import results

    before = confirmed(date)
    try:
        results.jra(date)
    except Exception as e:  # noqa: BLE001
        print("jra error:", e)
    if daily_running():
        print("daily 実行中のため楽天は休み")
    else:
        try:
            results.rakuten(date, finished_only=True, local=True, after_min=8)
        except Exception as e:  # noqa: BLE001
            print("rakuten error:", e)
    after = confirmed(date)
    print(f"{now():%H:%M} 確定 {before}→{after}")
    if after != before:
        sh("python", "scraper/score.py", "--date", date)
        for src in ("jra", "rakuten"):
            sh("python", "scraper/bias.py", "--date", date, "--source", src)
        push(date, after)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--until", default="21:25")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--max-minutes", type=int, default=345)
    a = ap.parse_args()
    h, m = map(int, a.until.split(":"))
    end = min(datetime.strptime(a.date, "%Y%m%d").replace(hour=h, minute=m, tzinfo=JST),
              now() + timedelta(minutes=a.max_minutes))
    print("live until", end)
    while now() < end:
        t0 = time.monotonic()
        cycle(a.date)
        rest = a.interval - (time.monotonic() - t0)
        if rest > 0 and now() + timedelta(seconds=rest) < end:
            time.sleep(rest)
        elif rest > 0:
            break
    cycle(a.date)


if __name__ == "__main__":
    main()
