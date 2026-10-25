"""共通処理：礼儀正しいHTTP取得と、生HTMLの保存。"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests

USER_AGENT = (
    "keiba-ai-research/0.1 (+https://github.com/bunbunbunzai/keiba-ai; "
    "personal non-commercial research; contact via GitHub issues)"
)
DATA_DIR = Path(os.environ.get("KEIBA_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))


class PoliteSession:
    """ホストごとに最小間隔を守ってアクセスするセッション。"""

    def __init__(self, min_interval: float, encoding: str | None = None):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ja"})
        self.min_interval = min_interval
        self.encoding = encoding
        self._last = 0.0

    def _wait(self):
        dt = time.monotonic() - self._last
        if dt < self.min_interval:
            time.sleep(self.min_interval - dt)
        self._last = time.monotonic()

    def get(self, url: str, **kw) -> requests.Response:
        self._wait()
        r = self.s.get(url, timeout=30, **kw)
        if self.encoding:
            r.encoding = self.encoding
        r.raise_for_status()
        return r

    def post(self, url: str, data: dict, **kw) -> requests.Response:
        self._wait()
        r = self.s.post(url, data=data, timeout=30, **kw)
        if self.encoding:
            r.encoding = self.encoding
        r.raise_for_status()
        return r


def save_raw(kind: str, date: str, name: str, html: str) -> Path:
    """data/raw/<date>/<kind>/<name>.html に保存（解析器づくりと検証用）。"""
    p = DATA_DIR / "raw" / date / kind / f"{name}.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")
    return p


def save_json(rel: str, obj) -> Path:
    p = DATA_DIR / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def short_hash(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:8]
