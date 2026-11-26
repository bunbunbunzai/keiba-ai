"""site/sitekit.py（サイトの組み立てで使う小さな関数）のテスト。

実行: python -m pytest tests/test_sitekit.py -q
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "site"))

import sitekit  # noqa: E402

BASE = "https://example.com"


# ---- レース名の整形 ----
def test_tidy_race_name_drops_repeated_word():
    assert sitekit.tidy_race_name("Ｃ２二 Ｃ２二 ３歳以上") == "C2二 3歳以上"


def test_tidy_race_name_drops_bare_jusho_word():
    assert sitekit.tidy_race_name("兵庫ジュニアグランプリ（Ｊｐｎ２） 重賞 ２歳登録馬") == "兵庫ジュニアグランプリ(Jpn2) 2歳登録馬"


def test_tidy_race_name_keeps_single_word():
    assert sitekit.tidy_race_name("重賞") == "重賞"


def test_tidy_race_name_keeps_numbered_jusho():
    # 「楠賞 重賞1」は重賞名を取り出す側（extra.clean_name）が扱うので、ここでは触らない
    assert sitekit.tidy_race_name("楠賞 重賞1") == "楠賞 重賞1"


def test_tidy_race_name_keeps_non_adjacent_repeat():
    assert sitekit.tidy_race_name("A B A") == "A B A"


def test_tidy_race_name_empty():
    assert sitekit.tidy_race_name("") == ""
    assert sitekit.tidy_race_name(None) == ""


# ---- Google にだけ載せないページのサイトマップ ----
TODAY = "2026-11-26"


def _urls(xml: str) -> list[tuple[str, str]]:
    return [(u[0].text, u[1].text) for u in ET.fromstring(xml)]


def test_hidden_since_is_race_date_plus_days():
    # 地方：レースの日から3日たった日に、Google に載せない設定へ変わる
    assert sitekit.hidden_since("20261125", 3, "2026-11-20") == "2026-11-28"


def test_hidden_since_not_before_policy_start():
    # 決まりを入れる前に終わっていたレースは、決まりを入れた日に変わった
    assert sitekit.hidden_since("20261030", 3, "2026-11-20") == "2026-11-20"


def test_hidden_since_crosses_month_end():
    assert sitekit.hidden_since("20261129", 7, "2026-11-23") == "2026-12-06"


def test_noindex_sitemap_lists_page_with_the_day_it_changed():
    xml = sitekit.noindex_sitemap({"/jockey/abc/": "2026-11-23"}, BASE, TODAY)
    assert "<url><loc>https://example.com/jockey/abc/</loc><lastmod>2026-11-23</lastmod></url>" in xml


def test_noindex_sitemap_skips_page_that_was_never_indexable():
    # 生まれたときから載せない設定のページは Google に載っていないので、見直しを頼まない
    assert _urls(sitekit.noindex_sitemap({"/horse/new/": ""}, BASE, TODAY)) == []


def test_noindex_sitemap_drops_page_after_window():
    xml = sitekit.noindex_sitemap({"/old/": "2026-08-27", "/edge/": "2026-08-28"}, BASE, TODAY, days=90)
    assert _urls(xml) == [("https://example.com/edge/", "2026-08-28")]


def test_noindex_sitemap_empty_is_valid_xml():
    root = ET.fromstring(sitekit.noindex_sitemap({}, BASE, TODAY))
    assert root.tag.endswith("urlset") and len(root) == 0


def test_noindex_sitemap_escapes_and_sorts():
    xml = sitekit.noindex_sitemap({"/b/?x=1&y=2": "2026-11-23", "/a/": "2026-11-24"}, BASE, TODAY)
    assert _urls(xml) == [("https://example.com/a/", "2026-11-24"), ("https://example.com/b/?x=1&y=2", "2026-11-23")]


# ---- レース結果の一言 ----
def test_result_badge_miss():
    assert sitekit.result_badge(100, 0, "0.0%") == ("miss", "不的中 −100円")


def test_result_badge_torigami():
    assert sitekit.result_badge(300, 190, "63.3%") == ("tg", "的中 -110円（トリガミ）")


def test_result_badge_even_keeps_hit_class():
    # 当日の自動更新は .res.hit / .res.miss / .res.tg を「結果が出た」印に使うので、hit を残す
    assert sitekit.result_badge(100, 100, "100.0%") == ("hit even", "的中・元返し ±0円")


def test_result_badge_hit():
    assert sitekit.result_badge(100, 190, "190.0%") == ("hit", "的中 +90円・190.0%")


# ---- コラムを RSS に載せる ----
def _col(slug, date, updated="", draft=False):
    return {"slug": slug, "title": slug.upper(), "date": date, "updated": updated, "draft": draft}


def test_column_feed_newest_first_skips_drafts_and_undated():
    cols = [_col("a", "2026-11-01"), _col("b", "2026-11-10", "2026-11-20"), _col("c", "2026-11-25", draft=True), _col("d", "")]
    assert sitekit.column_feed(cols) == [("/column/b/", "B", "2026-11-20"), ("/column/a/", "A", "2026-11-01")]


def test_column_feed_limit():
    cols = [_col(f"s{i}", f"2026-11-{i:02d}") for i in range(1, 21)]
    out = sitekit.column_feed(cols, limit=5)
    assert [p for p, _, _ in out] == ["/column/s20/", "/column/s19/", "/column/s18/", "/column/s17/", "/column/s16/"]


# ---- 公開サイトの大きさ ----
def test_dir_stats_counts_bytes_and_files(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.txt").write_bytes(b"12345")
    (tmp_path / "y.txt").write_bytes(b"1")
    assert sitekit.dir_stats(tmp_path) == {"bytes": 6, "files": 2}


# ---- 1番人気を買うだけの場合との比較 ----
def _row(pop, fuku, tan, stake, ret, honmei, jra=False):
    return {"pop": pop, "stake": stake, "ret": ret, "honmei": honmei, "jra": jra,
            "payouts": {"複勝": [{"combo": k, "yen": v} for k, v in fuku.items()],
                        "単勝": [{"combo": k, "yen": v} for k, v in tan.items()]}}


def test_favorite_baseline_totals_and_split():
    rows = [_row({"1": 1, "2": 2}, {"1": 110, "2": 150}, {"1": 180}, 100, 110, "1"),
            _row({"3": 1, "4": 2}, {"4": 300}, {"4": 900}, 100, 0, "4", jra=True)]
    b = sitekit.favorite_baseline(rows)
    assert b["all"] == {"n": 2, "fuku": 55.0, "tan": 90.0, "site": 55.0, "same": 1}
    assert b["nar"] == {"n": 1, "fuku": 110.0, "tan": 180.0, "site": 110.0, "same": 1}
    assert b["jra"] == {"n": 1, "fuku": 0.0, "tan": 0.0, "site": 0.0, "same": 0}


def test_favorite_baseline_accepts_numeric_keys():
    rows = [{"pop": {1: 1, 2: 2}, "stake": 100, "ret": 0, "honmei": 2, "jra": False,
             "payouts": {"複勝": [{"combo": 1, "yen": 120}], "単勝": [{"combo": "1", "yen": 250}]}}]
    assert sitekit.favorite_baseline(rows)["all"] == {"n": 1, "fuku": 120.0, "tan": 250.0, "site": 0.0, "same": 0}


def test_favorite_baseline_skips_rows_without_popularity_or_payout():
    rows = [_row({}, {"1": 110}, {"1": 180}, 100, 110, "1"),
            {"pop": {"1": 1}, "stake": 100, "ret": 0, "honmei": "1", "jra": False, "payouts": {}}]
    assert sitekit.favorite_baseline(rows) == {}
