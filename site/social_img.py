"""SNS投稿用の画像（1080x1350、Instagramの縦長4:5。Xでもそのまま使える）。

card = {"label": "的中", "kind": "hit|grade_pre|grade_res|summary", "date": "11/1",
        "head": "門別11R エーデルワイス賞", "sub": "19:55発走・ダ1200m",
        "lines": [("◎", "9 セルアウトクラウド"), ...], "rows": ["馬連 6-9  1,590円", ...],
        "big": "236.7%", "big_label": "回収率", "foot": "投資900円 → 払戻2,130円"}
背景は site/assets/sns-<kind>.png（Codexで作った絵）。無ければ og-base を上部に敷いた無地。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

import og

HERE = Path(__file__).resolve().parent
W, H = 1080, 1350
GOLD = (196, 150, 40)
ACC = {"hit": GOLD, "grade_pre": og.GREEN, "grade_res": og.GREEN, "summary": og.GREEN}


def background(kind: str) -> Image.Image:
    for name in (f"sns-{kind}.png", "sns-base.png"):
        f = HERE / "assets" / name
        if f.exists():
            im = Image.open(f).convert("RGB")
            r = max(W / im.width, H / im.height)
            im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
            x, y = (im.width - W) // 2, (im.height - H) // 2
            return im.crop((x, y, x + W, y + H))
    im = Image.new("RGB", (W, H), og.CREAM)
    base = HERE / "assets" / "og-base.png"
    if base.exists():
        b = Image.open(base).convert("RGB")
        r = max(W / b.width, 420 / b.height)
        b = b.resize((round(b.width * r), round(b.height * r)), Image.LANCZOS)
        x = b.width - W  # 右寄せ（馬が右側にいる絵のため）
        im.paste(b.crop((x, 0, x + W, 420)), (0, 0))
    return im


def render(out: Path, card: dict) -> None:
    kind = card.get("kind", "hit")
    acc = ACC.get(kind, og.GREEN)
    im = background(kind).convert("RGBA")
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((48, 300, W - 48, H - 150), radius=36, fill=og.CREAM + (242,))
    d.rectangle((0, H - 124, W, H), fill=og.GREEN + (255,))
    im = Image.alpha_composite(im, layer)
    d = ImageDraw.Draw(im)
    # 上部：サイト名と日付
    logo = HERE / "assets" / "logo-mark-96.png"
    x0 = 64
    if logo.exists():
        lg = Image.open(logo).convert("RGBA").resize((72, 72), Image.LANCZOS)
        bg = Image.new("RGBA", (88, 88), (255, 255, 255, 230))
        im.alpha_composite(bg, (56, 48))
        im.alpha_composite(lg, (64, 56))
        x0 = 160
    d.rounded_rectangle((x0 - 8, 56, x0 + 330, 128), radius=14, fill=(255, 255, 255, 230))
    d.text((x0 + 8, 92), "AI競馬ログ", font=og.font(44), fill=og.GREEN, anchor="lm")
    # ラベル
    label = card.get("label", "")
    f = og.font(64)
    tw = d.textlength(label, font=f)
    d.rounded_rectangle((96, 336, 96 + tw + 64, 436), radius=20, fill=acc)
    d.text((128, 386), label, font=f, fill=(255, 255, 255), anchor="lm")
    d.text((W - 96, 386), card.get("date", ""), font=og.font(40, False), fill=og.MUT, anchor="rm")
    y = 456
    head = og.unicodedata.normalize("NFKC", card.get("head", ""))
    hf = og.fit(d, head, 56, W - 192)
    d.text((96, y), head, font=hf, fill=og.INK)
    y += hf.size + 24
    if card.get("sub"):
        d.text((98, y), card["sub"], font=og.fit(d, card["sub"], 32, W - 192, False), fill=og.MUT)
        y += 56
    y += 8
    for m, txt in card.get("lines", [])[:3]:
        d.text((96, y), m, font=og.font(52), fill=og.GREEN)
        d.text((170, y + 4), txt, font=og.fit(d, txt, 48, W - 280), fill=og.INK)
        y += 64
    big_top = H - 150 - 262  # 大きな数字の区画（パネル下端から300px）
    if card.get("rows"):
        y += 12
        for row in card["rows"][:4]:
            if card.get("big") and y + 52 > big_top - 10:
                break
            d.text((100, y), row, font=og.fit(d, row, 36, W - 200, False), fill=og.INK)
            y += 48
    # 大きな数字
    if card.get("big"):
        by = big_top
        d.line((96, by, W - 96, by), fill=(220, 216, 204), width=3)
        d.text((96, by + 28), card.get("big_label", ""), font=og.font(36, False), fill=og.MUT)
        d.text((W - 96, by + 128), card["big"], font=og.font(112), fill=acc, anchor="rm")
        if card.get("foot"):
            d.text((96, by + 196), card["foot"], font=og.fit(d, card["foot"], 36, W - 192), fill=og.INK)
    # 下部
    d.text((W // 2, H - 80), "www.ai-keiba-log.com　外れも含む全成績を公開", font=og.font(34), fill=(255, 255, 255), anchor="mm")
    d.text((W // 2, H - 36), "※予想は情報提供です。馬券は20歳から。", font=og.font(26, False), fill=(220, 236, 226), anchor="mm")
    out.parent.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(out, "JPEG", quality=88, optimize=True, progressive=True)
