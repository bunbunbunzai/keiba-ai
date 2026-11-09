"""騎手・厩舎の最近の成績（このサイトが予想したレースの結果から集計）。digest.py が出馬表の要約に出す。

2026-11-10の分析で、騎手・厩舎の強さは「人的・その他」の中で最も着順を説明していた（データで説明できる分の約2割）。
それまでの要約には名前しか出ておらず、AIは名前だけで判断していたため、数字を出す。

集計：対象日より前の DAYS 日間、予想ファイルがあり結果が確定したレース。名前は主催者の表記のまま（中央と地方で別に数える）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from functools import lru_cache

from common import DATA_DIR

ROOT = DATA_DIR.parent
DAYS = 90
MIN_N = 5


def norm(name: str) -> str:
    return re.sub(r"[\s　☆★▲△◇◆]", "", str(name or ""))


@lru_cache(maxsize=8)
def stats(date: str) -> dict:
    """{(source, 'j'|'t', 名前): [騎乗数, 1着, 3着内]}"""
    out: dict = {}
    end = datetime.strptime(date, "%Y%m%d")
    for i in range(1, DAYS + 1):
        d = (end - timedelta(days=i)).strftime("%Y%m%d")
        pdir = ROOT / "predictions" / d
        if not pdir.exists():
            continue
        for f in pdir.glob("*.json"):
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            rid, rk = p.get("race_id"), p.get("results_key") or p.get("race_id")
            rf, sf = DATA_DIR / "races" / d / f"{rid}.json", DATA_DIR / "results" / d / f"{rk}.json"
            if not rf.exists() or not sf.exists():
                continue
            try:
                race, res = json.loads(rf.read_text(encoding="utf-8")), json.loads(sf.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            fin = {}
            for r in res.get("rows") or []:
                try:
                    fin[int(r["number"])] = int(str(r.get("finish")).strip())
                except (TypeError, ValueError, KeyError):
                    pass
            if len(fin) < 3:
                continue
            src = "jra" if str(rid).startswith("jra_") else "local"
            for h in race.get("horses") or []:
                try:
                    n = int(h.get("number"))
                except (TypeError, ValueError):
                    continue
                if n not in fin:
                    continue
                for kind in ("j", "t"):
                    nm = norm(h.get("jockey") if kind == "j" else h.get("trainer"))
                    if not nm:
                        continue
                    a = out.setdefault((src, kind, nm), [0, 0, 0])
                    a[0] += 1
                    a[1] += fin[n] == 1
                    a[2] += fin[n] <= 3
    return out


def label(date: str, race_id: str, kind: str, name: str) -> str:
    """'3着内31%・勝率12%（42走）' の形。少ないときは '（3走・参考少）'。"""
    if not date:
        return "記録なし"
    src = "jra" if str(race_id).startswith("jra_") else "local"
    a = stats(date).get((src, kind, norm(name)))
    if not a:
        return "最近の記録なし"
    n, w, t3 = a
    if n < MIN_N:
        return f"{n}走・参考少"
    return f"3着内{round(100 * t3 / n)}%・勝率{round(100 * w / n)}%（{n}走）"
