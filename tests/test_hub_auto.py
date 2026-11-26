"""G1以外の重賞の特集まとめ（scraper/g1_hub_cols.py の auto_cfgs・auto_hero・build_next）のテスト。

リポジトリの重賞の全着順（data/graded_hist）を読む。日付は引数で固定する。

実行: python -m pytest tests/test_hub_auto.py -q  または  python tests/test_hub_auto.py
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))

import g1_hub_cols as H  # noqa: E402
import graded_cols as G  # noqa: E402

sys.path.insert(0, str(ROOT / "site"))
import column  # noqa: E402
import weekly  # noqa: E402

_KA = {}


def data():
    """(all_, K)。重賞の全着順を一度だけ読む。"""
    if not _KA:
        with contextlib.redirect_stdout(io.StringIO()):
            all_ = G.load_all()
            G._init_names()
            _KA.update(all_=all_, K=G.keyed(all_))
    return _KA["all_"], _KA["K"]


def slugs(today, cols=None):
    _, K = data()
    return [c["slug"] for c in (H.auto_cfgs(K, today, cols) if cols is not None else H.auto_cfgs(K, today))]


def cfg_of(slug, today):
    _, K = data()
    return next(c for c in H.auto_cfgs(K, today) if c["slug"] == slug)


def test_window_and_grades():
    _, K = data()
    cs = H.auto_cfgs(K, "2026-11-26")
    got = [c["slug"] for c in cs]
    for s in ("stayers-stakes", "keihan-hai", "hanshin-cup"):
        assert s in got, s
    for s in ("japan-cup", "arima-kinen", "fairy-stakes"):
        assert s not in got, f"{s}（G1か、35日より先）を作ろうとしている"
    assert all(c["auto"] is True and c["ahead"] == H.HUB_DAYS and c["keep"] == H.HUB_KEEP for c in cs)
    st = next(c for c in cs if c["slug"] == "stayers-stakes")
    assert st["series"] == "stayers-stakes2026"
    dates = [K[c["slug"]][int(c["series"][-4:])]["date"] for c in cs]
    assert dates == sorted(dates), "レースの日付の順"


def test_skips_manual_guide():
    got = slugs("2026-12-20")
    assert "nakayama-kimpai" not in got and "kyoto-kimpai" not in got, "手で作った特集まとめがあるレースは作らない"
    with tempfile.TemporaryDirectory() as d:
        got = slugs("2026-12-20", Path(d))
    assert "nakayama-kimpai" in got and "kyoto-kimpai" in got


def test_keeps_updating_own_auto_guide():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "stayers-stakes2026-guide.md").write_text("---\ntitle: x\nhub: auto\nrace: stayers-stakes\n---\n本文\n", encoding="utf-8")
        assert "stayers-stakes" in slugs("2026-11-26", Path(d)), "自動で作った記事は、作り直しの対象のまま"


def test_skips_short_history():
    assert "kokura-himba-stakes" not in slugs("2027-01-10"), "過去の開催が8回未満のレースは作らない"


def test_keep_after_race():
    assert "stayers-stakes" in slugs("2026-12-10"), "レースの5日後は、結果を入れるために作り直す"
    assert "stayers-stakes" not in slugs("2026-12-25"), "レースの20日後は、もう触らない"


def test_skips_unnamed_race():
    _, K = data()
    assert any(s.startswith("abbr:") for s in K), "一覧の略称で束ねたレース（abbr:〇〇）がデータにある前提"
    K2 = {"abbr:ステイヤーズS": K["stayers-stakes"]}  # 正式名が決まらず略称で束ねられた、という形を作る
    with tempfile.TemporaryDirectory() as d:
        assert H.auto_cfgs(K2, "2026-11-26", Path(d)) == [], "URLにできない名前のレースは作らない"


def test_auto_hero():
    assert H.auto_hero({"surface": "障", "distance": 3570, "date": "20261219"}) == "g-jump"
    assert H.auto_hero({"surface": "ダ", "distance": 1200, "date": "20261213"}) == "g-dirt-day"
    assert H.auto_hero({"surface": "芝", "distance": 1200, "date": "20261129"}) == "g-sprint"
    assert H.auto_hero({"surface": "芝", "distance": 3600, "date": "20261205"}) == "g-stayer"
    assert H.auto_hero({"surface": "芝", "distance": 2000, "date": "20270104"}) == "g-turf-winter"
    assert H.auto_hero({"surface": "芝", "distance": 1800, "date": "20270515"}) == "g-turf-spring"
    assert H.auto_hero({"surface": "芝", "distance": 2000, "date": "20270718"}) == "g-turf-summer"
    assert H.auto_hero({"surface": "芝", "distance": 2000, "date": "20261003"}) == "g-turf-autumn"
    for h in {H.auto_hero(r) for r in ({"surface": s, "distance": dd, "date": d} for s in "芝ダ障" for dd in (1000, 2000, 3600)
                                       for d in ("20260101", "20260401", "20260701", "20261001"))}:
        assert (ROOT / "site" / "assets" / f"{h}.jpg").exists(), h


def test_build_auto():
    all_, K = data()
    gslug, title, desc, lead, body, extra = H.build_next(cfg_of("stayers-stakes", "2026-11-26"), all_, K, "2026-11-26")
    assert gslug == "stayers-stakes2026-guide"
    assert title == "ステイヤーズステークス2026はいつ？日程と過去10年の傾向【特集まとめ】"
    assert "前哨戦" not in title and "前哨戦" not in desc
    for h in ("## レースの基本情報", "## 2025年の結果", "## 過去10年の勝ち馬", "## 特集の記事", "## 出典"):
        assert h in body, h
    assert "/column/g1-nittei-2027/" not in body, "G1の日程の一覧へは案内しない"
    assert "(/weekend/)" in body, "今週末の重賞まとめへ案内する"
    assert "(/graded/stayers-stakes/)" in body, "レースガイドがあるレースは、重賞のページへ案内する"
    assert extra["hub"] == "auto" and extra["race"] == "stayers-stakes" and extra["race_date"] == "20261205"
    assert "None" not in body + lead + desc and "レースだ。" not in lead
    assert lead.startswith("第60回ステイヤーズステークスは2026年12月5日（土）、中山競馬場の芝3600mで行われる。")


def test_build_auto_without_race_guide():
    all_, K = data()
    gslug, title, desc, lead, body, extra = H.build_next(cfg_of("keihan-hai", "2026-11-26"), all_, K, "2026-11-26")
    assert title.startswith("京阪杯2026はいつ？")
    assert "/graded/keihan-hai/" not in body, "重賞のページ（レースガイド）が無いレースには、そのページへのリンクを張らない"
    assert "レースガイド" not in body.split("## 出典")[1], "出典に、使っていないレースガイドを書かない"
    assert "- 場所：京都競馬場の芝1200m\n" in body
    gslug, title, *_ = H.build_next(cfg_of("kyoto-2yo-stakes", "2026-11-26"), all_, K, "2026-11-26")
    assert title.startswith("京都2歳ステークス2026はいつ？"), "略称（京都2歳S）でなく正式な名前"


def test_cond_jp():
    assert H.cond_jp("3歳以上牝") == "3歳以上の牝馬"
    assert H.cond_jp("3歳牝") == "3歳の牝馬"
    assert H.cond_jp("4歳以上") == "4歳以上" and H.cond_jp("") == ""


def test_build_auto_after_keep_window():
    all_, K = data()
    cfg = dict(cfg_of("stayers-stakes", "2026-11-26"))
    assert H.build_next(cfg, all_, K, "2026-12-25") is None, "作り直しの期間（レースの14日後まで）を過ぎたら作らない"


def test_next_unchanged():
    all_, K = data()
    feb = next(c for c in H.NEXT if c["series"] == "feb2027")
    out = H.build_next(feb, all_, K, "2026-11-26")
    assert out and "前哨戦" in out[1] and "hub" not in out[5], "手で設定した来年の特集まとめは、これまでどおり"
    assert "/column/g1-nittei-2027/" in out[4]



# ---------- サイト側（site/column.py・site/weekly.py） ----------
@contextlib.contextmanager
def site_state():
    """登録した自動の特集まとめと weekly の状態を、テストのあとで元に戻す。"""
    saved = dict(fr=dict(weekly.FEATURE_RACE), ids=column.FEATURE_IDS, grp=dict(column.FEATURE_GROUP),
                 auto=set(weekly.AUTO_HUBS), K=weekly._K, feat=dict(weekly.FEAT), today=weekly.TODAY)
    try:
        yield
    finally:
        weekly.FEATURE_RACE.clear()
        weekly.FEATURE_RACE.update(saved["fr"])
        column.FEATURE_IDS = saved["ids"]
        column.FEATURE_GROUP.clear()
        column.FEATURE_GROUP.update(saved["grp"])
        weekly.AUTO_HUBS.clear()
        weekly.AUTO_HUBS.update(saved["auto"])
        weekly._K, weekly.TODAY = saved["K"], saved["today"]
        weekly.FEAT.clear()
        weekly.FEAT.update(saved["feat"])


def auto_col(race, year="2026", date="20261205", **over):
    c = {"slug": f"{race}{year}-guide", "series": f"{race}{year}", "hub": "auto", "race": race, "race_date": date,
         "race_grade": "G3", "draft": False, "order": 1, "title": race}
    c.update(over)
    return c


def test_register_auto_hubs():
    with site_state():
        got = column.register_auto_hubs([auto_col("x"), {"slug": "y", "series": "y2026", "draft": False},
                                         auto_col("z", draft=True)])
        assert got == ("x2026",)
        assert weekly.FEATURE_RACE["x2026"] == "x" and "x2026" in column.FEATURE_IDS and "x2026" in weekly.AUTO_HUBS
        assert "y2026" not in column.FEATURE_IDS and "z2026" not in column.FEATURE_IDS, "自動でない記事・下書きは登録しない"
        assert column.FEATURE_GROUP["jusho"] == ("x2026",)
        assert "jc2026" in column.FEATURE_IDS and weekly.FEATURE_RACE["jc2026"] == "japan-cup", "手で作った特集はそのまま"
        assert column.register_auto_hubs([auto_col("w")]) == ("w2026",)
        assert "x2026" not in weekly.FEATURE_RACE and "x2026" not in column.FEATURE_IDS, "何度呼んでも、最後に渡した分だけ"
        assert column.FEATURE_IDS.count("w2026") == 1
    assert "w2026" not in weekly.FEATURE_RACE


def test_register_never_overrides_manual_series():
    with site_state():
        got = column.register_auto_hubs([auto_col("nakayama-kimpai", series="nkimpai2027")])
        assert got == () and weekly.FEATURE_RACE["nkimpai2027"] == "nakayama-kimpai", "手で設定した特集の名前と重なったら登録しない"


def test_hidden_hub():
    assert column._hidden_hub({"hub": "auto", "race_grade": "G3"}) is True
    assert column._hidden_hub({"hub": "auto", "race_grade": "J・G2"}) is True
    assert column._hidden_hub({"hub": "auto", "race_grade": "G1"}) is False
    assert column._hidden_hub({"race_grade": "G3"}) is False, "手で作った特集まとめ（金杯など）は隠さない"


def test_feature_rel_for_g1_page():
    jc = {"slug": "jc2026-guide", "series": "jc2026", "order": 1, "race_date": "20261129", "draft": False}
    jc2 = {"slug": "jc2026-waku", "series": "jc2026", "order": 2, "draft": False}
    arima = {"slug": "arima2026-guide", "series": "arima2026", "order": 1, "race_date": "20261227", "draft": False}
    st, ch, old = auto_col("stayers-stakes", date="20261205"), auto_col("capella-stakes", date="20261213"), auto_col("musashino-stakes", date="20261114")
    with site_state():
        weekly._K = {}
        column.register_auto_hubs([st, ch, old])
        rel = dict(column._feature_rel(jc, [jc, jc2, arima, st, ch, old], "20261126"))
    assert [o["slug"] for o in rel["この特集のほかの記事"]] == ["jc2026-waku"]
    assert [o["slug"] for o in rel["ほかの特集"]] == ["arima2026-guide"], "G2・G3の特集まとめで、G1の特集が押し出されない"
    assert [o["slug"] for o in rel["近く行われる重賞（G2・G3）の特集まとめ"]] == ["stayers-stakes2026-guide", "capella-stakes2026-guide"], \
        "これから行われるレースを日付順に（終わったレースは出さない）"


def test_feature_rel_for_auto_page():
    jc = {"slug": "jc2026-guide", "series": "jc2026", "order": 1, "race_date": "20261129", "draft": False}
    eliza = {"slug": "eliza2026-guide", "series": "eliza2026", "order": 1, "race_date": "20261115", "draft": False}
    aki = {"slug": "aki-g1-2026", "series": "aki2026", "order": 1, "draft": False}
    st, ch = auto_col("stayers-stakes", date="20261205", race_name="ステイヤーズステークス"), auto_col("capella-stakes", date="20261213")
    data2, data1 = ({"slug": f"stayers-stakes-{k}", "series": "gdata", "race": "stayers-stakes", "order": n, "draft": False}
                    for k, n in (("jinx", 4), ("kako-kekka", 1)))
    other_data = {"slug": "capella-stakes-jinx", "series": "gdata", "race": "capella-stakes", "order": 1, "draft": False}
    with site_state():
        weekly._K = {}
        column.register_auto_hubs([st, ch])
        rel = column._feature_rel(st, [jc, eliza, aki, st, ch, data2, data1, other_data], "20261126")
    heads = [h for h, _ in rel]
    assert heads == ["ステイヤーズステークスのデータ記事", "近く行われるG1の特集まとめ", "ほかの重賞（G2・G3）の特集まとめ"]
    d = dict(rel)
    assert [o["slug"] for o in d["ステイヤーズステークスのデータ記事"]] == ["stayers-stakes-kako-kekka", "stayers-stakes-jinx"]
    assert [o["slug"] for o in d["近く行われるG1の特集まとめ"]] == ["jc2026-guide"], "終わったレース・日付の無い特集は出さない"
    assert [o["slug"] for o in d["ほかの重賞（G2・G3）の特集まとめ"]] == ["capella-stakes2026-guide"]


def test_next_hub_prefers_g1_from_g1_pages():
    with site_state():
        weekly._K = {"stayers-stakes": {2026: {"date": "20261205"}}, "champions-cup": {2026: {"date": "20261206"}}}
        weekly.TODAY = "20261130"
        column.register_auto_hubs([auto_col("stayers-stakes")])
        weekly.FEAT.clear()
        weekly.FEAT.update({"stayers-stakes": [{"slug": "stayers-stakes2026-guide", "series": "stayers-stakes2026"}],
                            "champions-cup": [{"slug": "champions-cup2026-guide", "series": "jcd2026"}]})
        assert weekly._next_hub("20261129")[0] == "champions-cup2026-guide", "G1の特集まとめの「次は」は、次のG1"
        assert weekly._next_hub("20261129", auto=True)[0] == "stayers-stakes2026-guide", "G2・G3の特集まとめからは、いちばん近いレース"


def test_sched_name_expands_abbr():
    assert weekly._full_name("中山牝馬S") == "中山牝馬ステークス"
    assert weekly._full_name("阪神C") == "阪神カップ"
    assert weekly._full_name("京阪杯") == "京阪杯"


if __name__ == "__main__":
    for _k, _f in sorted(globals().items()):
        if _k.startswith("test_") and callable(_f):
            _f()
    print("OK: G1以外の重賞の特集まとめの検算 すべて一致")
