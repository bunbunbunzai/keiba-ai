"""JRA公式サイト（www.jra.go.jp）の取得。

JRAのデータページは `doAction('/JRADB/accessX.html', 'CNAME')` 形式の
フォーム送信（POST cname=...）で開く。CNAMEには検査用の文字が含まれるため、
URLを組み立てずに、上位ページのリンクからたどって収集する。

第1段階（discover）：開催日の出馬表・オッズ・結果ページを生HTMLで保存し、
実際のHTML構造を確認してから解析器（parse_*）を仕上げる。
"""
from __future__ import annotations

import argparse
import re
from datetime import date as Date

from bs4 import BeautifulSoup

from common import PoliteSession, save_json, save_raw

BASE = "https://www.jra.go.jp"
ACTION_RE = re.compile(r"doAction\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)")

# 入口：トップの「出馬表」「オッズ」「レース結果」メニューに相当するページ
ENTRY = {
    "card": ("/JRADB/accessD.html", "pw01dli00/F3"),
    "odds": ("/JRADB/accessO.html", "pw15oli00/6D"),
    "result": ("/JRADB/accessS.html", "pw01sli00/AF"),
}


def actions(html: str) -> list[tuple[str, str, str]]:
    """ページ内の doAction(...) を (path, cname, リンク文字) で列挙。"""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all(["a", "button", "input"]):
        js = (a.get("onclick") or "") + " " + (a.get("href") or "")
        m = ACTION_RE.search(js)
        if m:
            out.append((m.group(1), m.group(2), a.get_text(" ", strip=True)))
    for m in ACTION_RE.finditer(html):  # script内に直書きされたもの
        t = (m.group(1), m.group(2), "")
        if all(t[1] != o[1] for o in out):
            out.append(t)
    return out


def open_action(sess: PoliteSession, path: str, cname: str) -> str:
    return sess.post(BASE + path, data={"cname": cname}).text


def discover(target: str, kinds: list[str], max_pages: int = 400) -> dict:
    """target=YYYYMMDD の開催について、入口から2〜3階層たどって生HTMLを保存する。"""
    sess = PoliteSession(min_interval=3.0, encoding="shift_jis")
    log = {"date": target, "pages": []}
    seen: set[str] = set()
    # 入口はトップページのメニューから拾う（拾えなければ既知の値を使う）
    top = sess.get(BASE + "/").text
    save_raw("jra_top", target, "top", top)
    prefix = {"card": "pw01dli", "odds": "pw15oli", "result": "pw01sli"}
    found = {}
    for p, c, _ in actions(top):
        for k, pre in prefix.items():
            if c.startswith(pre) and k not in found:
                found[k] = (p, c)
    log["entry"] = {k: v[1] for k, v in found.items()}
    for kind in kinds:
        path, cname = found.get(kind, ENTRY[kind])
        queue = [(path, cname, f"{kind}_entry", 0)]
        while queue and len(log["pages"]) < max_pages:
            path, cname, label, depth = queue.pop(0)
            if cname in seen:
                continue
            seen.add(cname)
            try:
                html = open_action(sess, path, cname)
            except Exception as e:  # noqa: BLE001
                log["pages"].append({"kind": kind, "cname": cname, "error": str(e)})
                continue
            fname = re.sub(r"[^0-9A-Za-z_]", "_", cname)
            save_raw(f"jra_{kind}", target, fname, html)
            log["pages"].append({"kind": kind, "cname": cname, "label": label, "depth": depth})
            if depth >= 3:
                continue
            for p2, c2, text in actions(html):
                # 対象日の開催（CNAME内に日付）か、開催一覧の階層だけをたどる
                if target in c2 or depth == 0:
                    queue.append((p2, c2, text, depth + 1))
    save_json(f"raw/{target}/jra_discover_log.json", log)
    return log


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=Date.today().strftime("%Y%m%d"))
    ap.add_argument("--kinds", default="card,odds,result")
    ap.add_argument("--max-pages", type=int, default=400)
    a = ap.parse_args()
    lg = discover(a.date, a.kinds.split(","), a.max_pages)
    ok = sum(1 for p in lg["pages"] if "error" not in p)
    print(f"JRA {a.date}: saved {ok} pages, errors {len(lg['pages']) - ok}")
