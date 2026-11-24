"""Threads への自動投稿（scraper/social.py）の検算。

1. 出す・出さないの決まり（設定オフ・地方の重賞・前日夜に出したレースの当日分）
2. 文面：500字以内、問いかけが入る、同じ投稿なら毎回同じ文面
3. 送信：リンクを付ける種類だけ付く、1日の上限（全成績は数えない）、続けて失敗したら止まる

実行: python tests/test_social_threads.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))

import social  # noqa: E402

CFG = {"threads": True, "threads_scope": "jra", "threads_max_per_day": 1, "threads_link_kinds": ["grade_pre", "summary"]}


def race(rid="jra_2026112905_11", grade="G1", score=None, name="ジャパンカップ"):
    hs = [{"number": i, "name": f"ウマ{i}"} for i in range(1, 6)]
    return {"race_id": rid, "venue": "東京", "race_no": 11, "race_name": name, "marks": {"◎": 3, "〇": 1, "▲": 5}, "confidence": "B",
            "summary": "先行有利の馬場で、◎は前走の内容が良い。" * 20, "_race": {"post_time": "15:40", "horses": hs}, "_score": score, "_grade": grade, "horses": []}


def check(cond, msg):
    if not cond:
        print("NG:", msg)
        sys.exit(1)


def main():
    pre = {"id": "pre-jra_2026112905_11", "kind": "grade_pre", "p": race()}
    eve = {"id": "eve-jra_2026112905_11", "kind": "grade_pre", "p": race(), "eve": True}
    local = {"id": "pre-urawa_11", "kind": "grade_pre", "p": race("urawa_2026112911", "S3", name="浦和スプリント")}
    jpn1 = {"id": "pre-kawasaki_11", "kind": "grade_pre", "p": race("kawasaki_2026121611", "Jpn1", name="全日本2歳優駿")}

    # 1. 出す・出さない
    check(not social.threads_wanted({}, pre, {}), "設定に threads が無ければ出さない")
    check(social.threads_wanted(CFG, pre, {}), "中央の重賞は出す")
    check(not social.threads_wanted(CFG, local, {}), "地方の重賞（G1以外）は出さない")
    check(social.threads_wanted(CFG, jpn1, {}), "地方の Jpn1 は出す")
    check(not social.threads_wanted(CFG, pre, {eve["id"]: {"threads": "posted"}}), "前日夜に出したレースは当日に重ねて出さない")
    check(social.threads_wanted(CFG, pre, {eve["id"]: {"threads": "off"}}), "前日夜に出していなければ当日に出す")
    check(not social.threads_wanted(CFG | {"threads_kinds": ["summary"]}, pre, {}), "threads_kinds に無い種類は出さない")

    # 2. 文面
    t = social.threads_text("20261129", pre)
    check(len(t) <= 500, f"500字以内（{len(t)}字）")
    check("◎3ウマ3" in t and "？" in t and "馬券は20歳から" in t, "本命・問いかけ・注記が入る")
    check(t.rstrip().endswith("#ジャパンカップ"), "タグはレース名の1つだけを末尾に")
    check(t == social.threads_text("20261129", pre), "同じ投稿なら同じ文面")
    win = {"id": "res-x", "kind": "grade_res", "p": race(score={"stake": 1000, "return": 5400, "hits": ["単勝 3 540円"], "top3": [3, 1, 5]})}
    lose = {"id": "res-y", "kind": "grade_res", "p": race(score={"stake": 1000, "return": 0, "hits": [], "top3": [2, 4, 1]})}
    check("的中でした" in social.threads_text("20261129", win), "的中の文面")
    tl = social.threads_text("20261129", lose)
    check("外れました" in tl and "2-4-1" in tl, "不的中も隠さず出す")
    rs = [race(score={"stake": 1000, "return": 5400}), race("jra_x", None, {"stake": 1000, "return": 0})]
    ts = social.threads_text("20261129", {"id": "sum-20261129", "kind": "summary", "rs": rs})
    check("全2レース" in ts and "的中1レース" in ts and "270.0%" in ts, "全成績の数字")

    # 3. 送信（実際には送らず、送ろうとした内容を記録する）
    with tempfile.TemporaryDirectory() as d:
        social.SOCIAL = Path(d)
        (Path(d) / "config.json").write_text(json.dumps(CFG), encoding="utf-8")
        now = social.now().strftime("%Y-%m-%d %H:%M")
        mk = lambda kind, link: {"kind": kind, "grade": "", "image": "/x.jpg", "images": ["/x.jpg"], "url": "https://example.test/r", "created": now,  # noqa: E731
                                 "x": "off", "instagram": "off", "threads": "pending", "threads_text": kind, "threads_link": link}
        st = {"date": "20261129", "posts": {"a": mk("grade_pre", True), "b": mk("gensen", False), "s": mk("summary", True)}}
        social.save_state("20261129", st)
        sent = []
        social.post_threads = lambda text, link=None: sent.append((text, link)) or "id1"
        social.live = lambda url: False  # 画像がまだ公開されていなくても、文字だけの Threads は出す
        os.environ["THREADS_ACCESS_TOKEN"] = "test"
        n = social.publish("20261129")
        after = social.load_state("20261129")["posts"]
        check(n == 2 and sent == [("grade_pre", "https://example.test/r"), ("summary", "https://example.test/r")], f"上限1件＋全成績だけ出る {sent}")
        check(after["b"]["threads"] == "off" and after["b"].get("threads_skip"), "上限を超えた分は出さない")

        # 続けて失敗したら止める
        def boom(text, link=None):
            raise RuntimeError("blocked")
        social.post_threads = boom
        (Path(d) / "config.json").write_text(json.dumps(CFG | {"threads_max_per_day": 99}), encoding="utf-8")
        st = {"date": "20261130", "posts": {k: mk("hit", False) for k in "abcde"}}
        social.save_state("20261130", st)
        social.publish("20261130")
        check(social.TH["fail_streak"] == 3, f"3回続けて失敗したら、それ以上は送らない（{social.TH['fail_streak']}回）")
        after = social.load_state("20261130")["posts"]
        check(sum(1 for e in after.values() if e.get("threads_wait")) == 2, "残りは待機にする")
    print("OK: Threads の検算 すべて一致")


if __name__ == "__main__":
    main()
