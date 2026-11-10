"""X・Instagram への自動投稿。

投稿するもの（1レース・1日につき1回だけ）
- hit       ：大きな的中だけ（払戻が購入額の3倍以上かつ300円以上のプラス。1日3件まで。小さな的中は summary の一覧にまとめる。重賞は grade_res）
- grade_pre ：重賞の予想（発走の10〜120分前）
- grade_res ：重賞の結果（的中・不的中とも）
- summary   ：その日の全成績（全レース確定後、または21:40以降）。厳選レースがあった日は、その結果をスレッド（返信）に1件
- gensen    ：朝（9:30〜11:30）の「今日の厳選レース」（自信度A）。無い日は picks（今日の勝負レース）

流れ（pages のデプロイ後に毎回呼ばれる）
1. publish：画像が公開URLで見られる「ready」の投稿を X・Instagram に出す（鍵が無ければ draft のまま）
2. prepare：新しく条件を満たした投稿の画像と文面を social/<日付>/ に作る（→ commit・push・サイト再公開 → 次の回で publish）

設定 social/config.json：{"x": true, "instagram": true, "x_url": "none" | "graded" | "key" | "all"}
  x_url: X の本文にサイトのURLを入れる投稿の範囲。none=入れない、graded=重賞のみ、key=重賞・勝負レース・全成績、all=全部
  （X API の従量課金はURL付き投稿が約0.20ドル、URL無しが約0.015ドルと差が大きいため範囲を選べる）
鍵（GitHub Secrets → 環境変数）：X_API_KEY X_API_SECRET X_ACCESS_TOKEN X_ACCESS_SECRET / IG_USER_ID IG_ACCESS_TOKEN

使い方: python scraper/social.py --date 20261101 [--prepare-only] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import DATA_DIR

ROOT = DATA_DIR.parent
SOCIAL = ROOT / "social"
JST = timezone(timedelta(hours=9))
BASE_URL = "https://www.ai-keiba-log.com"
STATS_FROM = "20261026"
sys.path.insert(0, str(ROOT / "site"))


def now() -> datetime:
    return datetime.now(JST)


def load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def nfkc(s) -> str:
    return unicodedata.normalize("NFKC", s or "")


# ---------------- 重賞の判定 ----------------
GRADE_RE = re.compile(r"\((G|Jpn|JPN|S|SP|M|H|BG|重賞)\s*([1-3ⅠⅡⅢ])\)")


def grade_of(race: dict) -> str | None:
    g = race.get("grade")
    if g and g.upper().startswith(("G", "J・G")):
        return g
    text = nfkc(" ".join(str(race.get(k) or "") for k in ("race_name", "title_text", "conditions")))
    m = GRADE_RE.search(text)
    if m:
        lvl = {"Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3"}.get(m.group(2), m.group(2))
        return f"{m.group(1)}{lvl}"
    if "重賞" in text:
        return "重賞"
    return None


# ---------------- データ ----------------
def races_of(date: str) -> list[dict]:
    score = load(DATA_DIR / "results" / date / "score.json", {}) or {}
    sc_by = {r.get("race_id"): r for r in score.get("races", [])}
    out = []
    for f in sorted((ROOT / "predictions" / date).glob("*.json")):
        p = load(f)
        if not p:
            continue
        p["_race"] = load(DATA_DIR / "races" / date / f"{p['race_id']}.json", {}) or {}
        s = sc_by.get(p["race_id"])
        p["_score"] = s if s and "stake" in s and not s.get("voided") else None
        p["_grade"] = grade_of(p["_race"] | {"race_name": p.get("race_name") or p["_race"].get("race_name")})
        out.append(p)
    return out


def venue(p) -> str:
    return p.get("venue") or p["_race"].get("venue") or ""


def rno(p) -> int:
    return int(p.get("race_no") or p["_race"].get("race_no") or 0)


def rname(p) -> str:
    n = nfkc(p.get("race_name") or p["_race"].get("race_name") or p["_race"].get("title_text") or "")
    n = re.sub(r"\s*(\([A-Za-z]{1,3}\d\)|[ABC]\d.*|C\d.*|\d歳.*|オープン.*)$", "", n).strip()
    return n


def horse(p, num) -> str:
    for h in p["_race"].get("horses", []) or []:
        if h.get("number") == num:
            return h.get("name") or ""
    return next((e.get("name") for e in p.get("horses", []) if e.get("number") == num), "") or ""


def race_url(date: str, p) -> str:
    from build import race_path  # site/build.py の URL 規則に合わせる
    return BASE_URL + race_path(date, p)


def fmt_md(date: str) -> str:
    return f"{int(date[4:6])}/{int(date[6:8])}"


def post_dt(date: str, p) -> datetime | None:
    pt = p["_race"].get("post_time") or ""
    if not re.fullmatch(r"\d{1,2}:\d{2}", pt):
        return None
    h, m = map(int, pt.split(":"))
    return datetime.strptime(date, "%Y%m%d").replace(hour=h, minute=m, tzinfo=JST)


def ledger_roi() -> str:
    import csv
    f = ROOT / "results_ledger.csv"
    if not f.exists():
        return "―"
    rows = [r for r in csv.DictReader(f.open(encoding="utf-8")) if r["date"] >= STATS_FROM and int(r["stake"] or 0) > 0]
    st, rt = sum(int(r["stake"]) for r in rows), sum(int(r["return"]) for r in rows)
    return f"{100 * rt / st:.1f}%" if st else "―"


# ---------------- 投稿の候補 ----------------
# フォロワーが少ないうちに小さな的中を大量に流すとスパム扱いされやすいので、個別の的中投稿は大きなものだけにする（2026-11-10）
HIT_MULT = 3            # 払戻が購入額の3倍以上
HIT_MIN_PROFIT = 300    # かつ300円以上のプラス
HIT_MAX_PER_DAY = 3     # 1日3件まで（払戻の大きい順）


def candidates(date: str) -> list[dict]:
    rs = races_of(date)
    t = now()
    out = []
    for p in rs:
        sc, g = p["_score"], p["_grade"]
        if p.get("confidence") == "見送り":
            continue
        if g:
            pd = post_dt(date, p)
            if pd and timedelta(minutes=10) <= pd - t <= timedelta(minutes=120) and not sc:
                out.append({"id": f"pre-{p['race_id']}", "kind": "grade_pre", "p": p})
            # 前日夜（19時以降）に、翌日の重賞の予想を1回だけ（検索・SNSの需要が前日から高まるため）
            if pd and pd.date() - t.date() == timedelta(days=1) and t.hour >= 19 and not sc:
                out.append({"id": f"eve-{p['race_id']}", "kind": "grade_pre", "p": p, "eve": True})
            if sc and sc["stake"]:
                out.append({"id": f"res-{p['race_id']}", "kind": "grade_res", "p": p})
        elif sc and sc["stake"] and sc["return"] >= HIT_MULT * sc["stake"] and sc["return"] - sc["stake"] >= HIT_MIN_PROFIT:
            out.append({"id": f"hit-{p['race_id']}", "kind": "hit", "p": p, "ret": sc["return"]})
    # 朝の投稿（1日1回）：9:30〜11:30に「今日の厳選レース」（自信度A＝◎の補正勝率50%以上。朝のオッズで決まったもの）。
    # 厳選レースが無ければ従来の「今日の勝負レース」。厳選は当日朝のオッズ反映（9:03の回）の後に決まるので9:30から。
    if t.strftime("%Y%m%d") == date and "09:30" <= t.strftime("%H:%M") <= "11:30":
        gs = gensen_races(date, rs, t)
        if gs:
            out.append({"id": f"picks-{date}", "kind": "gensen", "ps": gs})
        else:
            from build import picks
            ps = [p for p in picks(rs) if not p["_score"]]
            if len(ps) >= 2:
                out.append({"id": f"picks-{date}", "kind": "picks", "ps": ps})
    bet = [p for p in rs if p.get("confidence") != "見送り"]
    done = [p for p in bet if p["_score"]]
    if bet and done and (len(done) == len(bet) or t.strftime("%Y%m%d") > date or t.strftime("%H:%M") >= "21:40"):
        out.append({"id": f"sum-{date}", "kind": "summary", "rs": bet})
    return out


def gensen_races(date: str, rs: list[dict], t: datetime) -> list[dict]:
    """これから発走する厳選レース（自信度A・オッズ込みの補正勝率で決まったもの）を発走順に。"""
    out = []
    for p in rs:
        pd = post_dt(date, p)
        b = p.get("blend") or {}
        if (p.get("confidence") == "A" and b.get("kind") == "オッズ込み" and not p["_score"]
                and pd and pd - t >= timedelta(minutes=20)):
            out.append(p)
    return sorted(out, key=lambda p: p["_race"].get("post_time") or "99")[:8]


def gensen_result_text(date: str, rs: list[dict]) -> str:
    """夜の全成績のスレッド（返信）用：その日の厳選レースの結果。"""
    a = [p for p in rs if p.get("confidence") == "A" and p["_score"] and p["_score"].get("stake")]
    if not a:
        return ""
    st, rt = sum(p["_score"]["stake"] for p in a), sum(p["_score"]["return"] for p in a)
    hit = sum(1 for p in a if p["_score"]["return"] > 0)
    head = f"【{fmt_md(date)} 厳選レース（自信度A）の結果】{len(a)}レース 的中{hit}・回収率{100 * rt / st:.0f}%"
    lines = []
    for p in sorted(a, key=lambda q: q["_race"].get("post_time") or ""):
        hon = (p.get("marks") or {}).get("◎")
        fin = p["_score"].get("honmei_finish") or "-"
        lines.append(f"{venue(p)}{rno(p)}R ◎{hon}{horse(p, hon)} {fin}着" + (f" 払戻{p['_score']['return']:,}円" if p["_score"]["return"] else ""))
    body = head
    for ln in lines:
        if x_len(body + "\n" + ln + "\n※各100円・外れも含む") > 280:
            break
        body += "\n" + ln
    return body + "\n※各100円・外れも含む"


# ---------------- 文面 ----------------
def x_len(s: str) -> int:
    """X の文字数（全角は2、URLは23）。"""
    s2 = re.sub(r"https?://\S+", "x" * 23, s)
    return sum(1 if (ord(c) <= 0x10FF or 0x2000 <= ord(c) <= 0x200D or 0x2010 <= ord(c) <= 0x201F or 0x2032 <= ord(c) <= 0x2037) else 2 for c in s2)


def fit_x(lines: list[str], tags: list[str], url: str | None) -> str:
    tail = (["", url] if url else [])
    body = list(lines)
    while True:
        t = "\n".join(body + ([" ".join(tags)] if tags else []) + tail)
        if x_len(t) <= 280:
            return t
        if len(body) > 3:  # まず本文の補足（短評など）を削り、ハッシュタグは残す
            body = body[:-1]
        elif tags:
            tags = tags[:-1]
        elif len(body) > 1:
            body = body[:-1]
        else:
            return t[:100]


def marks_line(p) -> str:
    m = p.get("marks", {})
    return "　".join(f"{k}{m[k]}{horse(p, m[k])}" for k in ("◎", "〇", "▲") if m.get(k) is not None)


def hits_line(sc) -> list[str]:
    out = []
    for h in sc.get("hits", [])[:3]:
        parts = h.split()
        if len(parts) >= 3:
            out.append(f"{parts[0]} {parts[1]}　{int(parts[2].rstrip('円')):,}円" if parts[2].rstrip("円").isdigit() else h)
    return out


def texts(date: str, c: dict, cfg: dict) -> dict:
    kind = c["kind"]
    if kind == "summary":
        rs = c["rs"]
        done = [p["_score"] for p in rs if p["_score"]]
        st, rt = sum(s["stake"] for s in done), sum(s["return"] for s in done)
        hit = sum(1 for s in done if s["return"] > 0)
        plus = sum(1 for s in done if s["return"] > s["stake"])
        best = max((p for p in rs if p["_score"]), key=lambda p: p["_score"]["return"] - p["_score"]["stake"], default=None)
        venues = "・".join(sorted({venue(p) for p in rs}))
        lines = [f"【{fmt_md(date)} AI予想の全成績】", f"{venues}の{len(done)}レース",
                 f"的中{hit}（うちプラス{plus}）／当日回収率{100 * rt / st:.1f}%" if st else "",
                 f"収支{rt - st:+,}円（各点100円・外れも含む）"]
        if best and best["_score"]["return"] > best["_score"]["stake"]:
            lines.append(f"最高：{venue(best)}{rno(best)}R 払戻{best['_score']['return']:,}円")
        lines.append(f"累計回収率{ledger_roi()}")
        lines = [x for x in lines if x]
        jra = any(str(p["race_id"]).startswith("jra_") for p in rs)
        local = any(not str(p["race_id"]).startswith("jra_") for p in rs)
        tags = ["#競馬予想"] + (["#中央競馬"] if jra else []) + (["#地方競馬"] if local else []) + ["#AI予想", "#回収率"]
        url = BASE_URL + f"/{date[:4]}/{date[4:6]}/{date[6:8]}/"
    elif kind == "gensen":
        lines = [f"【{fmt_md(date)} 今日の厳選レース】"]
        for p in c["ps"]:
            hon = p["marks"]["◎"]
            b = p.get("blend") or {}
            od = next((h.get("odds") for h in p["_race"].get("horses", []) or [] if h.get("number") == hon), None)
            ex = f"（補正勝率{b.get('honmei_pct'):.0f}%" + (f"・単勝{float(od):.1f}倍" if od else "") + "）" if b.get("honmei_pct") is not None else ""
            lines.append(f"{p['_race'].get('post_time') or ''} {venue(p)}{rno(p)}R ◎{hon}{horse(p, hon)}{ex}")
        lines.append("AIの◎が勝つ確率50%以上のレース。買い目は◎の単勝か複勝1点（発走前のオッズで変わることあり）")
        tags = ["#競馬予想", "#AI予想", "#厳選レース"]
        url = BASE_URL + f"/{date[:4]}/{date[4:6]}/{date[6:8]}/"
    elif kind == "picks":
        from build import honmei_value
        lines = [f"【{fmt_md(date)} 今日の勝負レース】"]
        for p in c["ps"]:
            hon = p["marks"]["◎"]
            wp, od, val = honmei_value(p)
            pt = p["_race"].get("post_time") or ""
            ex = f"（勝率{wp:.0f}%×単勝{od:.1f}倍）" if wp is not None and od else ""
            lines.append(f"{pt} {venue(p)}{rno(p)}R ◎{hon}{horse(p, hon)}{ex}")
        lines.append("的中しやすい順（自信度・◎の人気・中央を優先）。全レースの印・買い目はサイトで")
        tags = ["#競馬予想", "#AI予想", "#今日の勝負レース"]
        url = BASE_URL + f"/{date[:4]}/{date[4:6]}/{date[6:8]}/"
    else:
        p, sc = c["p"], c["p"]["_score"]
        g = c["p"]["_grade"]
        head = f"{venue(p)}{rno(p)}R {rname(p)}" + (f"（{g}）" if g and g not in rname(p) else "")
        if kind == "grade_pre" and c.get("eve"):
            pt = p["_race"].get("post_time") or ""
            lines = [f"【明日の重賞AI予想】{head}", f"{fmt_md(date)} {pt}発走（前日版・当日オッズで最終更新）", marks_line(p), f"自信度{p.get('confidence')}"]
            summ = nfkc(p.get("summary") or "")
            if summ:
                lines.append(summ[:60] + ("…" if len(summ) > 60 else ""))
        elif kind == "grade_pre":
            pt = p["_race"].get("post_time") or ""
            lines = [f"【重賞AI予想】{head}", f"{fmt_md(date)} {pt}発走", marks_line(p), f"自信度{p.get('confidence')}"]
            summ = nfkc(p.get("summary") or "")
            if summ:
                lines.append(summ[:60] + ("…" if len(summ) > 60 else ""))
        else:
            win = sc["return"] > 0
            lines = [(f"【的中】" if win else "【結果】") + head, marks_line(p)]
            if win:
                lines += hits_line(sc)
                lines.append(f"投資{sc['stake']:,}円→払戻{sc['return']:,}円（回収率{100 * sc['return'] / sc['stake']:.1f}%）")
            else:
                top = "-".join(str(x) for x in (sc.get("top3") or []) if x is not None)
                lines.append(f"結果{top}　不的中（投資{sc['stake']:,}円）")
        tags = ["#競馬予想", f"#{venue(p)}競馬", "#AI予想"] + (["#重賞"] if g else ["#的中"])
        if g:  # レース名のハッシュタグ（#天皇賞秋 など。検索から見られる）
            rt = re.sub(r"[()（）・\s'’]", "", rname(p))
            if rt:
                tags = [f"#{rt}"] + tags
        url = race_url(date, p)
    mode = cfg.get("x_url", "none")
    with_url = (mode == "all" or (mode == "graded" and kind.startswith("grade"))
                or (mode == "key" and (kind.startswith("grade") or kind in ("picks", "gensen", "summary"))))
    x_url = url if with_url else None
    x = fit_x(lines, tags, x_url)
    ig_lbl = "この日の全レースの予想と成績" if kind in ("summary", "picks", "gensen") else "このレースの全頭評価と買い目"
    ig = ("\n".join(lines) + f"\n\n{ig_lbl} → {url.replace('https://', '')}\n外れも含めた全レースの予想と成績はプロフィールのリンクから。\n※予想は情報提供です。馬券は20歳から。\n\n"
          + " ".join(tags + ["#競馬", "#競馬全頭ログ"]))
    return {"x": x, "instagram": ig, "url": url}


# ---------------- 画像の中身 ----------------
def card(date: str, c: dict) -> dict:
    kind = c["kind"]
    md = f"{int(date[:4])}.{int(date[4:6])}.{int(date[6:8])}"
    if kind == "summary":
        rs = c["rs"]
        done = [p["_score"] for p in rs if p["_score"]]
        st, rt = sum(s["stake"] for s in done), sum(s["return"] for s in done)
        hit = sum(1 for s in done if s["return"] > 0)
        plus = sum(1 for s in done if s["return"] > s["stake"])
        by_v = {}
        for p in rs:
            if p["_score"]:
                v = by_v.setdefault(venue(p), [0, 0, 0])
                v[0] += 1; v[1] += p["_score"]["stake"]; v[2] += p["_score"]["return"]
        rows = [f"{v}　{n}R　回収率{100 * r / s:.1f}%" for v, (n, s, r) in sorted(by_v.items(), key=lambda kv: -kv[1][0]) if s]
        return {"kind": kind, "label": "本日の全成績", "date": md, "head": f"{len(done)}レース 的中{hit}（プラス{plus}）",
                "sub": "外れも含む全予想・各点100円で集計", "rows": rows, "big": f"{100 * rt / st:.1f}%" if st else "―",
                "big_label": "当日回収率", "foot": f"収支{rt - st:+,}円　累計回収率{ledger_roi()}"}
    if kind == "gensen":
        lines, rows = [], []
        for p in c["ps"]:
            hon = p["marks"]["◎"]
            b = p.get("blend") or {}
            od = next((h.get("odds") for h in p["_race"].get("horses", []) or [] if h.get("number") == hon), None)
            lines.append(("◎", f"{venue(p)}{rno(p)}R {hon} {horse(p, hon)}"))
            rows.append(f"{p['_race'].get('post_time') or ''}発走" + (f"　補正勝率{b['honmei_pct']:.0f}%" if b.get("honmei_pct") is not None else "")
                        + (f"・単勝{float(od):.1f}倍" if od else ""))
        return {"kind": "grade_pre", "label": "今日の厳選レース", "date": md, "head": f"AIの◎が勝つ確率50%以上の{len(lines)}レース",
                "sub": "買い目は◎の単勝か複勝1点（朝のオッズ）", "lines": lines[:6], "rows": rows[:6]}
    if kind == "picks":
        from build import honmei_value
        lines, rows = [], []
        for p in c["ps"]:
            hon = p["marks"]["◎"]
            wp, od, val = honmei_value(p)
            lines.append(("◎", f"{venue(p)}{rno(p)}R {hon} {horse(p, hon)}"))
            rows.append(f"{p['_race'].get('post_time') or ''}発走　自信度{p.get('confidence')}" + (f"　{'補正勝率' if p.get('blend') else '想定勝率'}{wp:.0f}%・単勝{od:.1f}倍" if wp is not None and od else ""))
        return {"kind": "grade_pre", "label": "今日の勝負レース", "date": md, "head": f"AIの◎ 的中しやすい{len(lines)}レース",
                "sub": "自信度・◎の人気・中央を優先（朝のオッズ）", "lines": lines, "rows": rows}
    p = c["p"]
    sc, g = p["_score"], p["_grade"]
    m = p.get("marks", {})
    lines = [(k, f"{m[k]} {horse(p, m[k])}") for k in ("◎", "〇", "▲") if m.get(k) is not None]
    head = f"{venue(p)}{rno(p)}R {rname(p)}" + (f"（{g}）" if g and g not in rname(p) else "")
    r = p["_race"]
    sub = "・".join(x for x in [f"{r['post_time']}発走" if r.get("post_time") else "",
                                f"{r.get('surface') or ''}{r.get('distance')}m" if r.get("distance") else "",
                                f"{r.get('field')}頭" if r.get("field") else "", f"自信度{p.get('confidence')}"] if x)
    if kind == "grade_pre":
        return {"kind": kind, "label": "明日の重賞AI予想" if c.get("eve") else "重賞AI予想", "date": md, "head": head, "sub": sub, "lines": lines,
                "rows": [f"買い目 {len(p.get('bets', []))}点（各100円）"]}
    win = sc["return"] > 0
    top = "-".join(str(x) for x in (sc.get("top3") or []) if x is not None)
    return {"kind": "hit" if win else kind, "label": "的中" if win else "結果", "date": md, "head": head,
            "sub": f"1〜3着 {top}　◎は{sc.get('honmei_finish') or '-'}着", "lines": lines, "rows": hits_line(sc),
            "big": f"{100 * sc['return'] / sc['stake']:.1f}%", "big_label": "このレースの回収率",
            "foot": f"投資{sc['stake']:,}円 → 払戻{sc['return']:,}円"}


# ---------------- 状態 ----------------
def state_path(date: str) -> Path:
    return SOCIAL / date / "posts.json"


def load_state(date: str) -> dict:
    return load(state_path(date), {"date": date, "posts": {}}) or {"date": date, "posts": {}}


def save_state(date: str, st: dict) -> None:
    if not st.get("posts") and not state_path(date).exists():
        return  # 投稿が無い日はファイルを作らない
    state_path(date).parent.mkdir(parents=True, exist_ok=True)
    state_path(date).write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def ascii_name(pid: str) -> str:
    """画像ファイル名は英数字だけにする（URLに日本語があるとInstagramが画像を取得できない）。"""
    from build import VENUE_SLUG
    for k, v in sorted(VENUE_SLUG.items(), key=lambda kv: -len(kv[0])):
        pid = pid.replace(k, v)
    return re.sub(r"[^0-9A-Za-z_-]", "_", pid)


def thread_texts(date: str, c: dict) -> list[str]:
    """重賞予想のXスレッド（返信）用：評価点上位の要点を2〜3ツイートに。全成績には厳選レースの結果を1ツイート。"""
    if c["kind"] == "summary":
        t = gensen_result_text(date, c["rs"])
        return [t] if t else []
    if c["kind"] != "grade_pre":
        return []
    p = c["p"]
    hs = sorted([h for h in p.get("horses", []) if h.get("score") is not None], key=lambda h: -h["score"])[:6]
    mm = {}
    for k, v in p.get("marks", {}).items():
        for n in (v if isinstance(v, list) else [v]):
            if n is not None:
                mm[n] = k
    out, cur = [], f"【全頭評価の要点】{venue(p)}{rno(p)}R {rname(p)}（1/N）"
    for h in hs:
        line = f"\n{mm.get(h.get('number'), '')}{h.get('number')} {horse(p, h.get('number'))}　{h['score']}点" + (f"・勝率{h['win_pct']}%" if h.get("win_pct") is not None else "")
        cm = nfkc(h.get("comment") or "")
        if cm:
            line += f"\n{cm[:70]}{'…' if len(cm) > 70 else ''}"
        if x_len(cur + line) > 270:
            out.append(cur)
            cur = line.lstrip("\n")
        else:
            cur += line
    if cur:
        out.append(cur)
    out = out[:2]
    pace = nfkc(p.get("pace") or "")
    if pace:
        # X の文字数（全角=2）で 280 以内に収める。文字数の pace[:130] だと全角で約300になり 403 で弾かれる
        head, foot = "【展開】", "\n※予想は情報提供です。馬券は20歳から。"
        budget = 280 - x_len(head + foot)
        body = pace
        if x_len(body) > budget:
            while body and x_len(body + "…") > budget:
                body = body[:-1]
            body += "…"
        out.append(f"{head}{body}{foot}")
    out = out[:3]
    return [t.replace("（1/N）", f"（{i + 1}/{len(out)}）") if i == 0 else t for i, t in enumerate(out)]


def extra_cards(date: str, c: dict) -> list[dict]:
    """カルーセル用の2枚目以降（全成績の投稿だけ）：的中レース一覧と、明日の重賞。"""
    if c["kind"] != "summary":
        return []
    md = f"{int(date[:4])}.{int(date[4:6])}.{int(date[6:8])}"
    out = []
    hits = [p for p in c["rs"] if p["_score"] and p["_score"]["return"] > 0]
    hits.sort(key=lambda p: -(p["_score"]["return"] - p["_score"]["stake"]))
    if hits:
        rows = [f"{venue(p)}{rno(p)}R　払戻{p['_score']['return']:,}円（{100 * p['_score']['return'] / p['_score']['stake']:.0f}%）" for p in hits[:11]]
        out.append({"kind": "hit", "label": "的中レース", "date": md, "head": f"的中{len(hits)}レース（払戻額順）",
                    "sub": "各点100円・外れも含めた全成績はサイトで", "list": rows})
    nd = (datetime.strptime(date, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
    try:
        nxt = [p for p in races_of(nd) if p["_grade"] and p.get("confidence") != "見送り"]
    except Exception:  # noqa: BLE001
        nxt = []
    if nxt:
        p = sorted(nxt, key=lambda q: q["_race"].get("post_time") or "99")[0]
        cd = card(nd, {"kind": "grade_pre", "p": p, "eve": True})
        out.append(cd)
    return out


def prepare(date: str, cfg: dict) -> int:
    import social_img

    st = load_state(date)
    n = 0
    hits_made = sum(1 for e in st["posts"].values() if e.get("kind") == "hit")
    cands = sorted(candidates(date), key=lambda c: -(c.get("ret") or 0))  # 的中は払戻の大きい順に
    for c in cands:
        if c["id"] in st["posts"]:
            continue
        if c["kind"] == "hit":
            if hits_made >= HIT_MAX_PER_DAY:
                continue
            hits_made += 1
        img = SOCIAL / date / f"{ascii_name(c['id'])}.jpg"
        social_img.render(img, card(date, c))
        images = [f"/social/{date}/{ascii_name(c['id'])}.jpg"]
        for i, cd in enumerate(extra_cards(date, c), start=2):
            f2 = SOCIAL / date / f"{ascii_name(c['id'])}-{i}.jpg"
            social_img.render(f2, cd)
            images.append(f"/social/{date}/{f2.name}")
        t = texts(date, c, cfg)
        st["posts"][c["id"]] = {"kind": c["kind"], "image": images[0], "images": images, "x_text": t["x"], "x_thread": thread_texts(date, c),
                                "ig_caption": t["instagram"], "url": t["url"], "created": now().strftime("%Y-%m-%d %H:%M"),
                                "x": "pending" if cfg.get("x", True) else "off",
                                "instagram": "pending" if cfg.get("instagram", True) else "off"}
        n += 1
    save_state(date, st)
    return n


# ---------------- 投稿 ----------------
def has_x() -> bool:
    return all(os.environ.get(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"))


def has_ig() -> bool:
    return all(os.environ.get(k) for k in ("IG_USER_ID", "IG_ACCESS_TOKEN"))


def _x_auth():
    from requests_oauthlib import OAuth1
    return OAuth1(os.environ["X_API_KEY"], os.environ["X_API_SECRET"], os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_SECRET"])


def post_x(text: str, image: Path, more: list[Path] | None = None) -> str:
    import requests

    auth = _x_auth()
    mids = []
    for im in [image] + list(more or [])[:3]:
        with im.open("rb") as f:
            r = requests.post("https://api.x.com/2/media/upload", auth=auth, timeout=60,
                              files={"media": (im.name, f, "image/jpeg")}, data={"media_category": "tweet_image"})
        r.raise_for_status()
        mids.append((r.json().get("data") or {}).get("id") or r.json().get("media_id_string"))
    r = requests.post("https://api.x.com/2/tweets", auth=auth, timeout=60, json={"text": text, "media": {"media_ids": mids}})
    r.raise_for_status()
    return r.json()["data"]["id"]


def post_x_reply(text: str, reply_to: str) -> str:
    import requests

    r = requests.post("https://api.x.com/2/tweets", auth=_x_auth(), timeout=60, json={"text": text, "reply": {"in_reply_to_tweet_id": reply_to}})
    r.raise_for_status()
    return r.json()["data"]["id"]


def ig_accounts(tok: str) -> list[dict]:
    """トークンから投稿できるInstagramアカウント（id・ユーザー名）を調べる。IDは秘密情報ではない。"""
    import requests

    out = []
    if tok.startswith("IG"):
        r = requests.get("https://graph.instagram.com/v23.0/me", timeout=30, params={"fields": "user_id,username", "access_token": tok})
        if r.ok:
            j = r.json()
            out.append({"id": str(j.get("user_id") or j.get("id")), "username": j.get("username")})
        return out
    base = "https://graph.facebook.com/v23.0"
    r = requests.get(f"{base}/me/accounts", timeout=30, params={"fields": "instagram_business_account{id,username}", "access_token": tok})
    if r.ok:
        for pg in r.json().get("data", []):
            a = pg.get("instagram_business_account")
            if a:
                out.append({"id": str(a["id"]), "username": a.get("username")})
    if not out:  # システムユーザートークン：ビジネスポートフォリオ経由でIGアカウントをたどる
        PROBE.clear()
        bids = set(filter(None, [os.environ.get("META_BUSINESS_ID", "").strip()]))
        r = requests.get(f"{base}/me/businesses", timeout=30, params={"fields": "id,name", "access_token": tok})
        PROBE.append(f"me/businesses {r.status_code}")
        if r.ok:
            bids |= {b["id"] for b in r.json().get("data", [])}
        for b in sorted(bids):
            for ep in ("owned_instagram_accounts", "instagram_business_accounts", "instagram_accounts"):
                r = requests.get(f"{base}/{b}/{ep}", timeout=30, params={"fields": "id,username", "access_token": tok})
                PROBE.append(f"{ep} {r.status_code}" + ("" if r.ok else " " + str((r.json().get("error") or {}).get("message", ""))[:80]))
                if r.ok:
                    for x in r.json().get("data", []):
                        if x.get("id") and {"id": str(x["id"]), "username": x.get("username")} not in out:
                            out.append({"id": str(x["id"]), "username": x.get("username")})
            if out:
                break
    return out


PROBE: list[str] = []


def ig_user_id(tok: str) -> str:
    uid = str((load(SOCIAL / "config.json", {}) or {}).get("ig_user_id") or "").strip()  # IDは秘密ではないので設定ファイルを優先
    if not (uid.isdigit() and len(uid) >= 10):
        uid = os.environ.get("IG_USER_ID", "").strip()
    if uid.isdigit() and len(uid) >= 10:
        return uid
    accs = ig_accounts(tok)
    if accs:
        return accs[0]["id"]
    return uid


def _ig_wait(base: str, cid: str, tok: str) -> None:
    import requests
    for _ in range(10):  # 取り込み完了を待つ
        s = requests.get(f"{base}/{cid}", timeout=30, params={"fields": "status_code", "access_token": tok}).json()
        if s.get("status_code") in ("FINISHED", None):
            return
        if s.get("status_code") == "ERROR":
            raise RuntimeError(f"instagram container error: {s}")
        time.sleep(6)


def post_ig(caption: str, image_url: str, more: list[str] | None = None) -> str:
    import requests

    tok = os.environ["IG_ACCESS_TOKEN"].strip()
    uid = ig_user_id(tok)
    # Instagramログインのトークン（IGで始まる）は graph.instagram.com、
    # Facebook／統合ログインのトークン（EAAで始まる）は graph.facebook.com を使う
    base = "https://graph.instagram.com/v23.0" if tok.startswith("IG") else "https://graph.facebook.com/v23.0"
    urls = [image_url] + list(more or [])
    if len(urls) >= 2:  # カルーセル（複数枚）
        kids = []
        for u in urls[:10]:
            r = requests.post(f"{base}/{uid}/media", timeout=60, data={"image_url": u, "is_carousel_item": "true", "access_token": tok})
            if not r.ok:
                raise RuntimeError(f"item {r.status_code}: {str((r.json() if r.content else {}).get('error', r.text))[:400]}")
            kids.append(r.json()["id"])
        for k in kids:
            _ig_wait(base, k, tok)
        r = requests.post(f"{base}/{uid}/media", timeout=60, data={"media_type": "CAROUSEL", "children": ",".join(kids), "caption": caption, "access_token": tok})
        if not r.ok:
            raise RuntimeError(f"carousel {r.status_code}: {str((r.json() if r.content else {}).get('error', r.text))[:400]}")
        cid = r.json()["id"]
    else:
        r = requests.post(f"{base}/{uid}/media", timeout=60, data={"image_url": image_url, "caption": caption, "access_token": tok})
        if not r.ok:  # Instagram側の理由をそのまま残す（トークンは含まれない）
            raise RuntimeError(f"media {r.status_code}: {str((r.json() if r.content else {}).get('error', r.text))[:400]}")
        cid = r.json()["id"]
    _ig_wait(base, cid, tok)
    r = requests.post(f"{base}/{uid}/media_publish", timeout=60, data={"creation_id": cid, "access_token": tok})
    if not r.ok:
        raise RuntimeError(f"publish {r.status_code}: {str((r.json() if r.content else {}).get('error', r.text))[:400]}")
    return r.json()["id"]


def live(url: str) -> bool:
    import requests
    try:
        return requests.head(url, timeout=20, allow_redirects=True).status_code == 200
    except Exception:  # noqa: BLE001
        return False


def publish(date: str, dry: bool = False, only: str = "") -> int:
    st = load_state(date)
    n = 0
    # Instagram側でAPIが止められている間は送らない（失敗を重ねない）。毎回の確認で解除されたら自動で再開する
    ig_on = (load(SOCIAL / "config.json", {}) or {}).get("instagram", True)
    ig_blocked = (not only) and "API access blocked" in " ".join((load(SOCIAL / "status.json", {}) or {}).get("ig_probe") or [])  # 投稿IDを指定した手動テストでは送る
    for pid, e in st["posts"].items():
        if only and pid != only:
            continue
        todo = [k for k in ("x", "instagram") if e.get(k) in ("pending", "draft")]
        if not todo:
            continue
        img_url = BASE_URL + e["image"]
        try:
            age = now() - datetime.strptime(e["created"], "%Y-%m-%d %H:%M").replace(tzinfo=JST)
        except Exception:  # noqa: BLE001
            age = timedelta(0)
        if age > timedelta(hours=6):
            continue  # 古い下書きは出さない（鍵を設定した直後に過去分がまとめて出ないように）
        imgs = e.get("images") or [e["image"]]
        if not dry and not all(live(BASE_URL + u) for u in imgs):
            continue  # まだサイトに出ていない（次の公開後に出す）
        for k in todo:
            if k == "instagram" and not ig_on and not only:
                e[k] = "off"
                continue
            if k == "instagram" and ig_blocked and not dry:
                e["instagram_wait"] = "Instagram側でAPIが止められているため待機"
                continue
            ok = has_x() if k == "x" else has_ig()
            if dry or not ok:
                e[k] = "draft"
                continue
            try:
                if k == "x":
                    e["x_id"] = post_x(e["x_text"], ROOT / imgs[0].lstrip("/"), [ROOT / u.lstrip("/") for u in imgs[1:]])
                else:
                    e["instagram_id"] = post_ig(e["ig_caption"], BASE_URL + imgs[0], [BASE_URL + u for u in imgs[1:]])
                e[k] = "posted"
                e[f"{k}_at"] = now().strftime("%Y-%m-%d %H:%M")
                n += 1
                if k == "x" and e.get("x_thread") and not e.get("x_thread_ids"):
                    ids, prev = [], e["x_id"]
                    for t_ in e["x_thread"]:
                        try:
                            prev = post_x_reply(t_, prev)
                            ids.append(prev)
                        except Exception as ex2:  # noqa: BLE001
                            e["x_thread_error"] = str(ex2)[:200]
                            break
                    e["x_thread_ids"] = ids
            except Exception as ex:  # noqa: BLE001
                e[f"{k}_error"] = str(ex)[:300]
                e[f"{k}_tries"] = e.get(f"{k}_tries", 0) + 1
                if e[f"{k}_tries"] >= 3:
                    e[k] = "failed"
                print(f"{pid} {k} error: {ex}")
    save_state(date, st)
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=now().strftime("%Y%m%d"))
    ap.add_argument("--prepare-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="", help="この投稿IDだけ出す（手動テスト用。準備はしない）")
    a = ap.parse_args()
    cfg = load(SOCIAL / "config.json", {}) or {}
    posted = 0 if a.prepare_only else publish(a.date, a.dry_run, a.only)
    made = 0 if a.only else prepare(a.date, cfg)
    status = {"x_keys": has_x(), "ig_keys": has_ig()}  # 鍵の有無だけ（中身は書かない）
    if not cfg.get("instagram", True):
        status["ig"] = "off"  # 設定で止めている間は確認も送らない（social/config.json の instagram を true に戻すと再開）
    elif has_ig():
        try:
            tok = os.environ["IG_ACCESS_TOKEN"].strip()
            status["ig_token_type"] = "instagram" if tok.startswith("IG") else "facebook"
            status["ig_id_ok"] = os.environ.get("IG_USER_ID", "").strip().isdigit() and len(os.environ.get("IG_USER_ID", "").strip()) >= 10
            status["ig_accounts"] = ig_accounts(tok)
            if PROBE:
                status["ig_probe"] = PROBE[:]
        except Exception as ex:  # noqa: BLE001
            status["ig_check_error"] = str(ex)[:200]
    if has_x():  # どのアカウントに投稿しているか（1日1回だけ確かめる。中身は公開情報だけ）
        old = load(SOCIAL / "status.json", {}) or {}
        today = now().strftime("%Y%m%d")
        if old.get("x_checked") == today and old.get("x_user"):
            status["x_user"], status["x_checked"] = old["x_user"], today
        else:
            try:
                import requests
                r = requests.get("https://api.x.com/2/users/me", auth=_x_auth(), timeout=30,
                                 params={"user.fields": "protected,public_metrics,created_at,verified"})
                if r.ok:
                    u = r.json().get("data", {})
                    status["x_user"] = {"username": u.get("username"), "name": u.get("name"), "protected": u.get("protected"),
                                        "followers": (u.get("public_metrics") or {}).get("followers_count"),
                                        "tweets": (u.get("public_metrics") or {}).get("tweet_count")}
                else:
                    status["x_user"] = {"error": f"{r.status_code} {r.text[:150]}"}
                status["x_checked"] = today
            except Exception as ex:  # noqa: BLE001
                status["x_user"] = {"error": str(ex)[:150]}
    sp = SOCIAL / "status.json"
    if load(sp, {}) != status:
        sp.write_text(json.dumps(status), encoding="utf-8")
    print(json.dumps({"posted": posted, "prepared": made, **status}))
