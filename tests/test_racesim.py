"""site/racesim.py（レースシミュレーションのページ用データ）のテスト。

実行: python -m pytest tests/test_racesim.py -q
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "site"))

import racesim  # noqa: E402


def frame_of(num, field):
    return 1


def jra_pred(**over):
    p = {
        "race_id": "jra_20261115_京都_01",
        "venue": "京都",
        "marks": {"◎": 1, "〇": 2},
        "horses": [
            {"number": 1, "name": "アー", "score": 30, "win_pct": 40, "adj_pct": 50.0},
            {"number": 2, "name": "イー", "score": 25, "win_pct": 30, "adj_pct": 30.0},
            {"number": 3, "name": "ウー", "score": 20, "win_pct": 10, "adj_pct": 10.0},
        ],
        "_race": {
            "venue": "京都", "distance": 1800, "surface": "ダ", "field": 3,
            "course_text": "コース： 1,800 メートル （ダート・右）",
            "horses": [
                {"number": 1, "frame": 1, "name": "アー", "past": [{"corners": "1-1-1-1", "field": 10}]},
                {"number": 2, "frame": 2, "name": "イー", "past": []},
                {"number": 3, "frame": 3, "name": "ウー", "past": [{"corners": "10-9-8-7", "field": 10}]},
            ],
        },
        "_result": {},
    }
    p.update(over)
    return p


# ---------- 脚質 ----------
def test_style_front_runner_is_zero():
    assert racesim.style_of([{"corners": "1-1-1-1", "field": 12}]) == 0.0


def test_style_closer_is_one():
    assert racesim.style_of([{"corners": "12-12-10-5", "field": 12}]) == 1.0


def test_style_averages_up_to_five_runs():
    past = [{"corners": "1-1", "field": 11}, {"corners": "11-10", "field": 11}] + [{"corners": "6-6", "field": 11}] * 5
    # 先頭5走だけ: 0, 1, 0.5, 0.5, 0.5 → 平均 0.5
    assert racesim.style_of(past) == 0.5


def test_style_none_without_corners():
    assert racesim.style_of([]) is None
    assert racesim.style_of([{"corners": "", "field": 10}, {"field": 10}]) is None
    assert racesim.style_of([{"corners": "3-3", "field": 1}]) is None


# ---------- ページ用データ ----------
def test_sim_data_basic_fields():
    d = racesim.sim_data(jra_pred(), frame_of)
    assert d["dist"] == 1800
    assert d["dir"] == "R"
    assert d["straight"] is False
    assert d["surface"] == "ダ"
    assert d["lap"] > 1000 and 150 < d["home"] < 700
    nums = [h["n"] for h in d["horses"]]
    assert nums == [1, 2, 3]
    h1 = d["horses"][0]
    assert h1["m"] == "◎" and h1["f"] == 1 and h1["name"] == "アー"


def test_sim_data_probabilities_sum_to_100():
    d = racesim.sim_data(jra_pred(), frame_of)
    assert abs(sum(h["p"] for h in d["horses"]) - 100) < 0.5


def test_sim_data_missing_style_defaults_to_middle():
    d = racesim.sim_data(jra_pred(), frame_of)
    s = {h["n"]: h["s"] for h in d["horses"]}
    assert s[1] == 0.0 and s[2] == 0.5 and s[3] == 1.0


def test_sim_data_partial_adj_pct_still_gives_everyone_a_chance():
    p = jra_pred()
    del p["horses"][2]["adj_pct"]
    d = racesim.sim_data(p, frame_of)
    ps = {h["n"]: h["p"] for h in d["horses"]}
    assert all(v > 0 for v in ps.values())
    assert abs(sum(ps.values()) - 100) < 0.5


def test_sim_data_falls_back_to_score():
    p = jra_pred()
    for h in p["horses"]:
        h.pop("adj_pct"), h.pop("win_pct")
    d = racesim.sim_data(p, frame_of)
    ps = {h["n"]: h["p"] for h in d["horses"]}
    assert ps[1] > ps[2] > ps[3] > 0


def test_sim_data_excludes_horse_not_in_evaluations():
    p = jra_pred()
    p["_race"]["horses"].append({"number": 4, "frame": 4, "name": "取消馬", "past": []})
    d = racesim.sim_data(p, frame_of)
    assert [h["n"] for h in d["horses"]] == [1, 2, 3]


def test_sim_data_left_turn_from_course_text():
    p = jra_pred(venue="東京")
    p["_race"].update(venue="東京", course_text="コース： 1,600 メートル （芝・左）", surface="芝")
    assert racesim.sim_data(p, frame_of)["dir"] == "L"


def test_sim_data_local_venue_direction_from_table():
    p = jra_pred(race_id="202611151106070101", venue="船橋")
    p["_race"].update(venue="船橋", course_text="", distance=1200)
    assert racesim.sim_data(p, frame_of)["dir"] == "L"
    p = jra_pred(race_id="202611151106070101", venue="大井")
    p["_race"].update(venue="大井", course_text="", distance=1200)
    assert racesim.sim_data(p, frame_of)["dir"] == "R"


def test_sim_data_niigata_straight():
    p = jra_pred(venue="新潟")
    p["_race"].update(venue="新潟", course_text="コース： 1,000 メートル （芝・直）", surface="芝", distance=1000)
    d = racesim.sim_data(p, frame_of)
    assert d["straight"] is True


def test_sim_data_actual_result_top3():
    p = jra_pred(_result={"rows": [{"number": 3, "finish": "1"}, {"number": 1, "finish": "2"}, {"number": 2, "finish": "3"}]})
    assert racesim.sim_data(p, frame_of)["result"] == [3, 1, 2]


def test_sim_data_skips_banei():
    p = jra_pred(race_id="202611150304160501", venue="帯広")
    p["_race"].update(venue="帯広ば", course_text="", distance=200)
    assert racesim.sim_data(p, frame_of) is None


def test_sim_data_skips_jump_race():
    p = jra_pred()
    p["_race"]["course_text"] = "コース： 2,910 メートル （芝→ダート）"
    assert racesim.sim_data(p, frame_of) is None


def test_sim_data_skips_without_horses():
    assert racesim.sim_data(jra_pred(horses=[]), frame_of) is None


def test_sim_data_frame_from_helper_when_missing():
    p = jra_pred()
    for h in p["_race"]["horses"]:
        h.pop("frame")
    d = racesim.sim_data(p, lambda num, field: 7)
    assert {h["f"] for h in d["horses"]} == {7}


# ---------- HTML ----------
def test_section_embeds_safe_json_and_script():
    p = jra_pred()
    p["horses"][0]["name"] = "</script><b>"
    p["_race"]["horses"][0]["name"] = "</script><b>"
    html = racesim.section(p, frame_of, "abc123")
    assert "</script><b>" not in html
    assert "/racesim.js?v=abc123" in html
    start = html.index('class="simdata">') + len('class="simdata">')
    end = html.index("</script>", start)
    d = json.loads(html[start:end])
    assert d["horses"][0]["name"] == "</script><b>"
    assert "シミュレーション" in html and "演出" in html


def test_section_empty_when_no_data():
    p = jra_pred(horses=[])
    assert racesim.section(p, frame_of, "x") == ""


def test_section_3d_url_only_when_given():
    p = jra_pred()
    plain = racesim.section(p, frame_of, "x")
    assert '"d3"' not in plain
    html = racesim.section(p, frame_of, "x", d3="/racesim3d.js?v=1")
    start = html.index('class="simdata">') + len('class="simdata">')
    d = json.loads(html[start:html.index("</script>", start)])
    assert d["d3"] == "/racesim3d.js?v=1"


def test_sim_data_going_only_when_known():
    p = jra_pred()
    assert "going" not in racesim.sim_data(p, frame_of)
    p["_race"]["track"] = "重"
    assert racesim.sim_data(p, frame_of)["going"] == "重"
    p["_race"]["track"] = "晴"
    assert "going" not in racesim.sim_data(p, frame_of)
