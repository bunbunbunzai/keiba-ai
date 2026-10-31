"""X・Instagram への自動投稿。

投稿するもの（1レース・1日につき1回だけ）
- hit       ：回収率100%以上の的中（重賞は grade_res にまとめる）
- grade_pre ：重賞の予想（発走の10〜120分前）
- grade_res ：重賞の結果（的中・不的中とも）
- summary   ：その日の全成績（全レース確定後、または21:40以降）

流れ（pages のデプロイ後に毎回呼ばれる）
1. publish：画像が公開URLで見られる「ready」の投稿を X・Instagram に出す（鍵が無ければ draft のまま）
2. prepare：新しく条件を満たした投稿の画像と文面を social/<日付>/ に作る（→ commit・push・サイト再公開 → 次の回で publish）

設定 social/config.json：{"x": true, "instagram": true, "x_url": "none" | "graded" | "all"}
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
            if sc and sc["stake"]:
                out.append({"id": f"res-{p['race_id']}", "kind": "grade_res", "p": p})
        elif sc and sc["stake"] and sc["return"] >= sc["stake"]:
            out.append({"id": f"hit-{p['race_id']}", "kind": "hit", "p": p})
    bet = [p for p in rs if p.get("confidence") != "見送り"]
    done = [p for p in bet if p["_score"]]
    if bet and done and (len(done) == len(bet) or t.strftime("%Y%m%d") > date or t.strftime("%H:%M") >= "21:40"):
        out.append({"id": f"sum-{date}", "kind": "summary", "rs": bet})
    return out


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
        if tags:
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
        tags = ["#競馬予想", "#地方競馬", "#AI予想", "#回収率"]
        url = BASE_URL + f"/{date[:4]}/{date[4:6]}/{date[6:8]}/"
    else:
        p, sc = c["p"], c["p"]["_score"]
        g = c["p"]["_grade"]
        head = f"{venue(p)}{rno(p)}R {rname(p)}" + (f"（{g}）" if g and g not in rname(p) else "")
        if kind == "grade_pre":
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
        url = race_url(date, p)
    mode = cfg.get("x_url", "none")
    x_url = url if mode == "all" or (mode == "graded" and kind.startswith("grade")) else None
    x = fit_x(lines, tags, x_url)
    ig = "\n".join(lines) + "\n\n外れも含めた全レースの予想と成績はプロフィールのリンクから。\n※予想は情報提供です。馬券は20歳から。\n\n" + " ".join(tags + ["#競馬", "#AI競馬ログ"])
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
        return {"kind": kind, "label": "重賞AI予想", "date": md, "head": head, "sub": sub, "lines": lines,
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
    state_path(date).parent.mkdir(parents=True, exist_ok=True)
    state_path(date).write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def prepare(date: str, cfg: dict) -> int:
    import social_img

    st = load_state(date)
    n = 0
    for c in candidates(date):
        if c["id"] in st["posts"]:
            continue
        img = SOCIAL / date / f"{c['id']}.jpg"
        social_img.render(img, card(date, c))
        t = texts(date, c, cfg)
        st["posts"][c["id"]] = {"kind": c["kind"], "image": f"/social/{date}/{c['id']}.jpg", "x_text": t["x"],
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


def post_x(text: str, image: Path) -> str:
    import requests
    from requests_oauthlib import OAuth1

    auth = OAuth1(os.environ["X_API_KEY"], os.environ["X_API_SECRET"], os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_SECRET"])
    with image.open("rb") as f:
        r = requests.post("https://api.x.com/2/media/upload", auth=auth, timeout=60,
                          files={"media": (image.name, f, "image/jpeg")}, data={"media_category": "tweet_image"})
    r.raise_for_status()
    mid = (r.json().get("data") or {}).get("id") or r.json().get("media_id_string")
    r = requests.post("https://api.x.com/2/tweets", auth=auth, timeout=60, json={"text": text, "media": {"media_ids": [mid]}})
    r.raise_for_status()
    return r.json()["data"]["id"]


def post_ig(caption: str, image_url: str) -> str:
    import requests

    base = "https://graph.instagram.com/v23.0"
    uid, tok = os.environ["IG_USER_ID"], os.environ["IG_ACCESS_TOKEN"]
    r = requests.post(f"{base}/{uid}/media", timeout=60, data={"image_url": image_url, "caption": caption, "access_token": tok})
    r.raise_for_status()
    cid = r.json()["id"]
    for _ in range(10):  # 取り込み完了を待つ
        s = requests.get(f"{base}/{cid}", timeout=30, params={"fields": "status_code", "access_token": tok}).json()
        if s.get("status_code") in ("FINISHED", None):
            break
        if s.get("status_code") == "ERROR":
            raise RuntimeError(f"instagram container error: {s}")
        time.sleep(6)
    r = requests.post(f"{base}/{uid}/media_publish", timeout=60, data={"creation_id": cid, "access_token": tok})
    r.raise_for_status()
    return r.json()["id"]


def live(url: str) -> bool:
    import requests
    try:
        return requests.head(url, timeout=20, allow_redirects=True).status_code == 200
    except Exception:  # noqa: BLE001
        return False


def publish(date: str, dry: bool = False) -> int:
    st = load_state(date)
    n = 0
    for pid, e in st["posts"].items():
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
        if not dry and not live(img_url):
            continue  # まだサイトに出ていない（次の公開後に出す）
        for k in todo:
            ok = has_x() if k == "x" else has_ig()
            if dry or not ok:
                e[k] = "draft"
                continue
            try:
                e[f"{k}_id"] = post_x(e["x_text"], SOCIAL / date / f"{pid}.jpg") if k == "x" else post_ig(e["ig_caption"], img_url)
                e[k] = "posted"
                e[f"{k}_at"] = now().strftime("%Y-%m-%d %H:%M")
                n += 1
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
    a = ap.parse_args()
    cfg = load(SOCIAL / "config.json", {}) or {}
    posted = 0 if a.prepare_only else publish(a.date, a.dry_run)
    made = prepare(a.date, cfg)
    print(json.dumps({"posted": posted, "prepared": made, "x_keys": has_x(), "ig_keys": has_ig()}))
