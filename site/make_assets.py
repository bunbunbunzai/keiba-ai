"""手元で1回だけ実行：生成した元画像（site/assets/src/）から、サイトで使うサイズの画像を作る。

  logo-mark.png   → assets/logo-mark.png（512px）, logo-mark-96.png（ヘッダー用）, favicon.png（48px）, apple-touch-icon.png（180px・白背景）
  og-base.png     → assets/og-base.png（1200x630に切り出し。OGP画像の背景。公開はしない）
  col-<slug>.png  → assets/col-<slug>.jpg（1200x800のJPEG。コラムの挿絵）と col-<slug>-s.jpg（一覧用の小さい版）
  g-<slug>.png    → 重賞記事の挿絵（col と同じ2サイズ）と ban-g-<slug>.jpg（重賞ページの見出し）
  ban-<slug>.png  → assets/ban-<slug>.jpg（ページ見出し、1600x580）
  sns-<kind>.png  → assets/sns-<kind>.jpg（SNS投稿画像の背景。公開はしない）
  zk-<pose>.png   → assets/zk-<pose>.png（全頭くんのポーズ違い、透過192px・64色）
"""
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SRC = HERE / "assets" / "src"
OUT = HERE / "assets"


def trim(im: Image.Image, pad: float = 0.06) -> Image.Image:
    """透過の余白を詰めて正方形にする。"""
    bbox = im.getchannel("A").getbbox() if im.mode == "RGBA" else None
    if bbox:
        im = im.crop(bbox)
    s = round(max(im.size) * (1 + 2 * pad))
    sq = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sq.paste(im, ((s - im.width) // 2, (s - im.height) // 2), im if im.mode == "RGBA" else None)
    return sq


def main() -> None:
    lm = SRC / "logo-mark.png"
    if lm.exists():
        m = trim(Image.open(lm).convert("RGBA"))
        for name, size in (("logo-mark.png", 512), ("logo-mark-96.png", 96), ("favicon.png", 48)):
            m.resize((size, size), Image.LANCZOS).save(OUT / name, optimize=True)
        bg = Image.new("RGBA", (180, 180), (255, 255, 255, 255))
        icon = m.resize((150, 150), Image.LANCZOS)
        bg.alpha_composite(icon, (15, 15))
        bg.convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)
    ob = SRC / "og-base.png"
    if ob.exists():
        im = Image.open(ob).convert("RGB")
        r = max(1200 / im.width, 630 / im.height)
        im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
        x, y = (im.width - 1200) // 2, (im.height - 630) // 2
        im.crop((x, y, x + 1200, y + 630)).save(OUT / "og-base.png", optimize=True)
    for f in SRC.glob("ban-*.png"):  # ページ見出しの挿絵（1600px幅、11:4に切り出し）
        im = Image.open(f).convert("RGB")
        im = im.resize((1600, round(im.height * 1600 / im.width)), Image.LANCZOS)
        if im.height > 580:
            y = (im.height - 580) // 2
            im = im.crop((0, y, 1600, y + 580))
        im.save(OUT / f"{f.stem}.jpg", "JPEG", quality=80, optimize=True, progressive=True)
    for f in [*SRC.glob("col-*.png"), *SRC.glob("g-*.png")]:  # コラム・重賞記事の挿絵（3:2）＋一覧用の小さい版
        im = Image.open(f).convert("RGB")
        r = max(1200 / im.width, 800 / im.height)
        im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
        x, y = (im.width - 1200) // 2, (im.height - 800) // 2
        im = im.crop((x, y, x + 1200, y + 800))
        im.save(OUT / f"{f.stem}.jpg", "JPEG", quality=70, optimize=True, progressive=True)
        im.resize((360, 240), Image.LANCZOS).save(OUT / f"{f.stem}-s.jpg", "JPEG", quality=78, optimize=True, progressive=True)
        if f.stem.startswith("g-"):  # 重賞ページの見出し用（11:4）
            b = im.resize((1600, 1067), Image.LANCZOS).crop((0, 243, 1600, 823))
            b.save(OUT / f"ban-{f.stem}.jpg", "JPEG", quality=80, optimize=True, progressive=True)
    for f in SRC.glob("sns-*.png"):  # SNS投稿画像の背景（1080x1350）。公開フォルダには出さない
        im = Image.open(f).convert("RGB")
        r = max(1080 / im.width, 1350 / im.height)
        im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
        x, y = (im.width - 1080) // 2, (im.height - 1350) // 2
        im.crop((x, y, x + 1080, y + 1350)).save(OUT / f"{f.stem}.jpg", "JPEG", quality=88, optimize=True)
    for f in SRC.glob("zk-*.png"):  # 全頭くんのポーズ違い（透過PNG、256px）
        if f.stem in ("zk-normal", "zk-think", "zk-joy", "zk-sorry"):
            continue
        m = trim(Image.open(f).convert("RGBA"), 0.02).resize((192, 192), Image.LANCZOS)
        m.quantize(colors=64, method=Image.Quantize.FASTOCTREE).save(OUT / f"{f.stem}.png", optimize=True)
    for f in OUT.glob("col-*.jpg"):  # 元画像が手元に無い既存の挿絵にも、一覧用の小さい版を作る
        if f.stem.endswith("-s") or (OUT / f"{f.stem}-s.jpg").exists():
            continue
        im = Image.open(f).convert("RGB")
        r = max(360 / im.width, 240 / im.height)
        im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
        x, y = (im.width - 360) // 2, (im.height - 240) // 2
        im.crop((x, y, x + 360, y + 240)).save(OUT / f"{f.stem}-s.jpg", "JPEG", quality=78, optimize=True, progressive=True)
    for f in sorted(OUT.glob("*.*")):
        print(f.name, f.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
