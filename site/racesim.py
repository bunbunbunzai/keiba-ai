"""レースシミュレーション（演出）：レースページに埋め込むデータとHTMLを作る。

描画と実況はブラウザ側の racesim.js が行う。ここでは
  - 着順を決める重み（AIの補正勝率 → 想定勝率 → 評価点の順に使う）
  - 道中の動きを決める脚質（過去のレースの最初のコーナーの通過順から 0=前 〜 1=後ろ）
  - コースの回りと、おおよその1周・直線の長さ
をJSONにまとめる。ばんえい・障害レースには出さない。
"""
from __future__ import annotations

import html
import json
import math
from typing import Callable

MARKS = ["◎", "〇", "▲", "△", "☆"]
BANEI = {"帯広", "帯広ば"}
DEFAULT_GEOM = ("R", {"ダ": (1600, 300), "芝": (1600, 300)})
# 回り（R=右、L=左）と、コースごとの (1周の長さm, 最後の直線m) のおおよその値。描画の縮尺に使うだけ
GEOM: dict[str, tuple[str, dict[str, tuple[int, int]]]] = {
    "札幌": ("R", {"芝": (1641, 266), "ダ": (1487, 264)}),
    "函館": ("R", {"芝": (1627, 262), "ダ": (1476, 260)}),
    "福島": ("R", {"芝": (1600, 292), "ダ": (1445, 296)}),
    "新潟": ("L", {"芝": (1623, 359), "芝外": (2223, 659), "ダ": (1472, 354)}),
    "東京": ("L", {"芝": (2083, 526), "ダ": (1899, 502)}),
    "中山": ("R", {"芝": (1667, 310), "芝外": (1840, 310), "ダ": (1493, 308)}),
    "中京": ("L", {"芝": (1706, 413), "ダ": (1530, 411)}),
    "京都": ("R", {"芝": (1783, 328), "芝外": (1894, 404), "ダ": (1608, 329)}),
    "阪神": ("R", {"芝": (1689, 357), "芝外": (2089, 474), "ダ": (1518, 353)}),
    "小倉": ("R", {"芝": (1615, 293), "ダ": (1445, 291)}),
    "門別": ("R", {"ダ": (1600, 330)}),
    "盛岡": ("L", {"ダ": (1600, 300), "芝": (1400, 300)}),
    "水沢": ("R", {"ダ": (1200, 247)}),
    "浦和": ("L", {"ダ": (1200, 220)}),
    "船橋": ("L", {"ダ": (1400, 308)}),
    "大井": ("R", {"ダ": (1600, 386)}),
    "川崎": ("L", {"ダ": (1200, 300)}),
    "金沢": ("R", {"ダ": (1200, 236)}),
    "笠松": ("R", {"ダ": (1100, 201)}),
    "名古屋": ("R", {"ダ": (1180, 240)}),
    "園田": ("R", {"ダ": (1051, 213)}),
    "姫路": ("R", {"ダ": (1400, 230)}),
    "高知": ("R", {"ダ": (1100, 200)}),
    "佐賀": ("R", {"ダ": (1100, 200)}),
}


def style_of(past: list[dict]) -> float | None:
    """直近5走の最初のコーナーの位置から脚質を 0（先頭）〜1（最後方）で出す。データが無ければ None。"""
    vals = []
    for x in (past or [])[:5]:
        c = str(x.get("corners") or "").split("-")[0].strip()
        try:
            pos, field = int(c), int(x.get("field") or 0)
        except ValueError:
            continue
        if field < 2:
            continue
        vals.append(min(1.0, max(0.0, (pos - 1) / (field - 1))))
    return round(sum(vals) / len(vals), 3) if vals else None


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def _weights(evals: list[dict]) -> dict:
    """着順を決める重み（合計100）。補正勝率→想定勝率→評価点の順に、半分以上の馬にある値を使う。"""
    nums = [e["number"] for e in evals]
    for key in ("adj_pct", "win_pct"):
        vals = {e["number"]: _num(e.get(key)) for e in evals}
        have = {n: v for n, v in vals.items() if v}
        if have and len(have) * 2 >= len(nums):
            low = min(have.values()) * 0.5
            w = {n: have.get(n, low) for n in nums}
            break
    else:
        sc = {e["number"]: e.get("score") for e in evals if isinstance(e.get("score"), (int, float))}
        if sc:
            top = max(sc.values())
            low = min(sc.values())
            w = {n: math.exp((sc.get(n, low) - top) / 4) for n in nums}
        else:
            w = {n: 1.0 for n in nums}
    tot = sum(w.values())
    return {n: round(v * 100 / tot, 2) for n, v in w.items()}


