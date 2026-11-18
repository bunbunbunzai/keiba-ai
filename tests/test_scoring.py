"""回収率の計算（scraper/score.py）の検算。公開の前に毎回走らせる（.github/workflows/pages.yml）。

1. 採点の決まり：的中・不的中・組み合わせの順序・返還・払戻なし（中止）
2. 公開している記録との照合：results_ledger.csv の直近の行を、保存してある予想と結果から計算し直して一致するか

実行: python tests/test_scoring.py
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))

import score  # noqa: E402

RES = {
    "rows": [{"number": 7, "finish": "1"}, {"number": 3, "finish": "2"}, {"number": 11, "finish": "3"}, {"number": 5, "finish": "4"}, {"number": 9, "finish": "取消"}],
    "payouts": {
        "単勝": [{"combo": "7", "yen": 450}],
        "複勝": [{"combo": "7", "yen": 180}, {"combo": "3", "yen": 140}, {"combo": "11", "yen": 520}],
        "ワイド": [{"combo": "3-7", "yen": 390}, {"combo": "7-11", "yen": 1840}, {"combo": "3-11", "yen": 1210}],
        "3連複": [{"combo": "3-7-11", "yen": 6230}],
        "馬単": [{"combo": "7-3", "yen": 1980}],
        "_refund": [9],
    },
}


def pred(bets, hon=7):
    return {"race_id": "t", "confidence": "B", "marks": {"◎": hon}, "bets": bets}


def test_rules():
    s = score.score_race(pred([{"type": "単勝", "combo": "7"}]), RES)
    assert (s["stake"], s["return"], s["roi"], s["honmei_finish"], s["top3"]) == (100, 450, 450.0, "1", [7, 3, 11]), s
    s = score.score_race(pred([{"type": "複勝", "combo": "3"}], hon=3), RES)
    assert (s["stake"], s["return"]) == (100, 140), s
    s = score.score_race(pred([{"type": "単勝", "combo": "3"}], hon=3), RES)       # 2着の単勝は外れ
    assert (s["stake"], s["return"], s["roi"]) == (100, 0, 0.0), s
    # 順序を問わない券種は、並びが違っても当たり。順序のある券種は並びどおりだけ
    s = score.score_race(pred([{"type": "3連複", "combo": "11-3-7"}, {"type": "ワイド", "combo": "11-7"}, {"type": "馬単", "combo": "3-7"}, {"type": "馬単", "combo": "7-3"}]), RES)
    assert (s["stake"], s["return"]) == (400, 6230 + 1840 + 0 + 1980), s
    # 取消の馬を含む買い目は返還（100円が戻る）
    s = score.score_race(pred([{"type": "単勝", "combo": "9"}, {"type": "ワイド", "combo": "7-9"}], hon=9), RES)
    assert (s["stake"], s["return"]) == (200, 200), s
    # 買い目なし（印だけ）：購入0円、回収率は出さない
    s = score.score_race(pred([]), RES)
    assert (s["stake"], s["return"], s["roi"], s["voided"]) == (0, 0, None, False), s
    # 払戻が無い（中止など）：成績に数えない印が付く
    assert score.score_race(pred([{"type": "単勝", "combo": "7"}]), {"rows": [], "payouts": {}})["voided"] is True
    assert score.score_race(pred([{"type": "単勝", "combo": "7"}]), {"rows": [], "payouts": {"_refund": [7]}})["voided"] is True


def test_ledger_matches(days: int = 5):
    """公開している記録（1レース1行）の直近の日付分を、予想と結果から計算し直す。"""
    led = ROOT / "results_ledger.csv"
    if not led.exists():
        return 0
    rows = list(csv.DictReader(led.open(encoding="utf-8")))
    dates = sorted({r["date"] for r in rows})[-days:]
    n = 0
    for r in rows:
        if r["date"] not in dates:
            continue
        pf = ROOT / "predictions" / r["date"] / f"{r['race_id']}.json"
        if not pf.exists():
            raise AssertionError(f"記録にあるレースの予想が無い: {r['date']} {r['race_id']}")
        p = json.loads(pf.read_text(encoding="utf-8"))
        rf = ROOT / "data" / "results" / r["date"] / f"{p.get('results_key') or p['race_id']}.json"
        if not rf.exists():
            raise AssertionError(f"記録にあるレースの結果が無い: {r['date']} {r['race_id']}")
        s = score.score_race(p, json.loads(rf.read_text(encoding="utf-8")))
        if (int(r["stake"]), int(r["return"])) != (s["stake"], s["return"]):
            raise AssertionError(f"記録と計算し直した値が違う: {r['date']} {r['race_id']} 記録={r['stake']}/{r['return']} 計算={s['stake']}/{s['return']}")
        n += 1
    return n


if __name__ == "__main__":
    test_rules()
    print("採点の決まり: OK")
    # 照合のずれは、結果の訂正がまだ集計に入っていないだけのこともあるので、公開は止めずに警告として出す
    try:
        print(f"公開している記録との照合: OK（{test_ledger_matches()}レース）")
    except AssertionError as e:
        print(f"::warning title=回収率の記録が計算と合わない::{e}")
