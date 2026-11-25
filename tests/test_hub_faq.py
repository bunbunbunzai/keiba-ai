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


if __name__ == "__main__":
    for _k, _f in sorted(globals().items()):
        if _k.startswith("test_") and callable(_f):
            _f()
    print("OK: よくある質問の検算 すべて一致")
