"""IndexNow：中身が変わったページだけを Bing などの検索エンジンに知らせる（ChatGPT検索は Bing の索引を多く使う）。

2026-11-23 に作り直した。それまでは「サイトマップの更新日が今日か昨日のページ」を公開のたびに送っていて、
同じ約700ページを1日に10回ほど送り直していた（20日で約17.8万件。その間に Bing に登録されたのは152ページ）。

仕組み：サイトを作るとき build.py が _site/indexnow-state.json を書く（ページ → いまの状態を表す短い文字。更新日＋印）。
  python site/indexnow.py diff   # 公開の前：前回までに知らせた状態（.indexnow/sent.json）と比べ、新しいページ・状態が変わったページを一覧にする
  python site/indexnow.py send   # 公開のあと：その一覧を IndexNow に送り、送れたら「知らせた状態」を今の状態に進める
- .indexnow/sent.json は GitHub Actions の cache で次の回に引き継ぐ（pages.yml）。進めるのは送信が成功したあとだけ。
  公開の途中で取り消された回（新しい公開に追い越された回）は何も送らず、状態も進まないので、次の回がまとめて送る。
  （はじめは公開中の indexnow-state.json と比べていたが、公開だけ済んで送信の前に取り消された回があると、送らないまま
  「知らせた」ことになってしまった）
- sent.json が無いとき（最初の1回・cache が消えたとき）は、全部のページを1回だけ送る（まだ Bing に無いページをまとめて知らせる）。
- 1ページが送られるのは、新しくできたとき・更新日が変わったとき・レースの結果が載ったときだけ（多くても1日1〜2回）。
鍵は公開してよいもの（サイト直下の <key>.txt で所有を証明する仕組み）。
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HOST = "www.ai-keiba-log.com"
STATE = ROOT / "_site" / "indexnow-state.json"   # 今回作ったサイトの状態
SENT = ROOT / ".indexnow" / "sent.json"            # 前回までに知らせた状態（Actions の cache で引き継ぐ）
LIST = Path(os.environ.get("RUNNER_TEMP") or "/tmp") / "indexnow_urls.json"
MAX_PER_POST = 10000  # IndexNow の上限


def changed_paths(cur: dict, prev: dict | None) -> list[str]:
    """新しいページと、状態が変わったページ。prev が None（知らせた記録が無い）なら全部。消えたページは送らない。"""
    if prev is None:
        return list(cur)
    return [u for u, t in cur.items() if prev.get(u) != t]


def load_sent() -> dict | None:
    try:
        d = json.loads(SENT.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:  # noqa: BLE001
        return None


def diff() -> None:
    cur = json.loads(STATE.read_text(encoding="utf-8"))
    prev = load_sent()
    changed = changed_paths(cur, prev)
    print(f"indexnow diff: 全{len(cur)}ページのうち、新しい・変わった {len(changed)}ページ" + ("（知らせた記録が無いので全部）" if prev is None else ""))
    LIST.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")


def post(urls: list[str], key: str) -> int:
    body = json.dumps({"host": HOST, "key": key, "keyLocation": f"https://{HOST}/{key}.txt", "urlList": urls}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def send() -> int:
    """送れたら 0。送る一覧が無い・送信に失敗したときは 1（状態を進めない）。"""
    if not LIST.exists():
        print("indexnow send: 送る一覧が無い（diff が動いていない）")
        return 1
    paths = json.loads(LIST.read_text(encoding="utf-8"))
    out = os.environ.get("GITHUB_OUTPUT")
    if paths:
        key = (HERE / "indexnow_key.txt").read_text().strip()
        urls = [f"https://{HOST}{p}" for p in paths]
        for i in range(0, len(urls), MAX_PER_POST):
            part = urls[i:i + MAX_PER_POST]
            try:
                print("indexnow send:", post(part, key), len(part))
            except Exception as e:  # noqa: BLE001
                print("indexnow error", e, file=sys.stderr)
                return 1  # 状態を進めない（次の回がもう一度送る）
    else:
        print("indexnow send: 0")
    if paths or not SENT.exists():
        SENT.parent.mkdir(parents=True, exist_ok=True)
        SENT.write_text(STATE.read_text(encoding="utf-8"), encoding="utf-8")
        if out:  # 状態が進んだときだけ cache に保存する（pages.yml）
            with open(out, "a", encoding="utf-8") as f:
                f.write("saved=1\n")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "diff":
        diff()
    elif cmd == "send":
        sys.exit(send())
    else:
        print("usage: indexnow.py diff|send")
