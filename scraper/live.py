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


BET_WINDOW = (22, 90)   # 発走の90〜22分前のレースは、オッズを見て◎・自信度・買い目（単勝か複勝か）を決め直す
ODDS_MAX_AGE = 20       # 地方の単勝オッズは20分たったら取り直す
LAST_WINDOW = (2, 12)   # 地方は発走の12〜2分前にもう一度出馬表を取り、直前のオッズを final_odds に残す
_card_fetched: dict[str, float] = {}
_last_done: set[str] = set()


def refresh_bets(date: str) -> bool:
    """発走が近いレースについて、地方は単勝オッズを取り直し（中央は日中の取得で足りる）、
    blend.py で◎と自信度を、bets.py で買い目を組み直す。書き換えたら True。
    （3連複の発表オッズの取得は、11/11に3連複をやめたので行わない）"""
    import bets as BT

    t = now()
    local_ids, all_ids, last_ids = [], [], []
    for f in sorted((ROOT / "predictions" / date).glob("*.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        rid = p.get("race_id")
        rf = DATA_DIR / "races" / date / f"{rid}.json"
        if not rf.exists():
            continue
        post = BT._post_dt(date, json.loads(rf.read_text(encoding="utf-8")))
        if post is None:
            continue
        mins = (post - t).total_seconds() / 60
        if (not rid.startswith("jra_") and LAST_WINDOW[0] < mins <= LAST_WINDOW[1] and rid not in _last_done
                and not (DATA_DIR / "final_odds" / date / f"{rid}.json").exists()):
            last_ids.append(rid)
        if not (BET_WINDOW[0] < mins <= BET_WINDOW[1]):
            continue
        all_ids.append(rid)
        if not rid.startswith("jra_") and time.monotonic() - _card_fetched.get(rid, -1e9) > ODDS_MAX_AGE * 60:
            local_ids.append(rid)  # 地方は全レース：◎と自信度が単勝オッズで決まるので、発走前のオッズで決め直す
    if last_ids and not daily_running():
        try:  # 発走直前の出馬表（オッズ）を取り、final_odds に残す（確定オッズとの差を測るため。最大2レース）
            import final_odds
            import rakuten
            from common import PoliteSession, save_raw

            sess = PoliteSession(min_interval=61.0)
            time.sleep(61)
            for rid in last_ids[:2]:
                html = sess.get(rakuten.BASE + rakuten.PAGES["card"].format(rid=rid)).text
                save_raw("rakuten_card_last", date, rid, html)
                _last_done.add(rid)
                import parse_rakuten

                race = parse_rakuten.parse_card(html, rid)
                cur = DATA_DIR / "races" / date / f"{rid}.json"
                if race.get("horses") and cur.exists():
                    base = json.loads(cur.read_text(encoding="utf-8"))  # 出馬表のファイルは書き換えず、オッズだけ取り出す
                    by = {h.get("number"): h for h in race["horses"]}
                    tmp = dict(base, horses=[dict(h, odds=(by.get(h.get("number")) or {}).get("odds"),
                                                  popularity=(by.get(h.get("number")) or {}).get("popularity")) for h in base.get("horses") or []])
                    final_odds.snapshot_race(date, rid, tmp, "直前")
        except Exception as e:  # noqa: BLE001
            print("last odds error:", e)
    if not all_ids:
        return False
    if local_ids and not daily_running():
        try:  # 地方は出馬表を取り直して単勝オッズを新しくする（楽天の60秒間隔を守る）
            import rakuten
            from common import PoliteSession, save_raw

            sess = PoliteSession(min_interval=61.0)
            time.sleep(61)
            for rid in local_ids[:4]:  # 1回の周回で取り直すのは4レースまで（楽天の60秒間隔を守りつつ周回を止めない）
                html = sess.get(rakuten.BASE + rakuten.PAGES["card"].format(rid=rid)).text
                save_raw("rakuten_card", date, rid, html)
                _card_fetched[rid] = time.monotonic()
            sh("python", "scraper/parse_rakuten.py", "--date", date)
        except Exception as e:  # noqa: BLE001
            print("rakuten card error:", e)
    import blend as BL

    moved = BL.apply(date, all_ids, write=True)  # オッズが動いて補正勝率の1位が変われば◎も変わる
    changed = BT.apply(date, all_ids, write=True)
    print(f"{now():%H:%M} 買い目の組み直し {len(all_ids)}R（◎変更 {len(moved)}R・買い目変更 {len(changed)}R）")
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
    try:  # 一変候補（実験）の記録：オッズが動くと「人気薄」の判定が変わるので、発走前のレースだけ更新する
        import ippen

        ippen.record(date)
    except Exception as e:  # noqa: BLE001
        print("ippen error:", e)
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
