"""SNSで共有されたときの画像（OGP画像、1200x630）を作る。

- レースごと：場・R・レース名、◎〇▲、自信度、確定していれば的中／不的中と回収率
- サイト共通：サイト名と説明
背景は site/assets/og-base.png（左側を文字用の余白にしたイラスト）。無ければ無地。
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONT_B = HERE / "fonts" / "NotoSansJP-Bold.otf"
FONT_R = HERE / "fonts" / "NotoSansJP-Regular.otf"
BASE = HERE / "assets" / "og-base.png"
W, H = 1200, 630
GREEN = (31, 111, 74)
INK = (29, 29, 27)
MUT = (95, 99, 92)
CREAM = (250, 248, 240)
RED = (176, 58, 46)
_cache: dict = {}


def font(size: int, bold: bool = True):
    k = (size, bold)
    if k not in _cache:
        _cache[k] = ImageFont.truetype(str(FONT_B if bold else FONT_R), size)
    return _cache[k]


def canvas() -> Image.Image:
    if "base" not in _cache:
        if BASE.exists():
            im = Image.open(BASE).convert("RGB")
            r = max(W / im.width, H / im.height)
            im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
            x, y = (im.width - W) // 2, (im.height - H) // 2
            im = im.crop((x, y, x + W, y + H))
        else:
            im = Image.new("RGB", (W, H), (233, 240, 233))
        # 左側に文字用のパネル
        panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(panel)
        d.rounded_rectangle((36, 36, 760, H - 36), radius=28, fill=CREAM + (238,))
        im = Image.alpha_composite(im.convert("RGBA"), panel).convert("RGB")
        _cache["base"] = im
    return _cache["base"].copy()


def fit(d: ImageDraw.ImageDraw, text: str, size: int, maxw: int, bold=True):
    while size > 18 and d.textlength(text, font=font(size, bold)) > maxw:
        size -= 2
    return font(size, bold)


def header(d: ImageDraw.ImageDraw, sub: str) -> None:
    d.text((76, 66), "AI競馬ログ", font=font(30), fill=GREEN)
    d.text((76 + d.textlength("AI競馬ログ", font=font(30)) + 18, 72), sub, font=font(24, False), fill=MUT)


def race_image(out: Path, date_txt: str, label: str, meta: str, marks: list[tuple[str, str, str]],
               conf: str, result: tuple[str, bool] | None) -> None:
    label = unicodedata.normalize("NFKC", label)
    im = canvas()
    d = ImageDraw.Draw(im)
    header(d, date_txt)
    d.text((76, 118), label, font=fit(d, label, 58, 650), fill=INK)
    d.text((78, 196), meta, font=fit(d, meta, 26, 650, False), fill=MUT)
    y = 252
    for m, num, name in marks[:3]:
        d.text((76, y), m, font=font(46), fill=GREEN)
        line = f"{num}  {name}"
        d.text((140, y + 2), line, font=fit(d, line, 42, 560), fill=INK)
        y += 66
    # 自信度
    d.rounded_rectangle((76, 470, 236, 528), radius=12, fill=GREEN if conf in ("A", "B") else (201, 198, 184))
    ct = f"自信度 {conf}"
    d.text((156, 499), ct, font=fit(d, ct, 28, 150), fill=(255, 255, 255) if conf in ("A", "B") else INK, anchor="mm")
    if result:
        txt, hit = result
        f = fit(d, txt, 34, 470)
        tw = d.textlength(txt, font=f)
        d.rounded_rectangle((256, 470, 256 + tw + 40, 528), radius=12, fill=GREEN if hit else (255, 255, 255),
                            outline=None if hit else RED, width=3)
        d.text((276, 499), txt, font=f, fill=(255, 255, 255) if hit else RED, anchor="lm")
    else:
        d.text((256, 482), "全頭評価と買い目を公開中", font=font(28, False), fill=MUT)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, "JPEG", quality=82, optimize=True, progressive=True)


def site_image(out: Path, title: str, lines: list[str]) -> None:
    im = canvas()
    d = ImageDraw.Draw(im)
    d.text((76, 70), "AI競馬ログ", font=font(64), fill=GREEN)
    d.text((80, 160), title, font=fit(d, title, 38, 640), fill=INK)
    y = 240
    for ln in lines:
        d.text((80, y), ln, font=fit(d, ln, 30, 640, False), fill=MUT)
        y += 52
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, "JPEG", quality=85, optimize=True, progressive=True)
