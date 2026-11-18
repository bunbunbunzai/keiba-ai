"""古い作業用データを消して、リポジトリが大きくなり続けないようにする（毎晩の集計のあとに実行）。

- data/raw/<日付>/：取得したままのHTML（解析器づくりと検証用）。解析済みのデータは data/races・data/results に残るので、直近 RAW_DAYS 日分だけ残す。
- social/<日付>/ の画像：投稿済みの画像。サイトに出すのは直近14日分だけなので、IMG_DAYS 日より前は画像だけ消す（投稿の記録 posts.json は残す）。
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timedelta, timezone

from common import DATA_DIR

ROOT = DATA_DIR.parent
RAW_DAYS = 14
IMG_DAYS = 30
JST = timezone(timedelta(hours=9))


def main() -> None:
    today = datetime.now(JST)
    raw_limit = (today - timedelta(days=RAW_DAYS)).strftime("%Y%m%d")
    img_limit = (today - timedelta(days=IMG_DAYS)).strftime("%Y%m%d")
    n_raw = n_img = 0
    for d in sorted((DATA_DIR / "raw").glob("*")):
        if d.is_dir() and re.fullmatch(r"\d{8}", d.name) and d.name < raw_limit:
            shutil.rmtree(d)
            n_raw += 1
    for d in sorted((ROOT / "social").glob("*")):
        if d.is_dir() and re.fullmatch(r"\d{8}", d.name) and d.name < img_limit:
            for f in d.iterdir():
                if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                    f.unlink()
                    n_img += 1
    print(f"pruned: raw {n_raw}日分, social画像 {n_img}枚")


if __name__ == "__main__":
    main()