def _marks(p: dict) -> dict:
    out = {}
    for m in MARKS:
        v = (p.get("marks") or {}).get(m)
        for n in (v if isinstance(v, list) else [v] if v is not None else []):
            out.setdefault(n, m)
    return out


def _top3(p: dict) -> list:
    rows = (p.get("_result") or {}).get("rows") or []
    fin = {}
    for x in rows:
        f = str(x.get("finish") or "")
        if f in ("1", "2", "3") and x.get("number") is not None:
            fin.setdefault(int(f), x["number"])
    if fin:
        return [fin[k] for k in sorted(fin)]
    return list((p.get("_score") or {}).get("top3") or [])[:3]


def sim_data(p: dict, frame_of: Callable) -> dict | None:
    """ページに埋め込むシミュレーション用データ。出さないレースは None。"""
    r = p.get("_race") or {}
    venue = p.get("venue") or r.get("venue") or ""
    if venue in BANEI or r.get("venue") in BANEI:
        return None
    ct = str(r.get("course_text") or "")
    name = str(p.get("race_name") or r.get("race_name") or "")
    if "障害" in name or "ジャンプ" in name or "→" in ct:
        return None
    if str(p.get("race_id") or "").startswith("jra_") and ct and not any(c in ct for c in "右左直"):
        return None
    try:
        dist = int(r.get("distance") or 0)
    except (TypeError, ValueError):
        dist = 0
    evals = [e for e in p.get("horses") or [] if isinstance(e.get("number"), int)]
    if dist < 200 or len(evals) < 2:
        return None
    surface = "芝" if r.get("surface") == "芝" else "ダ"
    turn, table = GEOM.get(venue, DEFAULT_GEOM)
    if "右" in ct:
        turn = "R"
    elif "左" in ct:
        turn = "L"
    key = "芝外" if surface == "芝" and "外" in ct and "芝外" in table else surface
    lap, home = table.get(key) or table.get("ダ") or next(iter(table.values()))
    race_h = {h.get("number"): h for h in r.get("horses") or []}
    field = r.get("field") or len(race_h) or len(evals)
    w = _weights(evals)
    mk = _marks(p)
    horses = []
    for e in sorted(evals, key=lambda e: e["number"]):
        n = e["number"]
        h = race_h.get(n, {})
        st = style_of(h.get("past") or [])
        try:
            fr = int(h.get("frame") or frame_of(n, field) or 1)
        except (TypeError, ValueError):
            fr = 1
        horses.append({"n": n, "name": h.get("name") or e.get("name") or "", "f": min(8, max(1, fr)),
                       "m": mk.get(n, ""), "p": w[n], "s": 0.5 if st is None else st})
    out = {"id": str(p.get("race_id") or ""), "dist": dist, "surface": surface, "dir": turn,
            "straight": "直" in ct, "lap": lap, "home": home, "horses": horses, "result": _top3(p)}
    going = str(r.get("track") or "").strip()
    if going in ("良", "稍重", "重", "不良"):  # 馬場状態（分かっているレースだけ。3Dのダートの砂の色に使う）
        out["going"] = going
    return out


def section(p: dict, frame_of: Callable, js_v: str, d3: str | None = None) -> str:
    """レースページに差し込むカード（データが無ければ空文字）。
    d3 に3D表示のスクリプトのURLを渡すと（重賞のページ）、対応している端末では3Dで描く。"""
    d = sim_data(p, frame_of)
    if not d:
        return ""
    if d3:
        d["d3"] = d3
    data = json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    label = html.escape(f"{d['dist']}m {d['surface']}のレースを上から見た図")
    return (
        '<section class="card rsim">'
        '<h2>レースシミュレーション<small class="rsim-tag">演出</small></h2>'
        '<p class="meta">AIの補正勝率をもとに着順を決め、過去のレースの通過順から読んだ脚質で道中の動きを描いています。'
        '走らせるたびに結果は変わります。実際のレース展開を予想するものではありません。</p>'
        f'<div class="rsim-stage"><canvas role="img" aria-label="{label}"></canvas></div>'
        '<p class="rsim-call" aria-live="polite">「スタート」を押すと走り出します。</p>'
        '<div class="rsim-ctl"><button type="button" class="go rsim-go" disabled>スタート</button>'
        '<button type="button" class="rsim-voice" aria-pressed="false">実況の音声：オフ</button></div>'
        '<div class="rsim-res" hidden></div>'
        '<div class="rsim-tally"></div>'
        f'<script type="application/json" class="simdata">{data}</script>'
        f'<script src="/racesim.js?v={html.escape(js_v)}" defer></script>'
        '</section>')


