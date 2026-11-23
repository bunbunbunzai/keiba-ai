"""IndexNow：中身が変わったページだけを Bing などの検索エンジンに知らせる（ChatGPT検索は Bing の索引を多く使う）。

2026-11-23 に作り直した。それまでは「サイトマップの更新日が今日か昨日のページ」を公開のたびに送っていて、
同じ約700ページを1日に10回ほど送り直していた（20日で約17.8万件。その間に Bing に登録されたのは152ページ）。

仕組み：サイトを作るとき build.py が _site/indexnow-state.json を書く（ページ → いまの状態を表す短い文字。更新日＋印）。
  python site/indexnow.py diff   # 公開の前：公開中の indexnow-state.json と比べ、新しいページ・状態が変わったページを一覧にする
  python site/indexnow.py send   # 公開のあと：その一覧を IndexNow に送る
- 公開中の一覧がまだ無い最初の1回は、全部のページを1回だけ送る（まだ Bing に無いページをまとめて知らせる）。
- 公開中の一覧を取れなかったとき（通信の失敗）は、同じページの送り直しを避けるため、その回は何も送らない。
- 1ページが送られるのは、新しくできたとき・更新日が変わったとき・レースの結果が載ったときだけ（多くても1日1〜2回）。
鍵は公開してよいもの（サイト直下の <key>.txt で所有を証明する仕組み）。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOST = "www.ai-keiba-log.com"
STATE = HERE.parent / "_site" / "indexnow-state.json"
LIST = Path(os.environ.get("RUNNER_TEMP") or "/tmp") / "indexnow_urls.json"
MAX_PER_POST = 10000  # IndexNow の上限


def live_state() -> dict | None:
    """公開中の一覧。まだ無ければ {}（最初の1回）。取れなければ None。"""
    url = f"https://{HOST}/indexnow-state.json?t={int(time.time())}"  # ?t= は配信側の一時保存（約10分）を避けるため
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "keiba-ai-indexnow"}), timeout=30) as r:
                d = json.loads(r.read().decode("utf-8"))
                return d if isinstance(d, dict) else None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            print("indexnow: 公開中の一覧を取れず", e.code, file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print("indexnow: 公開中の一覧を取れず", e, file=sys.stderr)
        time.sleep(5 * (i + 1))
    return None


def diff() -> None:
    cur = json.loads(STATE.read_text(encoding="utf-8"))
    prev = live_state()
    if prev is None:
        changed = []
        print("indexnow diff: 公開中の一覧を取れなかったので、今回は送らない")
    else:
        changed = [u for u, t in cur.items() if prev.get(u) != t]
        print(f"indexnow diff: 全{len(cur)}ページのうち、新しい・変わった {len(changed)}ページ" + ("（最初の1回：全部）" if not prev else ""))
    LIST.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")


def send() -> None:
    if not LIST.exists():
        print("indexnow send: 送る一覧が無い（diff が動いていない）")
        return
    paths = json.loads(LIST.read_text(encoding="utf-8"))
    if not paths:
        print("indexnow send: 0")
        return
    key = (HERE / "indexnow_key.txt").read_text().strip()
    urls = [f"https://{HOST}{p}" for p in paths]
    for i in range(0, len(urls), MAX_PER_POST):
        part = urls[i:i + MAX_PER_POST]
        body = json.dumps({"host": HOST, "key": key, "keyLocation": f"https://{HOST}/{key}.txt", "urlList": part}).encode()
        req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, headers={"Content-Type": "application/json; charset=utf-8"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                print("indexnow send:", r.status, len(part))
        except Exception as e:  # noqa: BLE001
            print("indexnow error", e, file=sys.stderr)


if __name__ == "__main__":
    {"diff": diff, "send": send}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print("usage: indexnow.py diff|send"))()
