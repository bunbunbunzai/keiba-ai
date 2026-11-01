"""IndexNow：更新したページを Bing などの検索エンジンにすぐ知らせる（ChatGPT検索は Bing の索引を多く使う）。

pages のデプロイ後に実行。サイトマップのうち lastmod が今日（または昨日）のURLを送る。
鍵は公開してよいもの（サイト直下の <key>.txt で所有を証明する仕組み）。
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOST = "www.ai-keiba-log.com"


def main() -> None:
    jst0 = timezone(timedelta(hours=9))
    if "--force" not in sys.argv and datetime.now(jst0).minute >= 10:
        print("skip（送信は1時間に1回程度にとどめる）")
        return
    key = (HERE / "indexnow_key.txt").read_text().strip()
    sm = (HERE.parent / "_site" / "sitemap.xml").read_text(encoding="utf-8")
    jst = timezone(timedelta(hours=9))
    days = {(datetime.now(jst) - timedelta(days=i)).strftime("%Y-%m-%d") for i in (0, 1)}
    urls = [u for u, m in re.findall(r"<loc>([^<]+)</loc><lastmod>([^<]+)</lastmod>", sm) if m in days][:1000]
    urls = [f"https://{HOST}/"] + [u for u in urls if u != f"https://{HOST}/"]
    body = json.dumps({"host": HOST, "key": key, "keyLocation": f"https://{HOST}/{key}.txt", "urlList": urls}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("indexnow", r.status, len(urls))
    except Exception as e:  # noqa: BLE001
        print("indexnow error", e, file=sys.stderr)


if __name__ == "__main__":
    main()
