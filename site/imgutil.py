"""画像の小さな共通処理（build.py と column.py から使う）。"""
from __future__ import annotations

from pathlib import Path


def webp_variants(src: Path, dest_dir: Path, widths=(800, 1600)) -> list[tuple[int, str]]:
    """JPEG/PNG から WebP の縮小版を作る（作成済みで元画像より新しければ作り直さない）。[(幅, ファイル名)]"""
    from PIL import Image

    out = []
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        im = None
        for w in widths:
            name = f"{src.stem}-{w}.webp"
            dst = dest_dir / name
            if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
                if im is None:
                    im = Image.open(src).convert("RGB")
                if im.width < w:
                    continue
                im.resize((w, round(im.height * w / im.width)), Image.LANCZOS).save(dst, "WEBP", quality=72, method=5)
            out.append((w, name))
    except Exception:  # noqa: BLE001
        return []
    return out
