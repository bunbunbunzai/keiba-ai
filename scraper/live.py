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


def deploy() -> None:
    """GitHub Actions 内からの push では pages が起動しないため、明示的に起動する。"""
    if not os.environ.get("GH_TOKEN"):
        return
    repo = os.environ.get("GITHUB_REPOSITORY", "bunbunbunzai/keiba-ai")
    r = sh("gh", "workflow", "run", "pages.yml", "-R", repo)
    print("pages dispatch:", "ok" if r.returncode == 0 else r.stderr.strip()[:200])


def push(date: str, n: int) -> None:
    sh("git", "add", "-A", "data", "results_ledger.csv", "predictions")
    if sh("git", "diff", "--cached", "--quiet").returncode == 0:
        return
    sh("git", "commit", "-m", f"live {date} {now():%H:%M} 確定{n}R")
    for _ in range(4):
        if sh("git", "pull", "--rebase", "-X", "theirs").returncode == 0 and sh("git", "push").returncode == 0:
            print("pushed", n)
            deploy()
            return
        sh("git", "rebase", "--abort")
        time.sleep(10)
    print("push failed")


def flush(date: str, before: int) -> int:
    after = confirmed(date)
    print(f"{now():%H:%M} 確定 {before}→{after}")
    if after != before:
        sh("python", "scraper/score.py", "--date", date)
        for src in ("jra", "rakuten"):
            sh("python", "scraper/bias.py", "--date", date, "--source", src)
        if os.environ.get("ANTHROPIC_API_KEY"):
            r = sh("python", "scraper/review_gen.py", "--date", date)
            print((r.stdout or "").strip()[-80:], (r.stderr or "").strip()[-200:])
        push(date, after)
    return after


class Interleaver:
    """出馬表などを取る長い処理の合間に、同じセッション（同じ60秒間隔）で確定結果を1件ずつ取る。
    rakuten.discover の各リクエストの前に呼ばれる。5分ごとに集計して push する。"""

    def __init__(self, every: int = 300):
        self.date = now().strftime("%Y%m%d")
        self.base = confirmed(self.date)
        self.last = time.monotonic()
        self.every = every

    def __call__(self, sess) -> None:
        import results

        nx = results.next_unconfirmed(self.date)
        if nx:
            results.fetch_one(sess, self.date, *nx)
        if time.monotonic() - self.last >= self.every:
            self.done()

    def done(self) -> None:
        self.base = flush(self.date, self.base)
        self.last = time.monotonic()


BET_WINDOW = (22, 90)   # 発走の90〜22分前の自信度Aのレースは、オッズを取り直して買い目を組み直す
ODDS_MAX_AGE = 20       # 発表オッズは20分たったら取り直す
_card_fetched: dict[str, float] = {}


def refresh_bets(date: str) -> bool:
    """発走が近い自信度Aのレースについて、オッズ（中央は3連複の発表オッズ、地方は単勝オッズ）を取り直し、
    bets.py で買い目を組み直す。書き換えたら True。"""
    import bets as BT
    import combo_odds as CO

    t = now()
    jra_ids, local_ids, all_ids = [], [], []
    for f in sorted((ROOT / "predictions" / date).glob("*.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if p.get("confidence") != "A":
            continue
        rid = p.get("race_id")
        rf = DATA_DIR / "races" / date / f"{rid}.json"
        if not rf.exists():
            continue
        post = BT._post_dt(date, json.loads(rf.read_text(encoding="utf-8")))
        if post is None or not (BET_WINDOW[0] < (post - t).total_seconds() / 60 <= BET_WINDOW[1]):
            continue
        all_ids.append(rid)
        if rid.startswith("jra_"):
            tr = BT.load_trio(date, rid)
            age = (t - datetime.fromisoformat(tr["fetched_ts"])).total_seconds() / 60 if tr and tr.get("fetched_ts") else 1e9
            if age > ODDS_MAX_AGE:
                jra_ids.append(rid)
        elif time.monotonic() - _card_fetched.get(rid, -1e9) > ODDS_MAX_AGE * 60:
            local_ids.append(rid)
    if not all_ids:
        return False
    if jra_ids:
        try:
            CO.jra(date, jra_ids)
        except Exception as e:  # noqa: BLE001
            print("combo_odds error:", e)
    if local_ids and not daily_running():
        try:  # 地方は出馬表を取り直して単勝オッズを新しくする（楽天の60秒間隔を守る）
            import rakuten
            from common import PoliteSession, save_raw

            sess = PoliteSession(min_interval=61.0)
            time.sleep(61)
            for rid in local_ids:
                html = sess.get(rakuten.BASE + rakuten.PAGES["card"].format(rid=rid)).text
                save_raw("rakuten_card", date, rid, html)
                _card_fetched[rid] = time.monotonic()
            sh("python", "scraper/parse_rakuten.py", "--date", date)
        except Exception as e:  # noqa: BLE001
            print("rakuten card error:", e)
    changed = BT.apply(date, all_ids, write=True)
    print(f"{now():%H:%M} 買い目の組み直し {len(all_ids)}R（変更 {len(changed)}R）")
    return True


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
    touched = False
    try:
        touched = refresh_bets(date)
    except Exception as e:  # noqa: BLE001
        print("refresh_bets error:", e)
    after = flush(date, before)
    if touched and after == before:  # 結果が増えていなくても、買い目を変えたら push する
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
