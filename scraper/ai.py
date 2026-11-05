"""Anthropic API の薄い呼び出し（回顧・重賞記事の自動生成用）。

鍵は環境変数 ANTHROPIC_API_KEY（GitHub Secrets）。無ければ何もしない（None を返す）。
モデルは環境変数で差し替えられる：
  ANTHROPIC_MODEL_REVIEW  （既定 claude-haiku-5-5：1〜2文の回顧。安い）
  ANTHROPIC_MODEL_ARTICLE （既定 claude-sonnet-5-5：重賞記事。週十数本なので品質優先）
使った量は data/ai_usage.jsonl に1行ずつ記録する（費用の見積もり用）。
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

from common import DATA_DIR

API = "https://api.anthropic.com/v1/messages"
JST = timezone(timedelta(hours=9))
# 期間限定の格上げ（クレジットが余っている期間だけ上位モデルを使う。期限を過ぎると自動で元に戻る）
BOOST_UNTIL = "2026-11-12"
_boost = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d") <= BOOST_UNTIL
MODELS = {
    "review": os.environ.get("ANTHROPIC_MODEL_REVIEW", "claude-sonnet-5-5" if _boost else "claude-haiku-5-5"),
    "article": os.environ.get("ANTHROPIC_MODEL_ARTICLE", "claude-opus-5-5" if _boost else "claude-sonnet-5-5"),
    "analysis": os.environ.get("ANTHROPIC_MODEL_ANALYSIS", "claude-opus-5-5"),
    "bulk": os.environ.get("ANTHROPIC_MODEL_BULK", "claude-haiku-5-5"),  # 馬の寸評など大量に作るもの
}


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def ask(kind: str, system: str, user: str, max_tokens: int = 2000, temperature: float = 0.3) -> str | None:
    """max_tokens はモデル内部の思考分も含むので、出力の見込みより大きめに取る。"""
    """1往復。失敗は最大3回まで間隔を空けて再試行し、だめなら None。"""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    model = MODELS[kind]
    body = {"model": model, "max_tokens": max_tokens, "system": system,  # temperature はこの世代のモデルでは指定不可
            "messages": [{"role": "user", "content": user}]}
    for attempt in range(3):
        try:
            r = requests.post(API, json=body, timeout=90,
                              headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
            if r.status_code in (429, 500, 502, 503, 529):
                print(f"api {r.status_code} (retry {attempt + 1}):", r.text[:200], flush=True)
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code >= 400:
                print(f"api {r.status_code}:", r.text[:300], flush=True)
                FAILS[0] += 1
                return None
            FAILS[0] = 0
            j = r.json()
            text = "".join(c.get("text", "") for c in j.get("content", []) if c.get("type") == "text").strip()
            if not text:
                print("api empty text: stop_reason=", j.get("stop_reason"), "usage=", j.get("usage"), flush=True)
            u = j.get("usage", {})
            _log({"at": datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "kind": kind, "model": model,
                  "in": u.get("input_tokens"), "out": u.get("output_tokens")})
            return text
        except requests.RequestException as e:  # noqa: PERF203
            print("api error:", e, flush=True)
            time.sleep(5 * (attempt + 1))
    FAILS[0] += 1
    return None


FAILS = [0]  # 連続失敗の回数。3回続いたら呼び出し側は打ち切る


def too_many_failures() -> bool:
    return FAILS[0] >= 3


def _log(rec: dict) -> None:
    try:
        p = DATA_DIR / "ai_usage.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def usage_summary(days: int = 31) -> dict:
    """直近 days 日の呼び出し回数とトークン数（費用の目安用）。"""
    p = DATA_DIR / "ai_usage.jsonl"
    out: dict = {}
    if not p.exists():
        return out
    since = (datetime.now(JST) - timedelta(days=days)).strftime("%Y-%m-%d")
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (r.get("at") or "") < since:
            continue
        k = out.setdefault(r.get("kind"), {"calls": 0, "in": 0, "out": 0})
        k["calls"] += 1
        k["in"] += r.get("in") or 0
        k["out"] += r.get("out") or 0
    return out


def ask_with_search(kind: str, system: str, user: str, max_tokens: int = 16000, max_searches: int = 5) -> dict | None:
    """Web検索つきで1回答える。{"text", "sources": [{"url","title"}], "searches"} を返す。失敗は None。"""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    model = MODELS[kind]
    body = {"model": model, "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_searches,
                       "user_location": {"type": "approximate", "country": "JP", "timezone": "Asia/Tokyo"}}]}
    content, searches, tin, tout = [], 0, 0, 0
    for turn in range(4):
        try:
            r = requests.post(API, json=body, timeout=300,
                              headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        except requests.RequestException as e:
            print("api error:", e, flush=True)
            FAILS[0] += 1
            return None
        if r.status_code >= 400:
            print(f"api {r.status_code}:", r.text[:300], flush=True)
            FAILS[0] += 1
            return None
        j = r.json()
        content += j.get("content", [])
        u = j.get("usage", {})
        tin += u.get("input_tokens") or 0
        tout += u.get("output_tokens") or 0
        searches += (u.get("server_tool_use") or {}).get("web_search_requests") or 0
        if j.get("stop_reason") != "pause_turn":
            break
        body["messages"] = body["messages"] + [{"role": "assistant", "content": j.get("content", [])}]
    FAILS[0] = 0
    _log({"at": datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "kind": kind, "model": model, "in": tin, "out": tout, "searches": searches})
    texts = [c for c in content if c.get("type") == "text"]
    results = []
    for c in content:
        if c.get("type") == "web_search_tool_result" and isinstance(c.get("content"), list):
            results += [{"url": x.get("url"), "title": (x.get("title") or "")[:100]} for x in c["content"] if x.get("url")]
    seen, sources = set(), []
    for t in texts:
        for c in t.get("citations") or []:
            if c.get("url") and c["url"] not in seen:
                seen.add(c["url"])
                sources.append({"url": c["url"], "title": (c.get("title") or c["url"])[:100]})
    text = "".join(t.get("text", "") for t in texts).strip()
    text = re.sub(r'[<(]?cite index="[^"]*">', "", text).replace("</cite>", "")  # 本文に紛れた引用タグは消す
    return {"text": text, "sources": sources[:8], "results": results, "searches": searches}


def parse_json(text: str, kind: str = "{"):
    """文章の中から最初のJSON（オブジェクトか配列）を取り出す。後ろに余計な文章や2つ目のJSONがあっても無視する。"""
    i = text.find(kind)
    if i < 0:
        raise ValueError("JSONが見つからない")
    obj, _ = json.JSONDecoder().raw_decode(text[i:])
    return obj
