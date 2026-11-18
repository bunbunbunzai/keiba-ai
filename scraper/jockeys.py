"""地方競馬の騎手の正式な氏名を集める（楽天競馬の騎手ページ）。

出馬表の騎手名は3文字の略称（「佐々志」など）なので、出馬表のリンクにある騎手の番号から騎手ページを開き、氏名を1回だけ読んで
data/jockeys.json に貯める：{"by_id": {"31352": {"abbr": "中山遥", "name": "中山遥人"}}}。一度読んだ騎手は読み直さない。

robots.txt の Crawl-delay: 60 を守る（1ページ/60秒）。夜間の過去成績の取得（history.yml の地方の回）と同じジョブの中で、
その前に続けて動かす（同時に2つ動かして間隔を詰めない）。
氏名は、ページの題名・見出しから「略称の文字をこの順に含み、同じ文字で始まる、略称より長い名前」を探す。見つからなければ入れない。
"""
from __future__ import annotations

import argparse
import json
import re
import time

from bs4 import BeautifulSoup

from common import DATA_DIR, PoliteSession

BASE = "https://keiba.rakuten.co.jp"
OUT = DATA_DIR / "jockeys.json"
MARKS = re.compile(r"[\s\u3000☆★▲△◇◆]")
LINK = re.compile(r'JOCKEYID/(\d+)"[^>]*>([^<]+)</a>')
NAME_ONLY = re.compile(r"[一-龥々ヶァ-ヴー]{3,10}")


def seen_ids() -> dict[str, str]:
    """保存してある出馬表（直近の分）から {騎手の番号: 略称}。"""
    ids: dict[str, str] = {}
    for f in sorted((DATA_DIR / "raw").glob("*/rakuten_card/*.html")):
        for jid, ab in LINK.findall(f.read_text(encoding="utf-8", errors="ignore")):
            ab = MARKS.sub("", ab)
            if ab:
                ids[jid] = ab
    return ids


def is_full(abbr: str, cand: str) -> bool:
    c = MARKS.sub("", cand)
    if len(c) <= len(abbr) or c[0] != abbr[0] or len(c) > 10:
        return False
    i = 0
    for ch in c:
        if i < len(abbr) and ch == abbr[i]:
            i += 1
    return i == len(abbr)


def full_name(html: str, abbr: str) -> str | None:
    s = BeautifulSoup(html, "html.parser")
    texts = [el.get_text(" ", strip=True) for el in s.find_all(["title", "h1", "h2", "h3", "dt", "dd", "th", "td", "p", "span"])][:400]
    cands: dict[str, int] = {}
    for rank, t in enumerate(texts):
        toks = [re.sub(r"(騎手|選手)$", "", x) for x in re.split(r"[\s\u3000（）()｜|/・,、:：\[\]【】]+", t) if x]
        for k, tok in enumerate(toks):
            for c in (tok, tok + toks[k + 1] if k + 1 < len(toks) else ""):  # 「佐々木 志音」のように姓と名が分かれている場合
                if c and NAME_ONLY.fullmatch(c) and is_full(abbr, c):
                    cands.setdefault(c, rank)
    if not cands:
        return None
    # 題名・見出しに近いもの、同じなら短いもの（余分な語が付いていないもの）
    return sorted(cands, key=lambda k: (cands[k], len(k)))[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-minutes", type=float, default=45)
    ap.add_argument("--limit", type=int, default=1000)
    a = ap.parse_args()
    data = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"by_id": {}}
    by_id = data.setdefault("by_id", {})
    ids = seen_ids()
    todo = [(j, ab) for j, ab in sorted(ids.items()) if j not in by_id]
    print(f"騎手 {len(ids)}人（保存済み {len(by_id)}人、これから読む {len(todo)}人）", flush=True)
    sess = PoliteSession(60)
    t0, n, miss = time.monotonic(), 0, 0
    for jid, ab in todo[: a.limit]:
        if (time.monotonic() - t0) / 60 > a.max_minutes:
            break
        try:
            html = sess.get(f"{BASE}/jockey/detail/JOCKEYID/{jid}").text
        except Exception as e:  # noqa: BLE001
            print("fetch error", jid, repr(e)[:120], flush=True)
            continue
        name = full_name(html, ab)
        by_id[jid] = {"abbr": ab, "name": name}   # 読めなかった騎手も記録して、毎晩読み直さない（name が無い間は略称のまま表示）
        n += 1
        miss += 0 if name else 1
        print(jid, ab, "→", name, flush=True)
        if n % 10 == 0:
            OUT.write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    print(f"読んだ {n}人（氏名が読めなかった {miss}人）", flush=True)


if __name__ == "__main__":
    main()
