"""特集まとめの「よくある質問」（site/hubfaq.py）のテスト。

曜日・発走時刻・年・中央か地方かで、答えが正しく変わること（確かめていない時刻や番組を書かないこと）を見る。

実行: python -m pytest tests/test_hub_faq.py -q  または  python tests/test_hub_faq.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "site"))

import hubfaq  # noqa: E402


def jc(**over):
    """2026年のジャパンカップ（11月29日・日曜・東京芝2400m）。11月26日に見た状態。"""
    info = {"slug": "japan-cup", "name": "ジャパンカップ", "year": "2026", "date": "20261129", "venue": "東京", "course": "芝2400m",
            "grade": "G1", "jra": True, "post": "15:40", "post_fixed": False, "phase": None, "pred_path": "",
            "publish": "11月27日（金）の昼〜11月28日（土）の夜に公開予定", "today": "20261126", "graded_page": True}
    info.update(over)
    return info


def tdt(**over):
    """2026年の東京大賞典（12月29日・火曜・大井ダート2000m）。地方のレース。"""
    return jc(slug="tokyo-daishoten", name="東京大賞典", date="20261229", venue="大井", course="ダート2000m", jra=False, post="",
              publish="", **over)


def answers(info):
    return [x["a"] for x in hubfaq.faq_items(info)]


def by_q(info, word):
    """質問に word を含む項目の答え。"""
    hit = [x for x in hubfaq.faq_items(info) if word in x["q"]]
    assert len(hit) == 1, f"「{word}」の質問が{len(hit)}個"
    return hit[0]["a"]


def test_jra_sunday_g1():
    items = hubfaq.faq_items(jc())
    assert len(items) == 6
    when = by_q(jc(), "何時から")
    for w in ("2026年11月29日（日）", "東京競馬場", "芝2400m", "15時40分", "予定"):
        assert w in when, w
    tv = by_q(jc(), "中継")
    assert "みんなのKEIBA" in tv and "無料" in tv
    assert "変わることがある" in tv, "放送時間の変更は、決まったことのようには書かない"
    money = by_q(jc(), "いくら")
    assert "100円" in money and "20歳" in money
    net = by_q(jc(), "ネットで")
    for w in ("即PAT", "金曜の18時30分", "1分前"):
        assert w in net, w


def test_post_fixed_wording():
    assert "予定" not in by_q(jc(post_fixed=True), "何時から")
    assert "15時40分" in by_q(jc(post_fixed=True), "何時から")


def test_no_post_time():
    when = by_q(jc(post=""), "何時から")
    assert not re.search(r"\d時\d", when), "時刻のデータが無いのに時刻を書いている"
    assert "出馬表" in when


def test_saturday_race():
    tv = by_q(jc(name="ホープフルステークス", slug="hopeful-stakes", date="20261226", venue="中山", course="芝2000m"), "中継")
    assert "ウイニング競馬" in tv and "みんなのKEIBA" not in tv


def test_weekday_race():
    tv = by_q(jc(name="中山金杯", slug="nakayama-kimpai", year="2027", date="20270104", venue="中山", course="芝2000m", grade="G3",
                 today="20261220", post=""), "中継")
    assert "ウイニング競馬" not in tv and "みんなのKEIBA" not in tv
    assert "土曜・日曜以外" in tv


def test_post_outside_tv_window():
    tv = by_q(jc(name="中山大障害", slug="nakayama-daishogai", date="20261226", venue="中山", course="障害4100m", grade="J・G1",
                 post="14:40", post_fixed=True), "中継")
    assert "14時40分" in tv and "放送時間" in tv and "入らない" in tv
    assert "入らない" not in by_q(jc(), "中継"), "15時40分発走は放送時間の中"


def test_sale_time_only_for_checked_year():
    net27 = by_q(jc(name="フェブラリーステークス", slug="february-stakes", year="2027", date="20270221", today="20270201"), "ネットで")
    assert "18時30分" not in net27 and "7時" not in net27, "確かめていない年の発売時刻を書いている"
    assert "1分前" in net27
    g3 = by_q(jc(name="京阪杯", slug="keihan-hai", grade="G3", venue="京都", course="芝1200m"), "ネットで")
    assert "土曜の7時" in g3 and "18時30分" not in g3
    sat = by_q(jc(name="ステイヤーズステークス", slug="stayers-stakes", grade="G2", date="20261205", venue="中山", course="芝3600m"), "ネットで")
    assert "金曜の18時30分" in sat


def test_tv_programs_only_for_checked_year():
    feb = jc(name="フェブラリーステークス", slug="february-stakes", year="2027", date="20270221", venue="東京", course="ダート1600m",
             today="20270201", post="")
    tv = by_q(feb, "中継")
    for w in ("みんなのKEIBA", "ウイニング競馬", "15時"):
        assert w not in tv, f"確かめていない年の番組名・放送時間を書いている（{w}）"
    assert hubfaq.SRC["tv"] in tv and "無料" in tv, "案内へのリンクと、ネットの無料中継は出す"
    jump = by_q(jc(name="中山グランドジャンプ", slug="nakayama-grand-jump", year="2027", date="20270417", venue="中山", course="障害4260m",
                   grade="J・G1", today="20270401", post="14:40", post_fixed=True), "中継")
    assert "ウイニング競馬" not in jump and "入らない" not in jump, "放送時間を確かめていない年は、発走時刻と比べない"


def test_local_race_prediction_day():
    ai = by_q(tdt(), "AI予想")
    assert "12月28日（月）の夜" in ai, "特集まとめの冒頭の箱と同じ日どり（前日の夜）"
    assert "当日" not in ai


def test_pred_published():
    ai = by_q(jc(phase="pred", pred_path="/2026/11/29/tokyo/12r/"), "AI予想")
    assert "(/2026/11/29/tokyo/12r/)" in ai and "公開中" in ai
    before = by_q(jc(), "AI予想")
    assert "11月27日（金）" in before and "(/graded/japan-cup/)" in before


def test_local_race():
    items = hubfaq.faq_items(tdt())
    text = "".join(x["a"] for x in items)
    for w in ("楽天競馬", "SPAT4", "地方競馬ライブ", "大井競馬場"):
        assert w in text, w
    assert [x["after"] for x in items].count("{{aff_nar}}") == 1, "楽天競馬のPRは1つだけ"
    net = by_q(tdt(), "ネットで")
    assert "即PAT" in net and "2025年" in net, "JRAのネット投票は、確かめた2025年の話として書く"
    assert "みんなのKEIBA" not in text and "金曜の18時30分" not in text
    assert not [x for x in items if "競馬場で見る" in x["q"]], "地方の入場の案内は確かめていないので出さない"
    assert all(x["after"] == "" for x in hubfaq.faq_items(jc())), "中央のレースにはPRを差し込まない"


def test_result_no_faq():
    info = jc(phase="result")
    assert hubfaq.faq_items(info) == [] and hubfaq.faq_md(info) == "" and hubfaq.faq_ld(info) is None


def test_past_race_no_faq():
    info = jc(today="20261130")  # レースの日を過ぎたが、結果がまだ入っていない
    assert hubfaq.faq_items(info) == [] and hubfaq.faq_md(info) == ""


def test_no_date_no_faq():
    for info in (None, {}, jc(date=""), jc(name=""), jc(date="2026")):
        assert hubfaq.faq_items(info) == [] and hubfaq.faq_md(info) == "" and hubfaq.faq_ld(info) is None


def test_md_and_ld():
    md = hubfaq.faq_md(jc())
    assert md.startswith("## ジャパンカップ2026のよくある質問\n")
    assert len(re.findall(r"^### ", md, re.M)) == 6
    assert "None" not in md
    ld = hubfaq.faq_ld(jc())
    assert ld["@type"] == "FAQPage" and len(ld["mainEntity"]) == 6
    for q in ld["mainEntity"]:
        t = q["acceptedAnswer"]["text"]
        assert q["@type"] == "Question" and q["name"] and t
        assert "](" not in t and "{{" not in t and "**" not in t, "検索エンジン向けの答えに記法が残っている"
    md_l = hubfaq.faq_md(tdt())
    assert "\n{{aff_nar}}\n" in md_l, "PRの差し込みは1行で独立させる（render がその行だけを置き換える）"
    assert "{{" not in "".join(q["acceptedAnswer"]["text"] for q in hubfaq.faq_ld(tdt())["mainEntity"])


def test_insert_md():
    faq = "## Q\n\n### q1\n\na1\n"
    body = "## レースの基本情報\n\n- a\n\n## 特集の記事\n\n- b\n\n## 出典\n\n- c\n"
    out = hubfaq.insert_md(body, faq)
    assert out.index("## Q") < out.index("## 特集の記事") and out.index("## レースの基本情報") < out.index("## Q")
    out2 = hubfaq.insert_md("## A\n\nx\n\n## 出典\n\n- c\n", faq)
    assert out2.index("## A") < out2.index("## Q") < out2.index("## 出典")
    out3 = hubfaq.insert_md("## A\n\nx\n", faq)
    assert out3.index("## A") < out3.index("## Q") and out3.rstrip().endswith("a1")
    assert hubfaq.insert_md(body, "") == body
    # 見出しの前後に空行が入り、前の段落や表にくっつかない
    assert "\n\n## Q\n" in out and "a1\n\n## 特集の記事" in out


def test_post_hint():
    assert hubfaq.post_hint("- 日時：2026年11月29日（日）15:40発走予定") == "15:40"
    assert hubfaq.post_hint("- 日時：2026年12月6日（日）中京11R・15時40分発走予定") == "15:40"
    assert hubfaq.post_hint("受付は9時5分から") == ""
    assert hubfaq.post_hint("") == ""


# ---------- 特集まとめへの差し込み（site/weekly.py の hub_info、site/column.py の _aff_for） ----------
import contextlib  # noqa: E402
import json  # noqa: E402
import tempfile  # noqa: E402
import types  # noqa: E402

import column  # noqa: E402
import weekly  # noqa: E402


def _load_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@contextlib.contextmanager
def weekly_state(today="20261126", K=None, preds=None, waku=None, guides=None):
    """weekly の状態（サイトを組み立てるときに prepare が入れるもの）を、テスト用の小さな中身に入れ替える。
    guides はレースガイド（data/race_guides/<slug>.json）の {slug: レース名}。"""
    names = ("_B", "TODAY", "_K", "SCHED_BY_SLUG", "PREDS", "WAKU", "ENTRIES", "NOMS")
    saved = {n: getattr(weekly, n) for n in names}
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "data" / "race_guides").mkdir(parents=True)
        for g, nm in (guides or {}).items():
            (root / "data" / "race_guides" / f"{g}.json").write_text(json.dumps({"slug": g, "name": nm}), encoding="utf-8")
        B = types.SimpleNamespace(ROOT=root, esc=str, load_json=_load_json,
                                  race_path=lambda dd, p: f"/{dd[:4]}/{dd[4:6]}/{dd[6:]}/tokyo/12r/")
        K = K or {}
        sched = {s: [{"date": r["date"], "name": r.get("name", ""), "grade": r.get("grade", ""), "venue": r.get("venue", ""),
                      "course": r.get("course", ""), "slug": s} for r in ys.values()] for s, ys in K.items()}
        try:
            weekly._B, weekly.TODAY, weekly._K, weekly.SCHED_BY_SLUG = B, today, K, sched
            weekly.PREDS, weekly.WAKU, weekly.ENTRIES, weekly.NOMS = preds or {}, waku or {}, {}, {}
            yield
        finally:
            for n, v in saved.items():
                setattr(weekly, n, v)


TDT_GUIDE = {"tokyo-daishoten": "東京大賞典"}
JC_ROW = {"date": "20261129", "name": "ジャパンカップ", "grade": "G1", "venue": "東京", "course": "芝 2,400 メートル", "cond": "3歳以上"}


def test_hub_info_before_entries():
    with weekly_state(K={"japan-cup": {2026: JC_ROW}}, guides={"japan-cup": "ジャパンカップ"}):
        info = weekly.hub_info("japan-cup", "2026", post_hint="15:40")
    assert info["date"] == "20261129" and info["venue"] == "東京" and info["course"] == "芝2400m" and info["grade"] == "G1"
    assert info["name"] == "ジャパンカップ" and info["jra"] is True and info["today"] == "20261126"
    assert info["post"] == "15:40" and info["post_fixed"] is False, "記事の予定時刻は「予定」として扱う"
    assert info["phase"] is None and info["pred_path"] == ""
    assert "11月27日（金）" in info["publish"] and info["graded_page"] is True
    assert len(hubfaq.faq_items(info)) == 6, "hub_info の形のまま、よくある質問を作れる"


def test_hub_info_course_wording():
    row = dict(JC_ROW, date="20261206", name="チャンピオンズカップ", venue="中京", course="ダ 1,800 メートル")
    with weekly_state(K={"champions-cup": {2026: row}}):
        info = weekly.hub_info("champions-cup", "2026")
    assert info["course"] == "ダート1800m" and info["post"] == "" and info["graded_page"] is False


def test_hub_info_with_prediction():
    pred = {"race_id": "jra_x", "marks": {"◎": 3}, "confidence": "B", "_race": {"post_time": "15:40", "horses": []}}
    with weekly_state(K={"japan-cup": {2026: JC_ROW}}, preds={"japan-cup": [("20261129", pred, "ジャパンカップ", "G1")]}):
        info = weekly.hub_info("japan-cup", "2026", post_hint="15:35")
    assert info["phase"] == "pred" and info["pred_path"] == "/2026/11/29/tokyo/12r/"
    assert info["post"] == "15:40" and info["post_fixed"] is True, "出馬表の時刻が、記事の予定時刻より優先"


def test_hub_info_post_time_from_entries_table():
    waku = {"japan-cup": {"date": "20261129", "post_time": "15:40", "numbered": False, "horses": [{"name": "ア"}],
                          "src": "waku", "since": "2026-11-26"}}
    with weekly_state(K={"japan-cup": {2026: JC_ROW}}, waku=waku):
        info = weekly.hub_info("japan-cup", "2026")
    assert info["post"] == "15:40" and info["post_fixed"] is True


def test_hub_info_local_race_from_front_matter():
    meta = {"date": "20261229", "venue": "大井", "course": "ダート2000m", "grade": "G1"}
    with weekly_state(guides=TDT_GUIDE):
        info = weekly.hub_info("tokyo-daishoten", "2026", meta=meta)
        none = weekly.hub_info("tokyo-daishoten", "2026")
        other_year = weekly.hub_info("tokyo-daishoten", "2027", meta=meta)
    with weekly_state():
        unnamed = weekly.hub_info("tokyo-daishoten", "2026", meta=meta)
    assert info["jra"] is False and info["date"] == "20261229" and info["venue"] == "大井" and info["course"] == "ダート2000m"
    assert info["name"] == "東京大賞典", "一覧に無いレースの名前は、レースガイドから"
    assert unnamed["name"] == "" and hubfaq.faq_md(unnamed) == "", "名前が分からないレースには、よくある質問を出さない"
    assert info["publish"] == "", "地方のレースの公開の日どりは、中央の決まりでは言えない"
    assert none is None and other_year is None, "日程が分からなければ None（よくある質問を出さない）"


def test_hub_info_finished_race():
    rows = [{"fin": i, "num": i, "frame": i, "name": f"ウマ{i}", "pop": i, "jockey": "騎手"} for i in (1, 2, 3)]
    done = dict(JC_ROW, date="20261122", name="マイルチャンピオンシップ", venue="京都", course="芝 1,600 メートル", rows=rows, pay={})
    with weekly_state(K={"mile-championship": {2026: done}}):
        info = weekly.hub_info("mile-championship", "2026")
    assert info["phase"] == "result" and hubfaq.faq_md(info) == ""


def test_hub_info_bad_year():
    with weekly_state(K={"japan-cup": {2026: JC_ROW}}):
        assert weekly.hub_info("japan-cup", "") is None and weekly.hub_info("japan-cup", "abcd") is None


def test_aff_for_skips_when_faq_has_pr():
    tables = {"aff_rakuten": "R", "aff_saikyo": "S"}
    c = {"slug": "tokyo-daishoten2026-guide", "race_venue": "大井", "body": ""}
    assert column._aff_for(c, tables) == "R"
    assert column._aff_for(dict(c, _faq_pr=True), tables) == "", "よくある質問の中にPRを出したページでは、末尾のPRを出さない"


JC_COL = {"slug": "jc2026-guide", "series": "jc2026",
          "body": "## レースの基本情報\n\n- 日時：2026年11月29日（日）15:40発走予定\n\n## 特集の記事\n\n- [枠順](/column/jc2026-waku/)\n\n## 出典\n\n- JRA\n"}
TDT_COL = {"slug": "tokyo-daishoten2026-guide", "series": "tdt2026", "race_date": "20261229", "race_venue": "大井",
           "race_course": "ダート2000m", "race_grade": "G1", "body": "## レースの基本情報\n\n- 場所：大井競馬場\n\n## 特集の記事\n\n- a\n"}
TABLES = {"aff_rakuten": "R", "aff_saikyo": "S", "aff_nar": "<div class='aff'>PR</div>"}


def test_with_faq_inserts_before_feature_list():
    c = dict(JC_COL)
    with weekly_state(K={"japan-cup": {2026: JC_ROW}}):
        body, ld = column._with_faq(c, TABLES)
    assert body.index("## レースの基本情報") < body.index("## ジャパンカップ2026のよくある質問") < body.index("## 特集の記事")
    assert "発走は15時40分の予定。" in body, "記事に書いた発走の予定時刻を使う"
    assert ld["@type"] == "FAQPage" and len(ld["mainEntity"]) == 6
    assert c["_faq_pr"] is False and column._aff_for(c, TABLES) == "S", "中央のレースは、末尾のPRをこれまでどおり出す"


def test_with_faq_leaves_other_articles_alone():
    with weekly_state(K={"japan-cup": {2026: JC_ROW}}):
        for c in ({"slug": "jc2026-waku", "series": "jc2026", "body": "本文\n"},     # 特集の中の、まとめ以外の記事
                  {"slug": "tansho-fukusho", "body": "本文\n"},                        # ふつうのコラム
                  {"slug": "x2026-guide", "series": "x2026", "body": "本文\n"}):       # レースに結びついていない特集
            assert column._with_faq(c, TABLES) == ("本文\n", None) and c["_faq_pr"] is False


def test_with_faq_local_race_pr_once():
    c = dict(TDT_COL)
    with weekly_state(guides=TDT_GUIDE):
        body, ld = column._with_faq(c, TABLES)
    assert body.count("{{aff_nar}}") == 1 and "大井競馬場のダート2000m" in body and ld["@type"] == "FAQPage"
    assert c["_faq_pr"] is True and column._aff_for(c, TABLES) == "", "同じPRを、質問の中と末尾の2か所に出さない"


def test_with_faq_keeps_end_pr_when_box_is_missing():
    c = dict(TDT_COL)
    with weekly_state(guides=TDT_GUIDE):
        column._with_faq(c, dict(TABLES, aff_nar=""))
    assert c["_faq_pr"] is False and column._aff_for(c, TABLES) == "R", "質問の中のPRが作れなかったら、末尾のPRを残す"


def test_with_faq_finished_race():
    rows = [{"fin": i, "num": i, "frame": i, "name": f"ウマ{i}", "pop": i, "jockey": "騎手"} for i in (1, 2, 3)]
    with weekly_state(K={"japan-cup": {2026: dict(JC_ROW, date="20261122", rows=rows, pay={})}}):
        assert column._with_faq(dict(JC_COL), TABLES) == (JC_COL["body"], None)


def test_with_faq_never_breaks_the_page():
    with weekly_state(K={"japan-cup": {2026: JC_ROW}}):
        weekly._K = None  # 重賞の一覧が壊れていても、記事はそのまま出す
        assert column._with_faq(dict(JC_COL), TABLES) == (JC_COL["body"], None)


def test_faq_renders_with_site_markdown():
    """よくある質問の Markdown が、このサイトの Markdown の読み方（column.render）で意図どおりのHTMLになる。"""
    with weekly_state(guides=TDT_GUIDE):
        body, _ = column._with_faq(dict(TDT_COL), TABLES)
    out = column.render(body, TABLES)
    assert out.count("<h2>東京大賞典2026のよくある質問</h2>") == 1 and out.count("<h3>") == 5
    assert out.count("<div class='aff'>PR</div>") == 1 and "{{" not in out
    assert "<a href='/column/tansho-fukusho/'>単勝と複勝の違い</a>" in out
    assert out.index("よくある質問</h2>") < out.index("<div class='aff'>PR</div>") < out.index("<h2>特集の記事</h2>")
    assert "](" not in out and "**" not in out, "リンクや強調の書き方が、そのまま出ていない"


if __name__ == "__main__":
    for _k, _f in sorted(globals().items()):
        if _k.startswith("test_") and callable(_f):
            _f()
    print("OK: よくある質問の検算 すべて一致")
