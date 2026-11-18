"""画像の小さな共通処理（build.py と column.py から使う）。"""
from __future__ import annotations

import hashlib
import os
import shutil
import time
from pathlib import Path

# 作った画像の作り置き。サイトの生成は毎回 _site を空にするので、中身が変わっていない画像（レースごとの共有画像、WebP の縮小版）は
# ここから写すだけにする（1回の生成で1,300枚あまりを描き直していた）。公開処理では日ごとに保存・復元される（.github/workflows/pages.yml）。
CACHE = Path(os.environ.get("IMG_CACHE") or Path(__file__).resolve().parent.parent / ".imgcache")
KEEP_DAYS = 45


def cached(out: Path, key_parts: tuple, make) -> None:
    """key_parts が同じなら作り置きを写す。無ければ make(out) で作って、作り置きにも置く。"""
    key = hashlib.sha1(repr(key_parts).encode("utf-8")).hexdigest()
    hit = CACHE / key[:2] / (key + out.suffix)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        if hit.exists():
            shutil.copyfile(hit, out)
            os.utime(hit, None)  # 使った印（古いものを消すときの目安）
            return
    except OSError:
        pass
    make(out)
    try:
        hit.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out, hit)
    except OSError:
        pass


def prune() -> int:
    """KEEP_DAYS 日使われていない作り置きを消す。"""
    n, limit = 0, time.time() - KEEP_DAYS * 86400
    if CACHE.exists():
        for f in CACHE.glob("*/*"):
            try:
                if f.stat().st_mtime < limit:
                    f.unlink()
                    n += 1
            except OSError:
                pass
    return n


def file_sig(p: Path) -> str:
    try:
        st = p.stat()
        return f"{p.name}:{st.st_size}:{hashlib.sha1(p.read_bytes()).hexdigest()[:16]}"
    except OSError:
        return ""


def webp_variants(src: Path, dest_dir: Path, widths=(800, 1600)) -> list[tuple[int, str]]:
    """JPEG/PNG から WebP の縮小版を作る（作成済みで元画像より新しければ作り直さない）。[(幅, ファイル名)]"""
    from PIL import Image

    out = []
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        im, sig = None, ""
        for w in widths:
            name = f"{src.stem}-{w}.webp"
            dst = dest_dir / name
            if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
                if im is None:
                    im = Image.open(src).convert("RGB")
                if im.width < w:
                    continue
                def _mk(o, im=im, w=w):
                    im.resize((w, round(im.height * w / im.width)), Image.LANCZOS).save(o, "WEBP", quality=72, method=5)
                sig = sig or file_sig(src)
                cached(dst, ("webp", sig, w), _mk)
            out.append((w, name))
    except Exception:  # noqa: BLE001
        return []
    return out
