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
import time
from datetime import datetime, timedelta, timezone

import requests

from common import DATA_DIR

API = "https://api.anthropic.com/v1/messages"
JST = timezone(timedelta(hours=9))
MODELS = {
    "review": os.environ.get("ANTHROPIC_MODEL_REVIEW", "claude-haiku-5-5"),
    "article": os.environ.get("ANTHROPIC_MODEL_ARTICLE", "claude-sonnet-5-5"),
}


def enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def ask(kind: str, system: str, user: str, max_tokens: int = 400, temperature: float = 0.3) -> str | None:
    """1往復。失敗は最大3回まで間隔を空けて再試行し、だめなら None。"""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    model = MODELS[kind]
    body = {"model": model, "max_tokens": max_tokens, "temperature": temperature, "system": system,
            "messages": [{"role": "user", "content": user}]}
    for attempt in range(3):
        try:
            r = requests.post(API, json=body, timeout=120,
                              headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
            if r.status_code in (429, 500, 502, 503, 529):
                time.sleep(10 * (attempt + 1))
                continue
            r.raise_for_status()
            j = r.json()
            text = "".join(c.get("text", "") for c in j.get("content", []) if c.get("type") == "text").strip()
            u = j.get("usage", {})
            _log({"at": datetime.now(JST).strftime("%Y-%m-%d %H:%M"), "kind": kind, "model": model,
                  "in": u.get("input_tokens"), "out": u.get("output_tokens")})
            return text
        except requests.RequestException as e:  # noqa: PERF203
            print("api error:", e)
            time.sleep(10 * (attempt + 1))
    return None


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
