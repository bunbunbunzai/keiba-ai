"""サイトの組み立て（site/build.py）で使う、小さくて単体で確かめられる関数。

ほかのモジュールを読み込まない（テストから軽く呼べるように）。テストは tests/test_sitekit.py。
"""
from __future__ import annotations

import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape


def tidy_race_name(name) -> str:
    """表示用のレース名。全角英数を半角にし、同じ語が続くところは1つにする（園田の「Ｃ２二 Ｃ２二 ３歳以上」など）。
    区分として付いているだけの「重賞」も外す（格付けは名前の中のかっこに入っている）。"""
    out: list[str] = []
    for t in unicodedata.normalize("NFKC", str(name or "")).split():
        if not out or out[-1] != t:
            out.append(t)
    if len(out) > 1:
        out = [t for t in out if t != "重賞"] or out
    return " ".join(out)


# ---- Google にだけ載せない設定（page() の noindex="google"）にしたページの一覧 ----
# Google は「載せない」設定を、そのページをもう一度見に来たときに初めて知る。見に来るのが遅いページが多いので
# （設定から3〜6日たった 2026-11-26 の時点で、反映されたのは約12,600ページのうち22ページ）、
# 設定が変わったページの一覧（/sitemap-noindex.xml）を作り、Search Console の「サイトマップ」から送って見直しを促す。
NOINDEX_SINCE = "2026-11-23"   # 馬・騎手・重賞データ記事を載せない設定にした日（騎手とデータ記事は 11-20 から。遅いほうにそろえる）
NOINDEX_SITEMAP_DAYS = 90      # 設定が変わってからこの日数だけ一覧に載せる（Google が見直すのに十分な時間がたったら外す）


def hidden_since(race_date: str, days: int, policy_start: str) -> str:
    """レースのページが Google に載せない設定へ変わった日（YYYY-MM-DD）。
    レースの日（YYYYMMDD）から days 日たった日。決まりを入れた日（policy_start）より前に終わっていたレースは、その日。"""
    d = (datetime.strptime(race_date, "%Y%m%d") + timedelta(days=days)).strftime("%Y-%m-%d")
    return max(d, policy_start)


def noindex_sitemap(pages: dict[str, str], base_url: str, today_iso: str, days: int = NOINDEX_SITEMAP_DAYS) -> str:
    """Google にだけ載せない設定へ変わったページの一覧（サイトマップの形）。更新日は、設定が変わった日。
    pages：パス → 設定が変わった日（YYYY-MM-DD）。空（""）は、生まれたときから載せない設定のページ
    （Google に載っていないので、見直しを頼む意味が無い）で、一覧に入れない。変わってから days 日を過ぎたページも外す。"""
    oldest = (datetime.strptime(today_iso, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = [f"<url><loc>{escape(base_url + p)}</loc><lastmod>{d}</lastmod></url>"
            for p, d in sorted(pages.items()) if d and d >= oldest]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(rows) + "</urlset>\n")


def result_badge(stake: int, ret: int, roi: str) -> tuple[str, str]:
    """レースの結果の一言。（CSSのクラス名, 文言）を返す。
    払戻が購入額と同じときは「元返し」。当日の自動更新が .res.hit を結果の印に使うので、クラスには hit を残す。"""
    if not ret:
        return "miss", f"不的中 −{stake:,}円"
    if ret < stake:
        return "tg", f"的中 {ret - stake:+,}円（トリガミ）"
    if ret == stake:
        return "hit even", "的中・元返し ±0円"
    return "hit", f"的中 {ret - stake:+,}円・{roi}"


def column_feed(cols: list[dict], limit: int = 15) -> list[tuple[str, str, str]]:
    """RSS に載せるコラム。（パス, 題名, 日付 YYYY-MM-DD）を新しい順に。下書きと日付の無いものは除く。"""
    out = [(f"/column/{c['slug']}/", c["title"], c.get("updated") or c.get("date") or "")
           for c in cols if not c.get("draft")]
    out = [x for x in out if x[2]]
    out.sort(key=lambda x: (x[2], x[0]), reverse=True)
    return out[:limit]


def dir_stats(root: Path) -> dict:
    """フォルダの中身の合計サイズ（バイト）とファイル数。"""
    files = [f for f in Path(root).rglob("*") if f.is_file()]
    return {"bytes": sum(f.stat().st_size for f in files), "files": len(files)}


def favorite_baseline(rows: Iterable[dict]) -> dict:
    """「直前の1番人気をそのまま買った場合」と、サイトの買い目を同じレースで比べる。
    rows の各要素：pop（馬番→人気）、payouts（結果の払戻）、stake・ret（サイトの買い目の購入額と払戻）、honmei（◎の馬番）、jra（中央か）。
    人気が無いレースと、複勝の払戻がまだ無いレースは数えない。
    戻り値：{"all" | "jra" | "nar": {"n", "fuku", "tan", "site", "same"}}（回収率は%、0件の区分は入れない）。"""
    acc: dict[str, dict] = {}
    for r in rows:
        fav = next((str(k) for k, v in (r.get("pop") or {}).items() if v == 1), None)
        pay = r.get("payouts") or {}
        if fav is None or not pay.get("複勝"):
            continue
        fuku = sum(x["yen"] for x in pay.get("複勝", []) if str(x["combo"]) == fav)
        tan = sum(x["yen"] for x in pay.get("単勝", []) if str(x["combo"]) == fav)
        for key in ("all", "jra" if r.get("jra") else "nar"):
            a = acc.setdefault(key, {"n": 0, "fuku": 0, "tan": 0, "stake": 0, "ret": 0, "same": 0})
            a["n"] += 1
            a["fuku"] += fuku
            a["tan"] += tan
            a["stake"] += int(r.get("stake") or 0)
            a["ret"] += int(r.get("ret") or 0)
            a["same"] += str(r.get("honmei")) == fav
    return {k: {"n": a["n"], "fuku": round(a["fuku"] / a["n"], 1), "tan": round(a["tan"] / a["n"], 1),
                "site": round(a["ret"] / a["stake"] * 100, 1) if a["stake"] else 0.0, "same": a["same"]}
            for k, a in acc.items()}
