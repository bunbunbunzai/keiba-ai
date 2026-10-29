"""手元で1回だけ実行：生成した元画像（site/assets/src/）から、サイトで使うサイズの画像を作る。

  logo-mark.png   → assets/logo-mark.png（512px）, logo-mark-96.png（ヘッダー用）, favicon.png（48px）, apple-touch-icon.png（180px・白背景）
  og-base.png     → assets/og-base.png（1200x630に切り出し。OGP画像の背景。公開はしない）
  col-<slug>.png  → assets/col-<slug>.jpg（幅1200のJPEG。コラムの挿絵）
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
    for f in SRC.glob("col-*.png"):
        im = Image.open(f).convert("RGB")
        im = im.resize((1200, round(im.height * 1200 / im.width)), Image.LANCZOS)
        im.save(OUT / f"{f.stem}.jpg", "JPEG", quality=82, optimize=True, progressive=True)
    for f in sorted(OUT.glob("*.*")):
        print(f.name, f.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
