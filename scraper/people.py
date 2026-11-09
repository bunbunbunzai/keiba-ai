"""騎手・厩舎の最近の成績。digest.py が出馬表の要約に出す。

2026-11-10の分析で、騎手・厩舎の強さは「人的・その他」の中で最も着順を説明していた（データで説明できる分の約2割）。
それまでの要約には名前しか出ておらず、AIは名前だけで判断していたため、数字を出す。

集計の材料（対象日より前の DAYS 日間）：
- 騎手：保存してある全出馬表の各馬の近走（騎手・着順・頭数つき。同じレース・同じ馬は1回だけ数える）。
  予想していないレースの分も入るので、サンプルが大きい（2週間分の出馬表で約3万7千走）。
- 厩舎：近走には厩舎が無いので、このサイトが予想して結果が確定したレースだけ。
名前は主催者の表記のまま（中央と地方で別に数える）。中央の近走は「日付・京都」の形、地方は「2026-11-02・盛岡」の形。
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
JRA_VENUES = {"札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"}


def norm(name: str) -> str:
    return re.sub(r"[\s　☆★▲△◇◆]", "", str(name or ""))


def _pdate(s: str) -> str | None:
    s = str(s or "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s) or re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s)
    return f"{int(m.group(1)):04d}{int(m.group(2)):02d}{int(m.group(3)):02d}" if m else None


def _is_jra(venue: str) -> bool:
    v = str(venue or "").lstrip("Ｊ")
    return v in JRA_VENUES


@lru_cache(maxsize=8)
def stats(date: str) -> dict:
    """{(source, 'j'|'t', 名前): [走数, 1着, 3着内]}"""
    out: dict = {}
    end = datetime.strptime(date, "%Y%m%d")
    lo = (end - timedelta(days=DAYS)).strftime("%Y%m%d")
    seen = set()

    def bump(src, kind, name, fin):
        nm = norm(name)
        if not nm:
            return
        a = out.setdefault((src, kind, nm), [0, 0, 0])
        a[0] += 1
        a[1] += fin == 1
        a[2] += fin <= 3

    # 騎手：全出馬表の近走から
    for day in sorted(p.name for p in (DATA_DIR / "races").iterdir() if p.is_dir() and p.name.isdigit()):
        if day > date:  # 対象日より後の出馬表は見ない（その日以前の近走しか入っていないが念のため）
            continue
        for f in (DATA_DIR / "races" / day).glob("*.json"):
            try:
                race = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for h in race.get("horses") or []:
                for p in h.get("past") or []:
                    d = _pdate(p.get("date"))
                    if not d or not (lo <= d < date):
                        continue
                    try:
                        fin = int(str(p.get("finish")).strip())
                    except (TypeError, ValueError):
                        continue
                    key = (d, str(p.get("venue")), norm(h.get("name")))
                    if key in seen:
                        continue
                    seen.add(key)
                    bump("jra" if _is_jra(p.get("venue")) else "local", "j", p.get("jockey"), fin)
    # 厩舎：予想して結果が確定したレースから
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
                if n in fin:
                    bump(src, "t", h.get("trainer"), fin[n])
    return out


def label(date: str, race_id: str, kind: str, name: str) -> str:
    """'3着内31%・勝率12%（42走）' の形。少ないときは '3走・参考少'。"""
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
