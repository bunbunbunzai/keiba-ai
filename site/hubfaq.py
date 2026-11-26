"""特集まとめ（〇〇<年>-guide）に入れる「よくある質問」。

Bing の検索と AI の回答で引用されているのは、ふだん競馬を見ない人が調べる言葉（いつ・何時から・中継・買い方）が多い
（2026-11-26、Bing Webmaster Tools）。その答えを、いま上位にいる特集まとめの中に置く（ページは増やさない）。
site/column.py がサイトを組み立てるときに記事の本文（Markdown）へ差し込み、レースが終わったら出さない。

書いてよいのは、下の SRC のページで確かめたことだけ。番組や発売の時刻は年ごとに変わるので、
年が替わったら SRC を見直して CHECKED・CHECKED_YEAR を直す（直すまで、確かめていない年のレースには番組名・放送時間・発売開始の時刻を書かない）。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

CHECKED = "2026-11-26"  # 下の事実を公式ページで確かめた日
CHECKED_YEAR = 2026     # 地上波の番組・放送時間と、ネット投票の発売開始の時刻を確かめた年（この年のレースにだけ書く）
TV_FROM, TV_TO = "15:00", "16:00"  # 地上波の競馬中継のふだんの放送時間（土曜・日曜）

SRC = {
    # 地上波：関東は土曜がテレビ東京「ウイニング競馬」、日曜がフジテレビ「みんなのKEIBA」。どちらも15時00分〜16時00分（2026年度の表）
    "tv": "https://www.jra.go.jp/tvradio/",
    # 「中央競馬全レース中継」の無料ネット配信（2026年3月14日〜。グリーンチャンネルWeb無料版・YouTubeのJRA公式チャンネル・JRAアプリ）
    "live": "https://www.jra.go.jp/tvradio/racelive/",
    "live_news": "https://www.jra.go.jp/news/202601/013001.html",
    # 即PAT：JRA指定の銀行口座か本人確認済みのPayPayがあれば、申し込んだその日から使える
    "sokupat": "https://www.jra.go.jp/dento/soku/about.html",
    # 即PAT会員の発売時間（2026年）：締め切りは各レースの発走時刻の1分前。土曜の全レースは金曜18時30分から。
    # 前日発売は、G1が金曜18時30分〜土曜17時30分、日曜のG2・G3が土曜7時00分〜17時30分
    "sale": "https://www.jra.go.jp/dento/soku/instructions/hatsubai/jra.html",
    # 20歳未満は競馬法で買えない。発売は100円単位
    "rule": "https://www.jra.go.jp/kouza/baken/index.html",
    # 指定席は事前のネット予約が必要
    "ticket": "https://www.jra.go.jp/ticket/",
    # 2025年12月29日の東京大賞典は、JRAのネット投票（即PATのみ）でも発売された
    "nar_2025": "https://www.jra.go.jp/news/202512/121402.html",
}

# 地方のレースごとの補足（確かめた年を文の中に書く）
NAR_NOTES = {
    "tokyo-daishoten": "JRAのネット投票（即PAT）でも、2025年は東京大賞典の馬券が発売された。{year}年に発売されるかは、JRAの発表で確かめてほしい。",
}

WD = "月火水木金土日"
_G1 = ("G1", "J・G1")


def _day(d: str) -> tuple[str, int]:
    x = datetime.strptime(d, "%Y%m%d")
    return f"{x.year}年{x.month}月{x.day}日（{WD[x.weekday()]}）", x.weekday()


def _clock(t: str) -> str:
    """「15:40」を「15時40分」に。形が違えば空。"""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", t or "")
    return f"{int(m.group(1))}時{m.group(2)}分" if m else ""


def post_hint(body: str) -> str:
    """記事の本文に書かれた発走の予定時刻（「15:40発走」「15時40分発走」）を「15:40」の形で返す。無ければ空。"""
    m = re.search(r"(\d{1,2})(?::|時)(\d{2})分?発走", body or "")
    return f"{int(m.group(1))}:{m.group(2)}" if m else ""


def _usable(info) -> bool:
    if not info or not info.get("name") or not re.fullmatch(r"\d{8}", str(info.get("date") or "")):
        return False
    if info.get("phase") == "result":
        return False
    return not (info.get("today") and info["date"] < info["today"])  # 日を過ぎたら、結果がまだでも出さない


def _checked_year(info: dict) -> bool:
    """番組や発売の時刻を確かめた年のレースか（レースの日の年で見る）。"""
    return str(info["date"])[:4] == str(CHECKED_YEAR)


def _sale_from(info: dict, wd: int) -> str:
    """ネット投票（即PAT）で買えるようになる時刻。確かめた年の土曜・日曜のレースだけ。"""
    if not _checked_year(info):
        return ""
    if wd == 5:
        return "土曜のレースの馬券は、前日の金曜の18時30分から発売される。"
    if wd == 6:
        if info.get("grade") in _G1:
            return "G1の馬券は、その週の金曜の18時30分から発売される。"
        return "日曜の重賞の馬券は、前日の土曜の7時から発売される。"
    return ""


def _tv(info: dict, wd: int, clock: str) -> str:
    guide = f"[JRAのテレビ・ラジオ中継の案内]({SRC['tv']})で確かめてほしい。"
    if wd not in (5, 6):
        a = "土曜・日曜以外の開催日は、地上波で放送する局や時間がふだんと違うので、" + guide
    elif not _checked_year(info):  # 番組名と放送時間は、確かめた年の分だけ書く
        a = "地上波の競馬中継は、放送する局や時間が年や地域で違うので、" + guide
    else:
        a = ("地上波では、土曜の競馬中継（関東はテレビ東京「ウイニング競馬」、15時〜16時）がある。" if wd == 5
             else "地上波では、日曜の競馬中継（関東はフジテレビ「みんなのKEIBA」、15時〜16時）がある。") + "放送する局は地域で違う。"
        post = info.get("post") or ""
        if clock and not (TV_FROM <= post.zfill(5) < TV_TO):
            a += f"このレースは{clock}発走で、ふだんの放送時間（15時〜16時）には入らない。"
        a += "G1の日などは放送時間が変わることがあるので、" + guide
    a += f"ネットでは、JRAが全レースの中継を無料で配信している（[JRAのレースライブ]({SRC['live']})。YouTubeのJRA公式チャンネルやJRAのアプリでも見られる）。"
    return a


def faq_items(info) -> list[dict]:
    """[{"q": 質問, "a": 答え（Markdownの1段落）, "after": 答えの次の行に置く差し込み}]。出さないときは空。"""
    if not _usable(info):
        return []
    name, year, slug = info["name"], str(info.get("year") or info["date"][:4]), info.get("slug") or ""
    day, wd = _day(info["date"])
    jra = bool(info.get("jra"))
    place = f"{info.get('venue', '')}競馬場" + (f"の{info['course']}" if info.get("course") else "")
    clock = _clock(info.get("post") or "")
    out = []

    def add(q: str, a: str, after: str = "") -> None:
        out.append({"q": q, "a": a, "after": after})

    # 1. いつ、何時から
    if clock:
        when = f"発走は{clock}" + ("。" if info.get("post_fixed") else "の予定。")
    elif jra:
        when = "発走時刻は出馬表の発表で決まり、このページにも載る。"
    else:
        when = "発走時刻は主催者が出す出馬表で決まり、このページにも載る。"
    add(f"{name}{year}はいつ、何時から？", f"{day}、{place}で行われる。{when}")

    # 2. 中継
    if jra:
        add("テレビやネットの中継はある？", _tv(info, wd, clock))
    else:
        add("テレビやネットの中継はある？",
            "地方競馬の公式のライブ映像「地方競馬ライブ」で、無料で見られる。楽天競馬などのネット投票サイトでも、レースの映像を見られる。"
            "テレビの放送は年によって違うので、主催者の発表で確かめてほしい。")

    # 3. いくらから
    add("馬券はいくらから買える？",
        "100円から、100円単位で買える。買えるのは20歳以上で、20歳未満は法律で買えない。"
        "いちばん単純なのは1着を当てる「単勝」で、3着までに入れば当たりの「複勝」もある（出走が7頭以下なら2着まで）。"
        "くわしくは[単勝と複勝の違い](/column/tansho-fukusho/)と[予算の決め方](/column/guide-yosan-kimekata/)にまとめた。")

    # 4. ネットで買えるか
    if jra:
        add("ネットで、当日でも買える？",
            f"買える。JRAのネット投票「即PAT」は、JRAが指定する銀行の口座かPayPayがあれば、申し込んだその日から使える（[JRAの即PATの案内]({SRC['sokupat']})）。"
            + _sale_from(info, wd) + "締め切りは発走時刻の1分前。手順は[JRAの馬券の買い方](/column/guide-jra-baken-kaikata/)にまとめた。")
    else:
        add("ネットで買える？当日でも間に合う？",
            "買える。地方競馬の馬券は、楽天競馬やSPAT4などのネット投票で買える。会員登録と入金が済んでいれば、当日でも発走の直前まで買える。"
            + NAR_NOTES.get(slug, "").format(year=year), after="{{aff_nar}}")

    # 5. 競馬場で見る（中央だけ。地方の入場の決まりは確かめていない）
    if jra and info.get("venue"):
        add(f"{info['venue']}競馬場で見るには？",
            f"指定席は、事前のネット予約が要る。入場券の買い方は開催日によって違うので、[JRAの指定席・入場券の案内]({SRC['ticket']})で確かめてほしい。"
            "初めて行く人向けの流れは[初めての競馬場観戦ガイド](/column/guide-keibajo-kansen/)にまとめた。")

    # 6. このサイトのAI予想
    keep = "外れた予想も、結果と一緒に残している。"
    if info.get("phase") == "pred" and info.get("pred_path"):
        ai = f"公開中。[{name}{year}のAI予想]({info['pred_path']})で、全頭の評価点と印、買い目を見られる。{keep}"
    elif jra:
        ai = (f"{info['publish']}（枠順が決まってから）。" if info.get("publish") else "枠順が決まったあと、レースの前日の夜までに公開する。")
        ai += f"全頭の評価点と印、買い目を無料で公開する。{keep}"
        if info.get("graded_page") and slug:
            ai += f"公開すると[{name}のページ](/graded/{slug}/)にも載る。"
    else:  # 地方のレースは、ふだんの全レースと同じく前日の夜（特集まとめの冒頭の箱と同じ日どり）
        prev = datetime.strptime(info["date"], "%Y%m%d") - timedelta(days=1)
        ai = f"レースの前日の{prev.month}月{prev.day}日（{WD[prev.weekday()]}）の夜に公開する予定。全頭の評価点と印、買い目を無料で公開する。{keep}"
    add("このサイトのAI予想はいつ出る？", ai)
    return out


def faq_md(info) -> str:
    """記事の本文に差し込む Markdown。出さないときは空。"""
    items = faq_items(info)
    if not items:
        return ""
    y, m, _ = CHECKED.split("-")
    who = "JRA" if info.get("jra") else "主催者やJRA"
    out = [f"## {info['name']}{info.get('year') or info['date'][:4]}のよくある質問", "",
           f"初めて見る人・買う人がよく調べることを、{who}の案内をもとにまとめた（{int(y)}年{int(m)}月に確認）。", ""]
    for x in items:
        out += [f"### {x['q']}", "", x["a"], ""]
        if x["after"]:
            out += [x["after"], ""]
    return "\n".join(out)


def _plain(s: str) -> str:
    """Markdown のリンクと強調を外した文字だけ。"""
    s = re.sub(r"\[([^\]]+)\]\([^)\s]+\)", r"\1", s)
    return s.replace("**", "")


def faq_ld(info) -> dict | None:
    """検索エンジン向けの質問と答え（schema.org の FAQPage）。ページに見えている内容と同じものだけ。"""
    items = faq_items(info)
    if not items:
        return None
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": x["q"], "acceptedAnswer": {"@type": "Answer", "text": _plain(x["a"])}} for x in items]}


def insert_md(body: str, faq: str) -> str:
    """本文の「特集の記事」の見出しの前に入れる。無ければ「出典」の前、それも無ければ末尾。"""
    if not faq:
        return body
    m = (re.search(r"^## 特集の記事", body, re.M) or re.search(r"^## (?:出典|参考|参考にした資料)", body, re.M))
    block = faq.strip("\n")
    if not m:
        return body.rstrip("\n") + "\n\n" + block + "\n"
    return body[:m.start()].rstrip("\n") + "\n\n" + block + "\n\n" + body[m.start():]