CSS = (".rsim-stage{position:relative;margin:8px 0 6px;border:1px solid var(--line);border-radius:6px;overflow:hidden;background:var(--panel)}"
       ".rsim-stage canvas{display:block;width:100%;height:auto}"
       ".rsim h2 .rsim-tag{display:inline-block;margin-left:8px;padding:0 6px;border:1px solid var(--line);border-radius:3px;font-size:12px;vertical-align:middle}"
       ".rsim-call{min-height:1.75em;margin:6px 0;font-weight:700}"
       ".rsim-ctl{display:flex;gap:8px;flex-wrap:wrap;align-items:center}"
       ".rsim .rsim-ctl .rsim-go{background:var(--acc);color:#fff;border:0;border-radius:8px;padding:8px 18px;font-weight:700;font-size:15px}"
       ".rsim .rsim-ctl .rsim-go[disabled]{opacity:.6;cursor:default}"
       ".rsim-res{margin:10px 0;padding:8px 12px;background:var(--acc-soft);border-left:4px solid var(--acc);font-size:14px}"
       ".rsim-res p{margin:2px 0}"
       ".rsim-tally{margin-top:14px}.rsim-tally h3{margin-top:0}"
       ".rsim-tally td.n,.rsim-tally th.n{text-align:right;white-space:nowrap}"
       ".rsim-tally .bar{display:inline-block;height:8px;background:var(--acc);border-radius:2px;margin-left:6px;vertical-align:middle;opacity:.7}"
       ".rsim-tally details{margin-top:6px}.rsim-tally summary{cursor:pointer;font-size:14px;color:var(--acc)}"
       "@media (max-width:520px){.rsim-tally .bar{display:none}.rsim-tally th,.rsim-tally td{padding:6px 5px}}"
       # 3D（重賞）
       ".rsim-stage .rsim-3d{display:block;width:100%}"
       ".rsim-hud{position:absolute;left:10px;right:10px;top:8px;display:flex;justify-content:space-between;gap:10px;pointer-events:none;"
       "color:#fff;font-weight:700;font-size:14px;text-shadow:0 1px 3px rgba(0,0,0,.75),0 0 2px rgba(0,0,0,.6)}"
       ".rsim-hud .l{font-size:12px;text-align:right}"
       ".rsim-fin{position:absolute;left:50%;top:38px;transform:translateX(-50%);display:flex;flex-direction:column;gap:2px;align-items:flex-start;"
       "padding:8px 14px;border-radius:8px;background:rgba(0,0,0,.55);color:#fff;font-size:14px;font-weight:700;pointer-events:none;white-space:nowrap}"
       ".rsim-fin[hidden]{display:none}"
       ".rsim-fin b{align-self:center;font-size:20px;letter-spacing:.08em;color:#ffd54a}"
       ".rsim-fin i{display:inline-block;min-width:1.5em;padding:0 3px;border-radius:3px;text-align:center;font-style:normal}"
       ".rsim-loading::after{content:'3Dを準備中…';position:absolute;right:10px;bottom:8px;font-size:12px;color:var(--mut)}"
       ".rsim-views{display:inline-flex;margin-left:auto}"
       ".rsim-views button{border-radius:0;margin-left:-1px}.rsim-views button:first-child{border-radius:6px 0 0 6px}.rsim-views button:last-child{border-radius:0 6px 6px 0}"
       ".rsim-views button[aria-pressed=true]{background:var(--acc);color:#fff;border-color:var(--acc)}"
       "@media (max-width:520px){.rsim-views{margin-left:0}.rsim-hud{font-size:12px}.rsim-hud .l{font-size:11px}}")
