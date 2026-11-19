"""検索から1ページだけ読んで帰る人に「次の1クリック」と「毎週来る場所」を用意する部品（build.py から呼ぶ）。

GA4（2026-11-19時点の28日分）では、検索から来た人の入口は G1特集・馬のページ・重賞ページが9割で、
見るのは平均1.4ページ、2回以上来た人は約5%だった。そこで：

- next_card / next_mini：馬・重賞・特集・データ記事のページに、そのレースのAI予想と「AI vs あなた」への入口を置く
  （予想がまだなら公開予定の日と、毎週更新のまとめページへ案内する）
- /weekend/：今週末の重賞（予想の公開状況・特集・過去データ）と先週の結果を毎回のビルドで入れ替える固定ページ

重賞の日程は data/graded_hist/<年>.json（JRA公式の一覧から集めたもの。まだ行われていないレースも入っている）。
URL名は scraper/graded_cols.py と同じ決め方にする（略称と正式名のずれをそろえるため）。
"""
from __future__ import annotations

import contextlib
import io
import sys
from datetime import datetime, timedelta

WD = "月火水木金土日"
JRA = ("札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉")
# 手で書いた特集（columns の series）と重賞ページの対応
FEATURE_RACE = {"eliza2026": "queen-elizabeth-cup", "mile2026": "mile-championship", "jc2026": "japan-cup",
                "jcd2026": "champions-cup", "arima2026": "arima-kinen"}

_B = None
TODAY = ""
SCHED: list[dict] = []           # これから（と直近）のJRA重賞：{date, name, grade, venue, course, slug}
SCHED_BY_SLUG: dict[str, list[dict]] = {}
PREDS: dict[str, list[tuple]] = {}  # 重賞の slug → [(日付, 予想)]（古い順）
FEAT: dict[str, list[dict]] = {}   # 重賞の slug → 特集の記事（order 順）
GDATA: dict[str, list[dict]] = {}  # 重賞の slug → 過去20年データ記事


def _schedule(root, today: str) -> list[dict]:
    try:
        sys.path.insert(0, str(root / "scraper"))
        import graded_cols as G  # noqa: PLC0415
        with contextlib.redirect_stdout(io.StringIO()):
            keyed = G.keyed(G.load_all())
    except Exception:  # noqa: BLE001
        return []
    lo = (datetime.strptime(today, "%Y%m%d") - timedelta(days=14)).strftime("%Y%m%d")
    out = []
    for slug, years in keyed.items():
        if slug.startswith("abbr:"):
            continue
        for r in years.values():
            if r.get("date", "") >= lo:
                out.append({"date": r["date"], "abbr": r.get("abbr", ""), "grade": r.get("grade", ""), "venue": r.get("venue", ""),
                            "course": (r.get("course") or "").replace(" ", "").replace(",", "").replace("メートル", "m"), "slug": slug})
    out.sort(key=lambda x: (x["date"], x["slug"]))
    return out


def prepare(B, by_date: dict, today: str) -> None:
    """ビルドの最初の方で1回だけ呼ぶ（重賞ページ・馬のページ・コラムより前）。"""
    global _B, TODAY, SCHED
    _B, TODAY = B, today
    import column  # noqa: PLC0415
    import extra  # noqa: PLC0415
    SCHED = _schedule(B.ROOT, today)
    for r in SCHED:
        g = B.load_json(B.ROOT / "data" / "race_guides" / f"{r['slug']}.json") or {}
        r["name"] = g.get("name") or r["abbr"]
        SCHED_BY_SLUG.setdefault(r["slug"], []).append(r)
    PREDS.clear()
    for d, ps in by_date.items():
        for p in ps:
            name = p.get("race_name") or p["_race"].get("race_name") or p["_race"].get("title_text") or ""
            g = extra.grade_of(p["_race"], name)
            if g:
                slug = extra.graded_slug(name, B.VENUE_SLUG.get(B.venue_of(p), "venue"))
                PREDS.setdefault(slug, []).append((d, p, extra.clean_name(name), g))
    for v in PREDS.values():
        v.sort(key=lambda x: (x[0], x[1]["_race"].get("post_time") or ""))
    FEAT.clear(); GDATA.clear()
    for c in column.columns():
        if c["draft"]:
            continue
        s = c.get("series")
        if s in FEATURE_RACE:
            FEAT.setdefault(FEATURE_RACE[s], []).append(c)
        elif s == "gdata" and c.get("race"):
            GDATA.setdefault(c["race"], []).append(c)
    for v in list(FEAT.values()) + list(GDATA.values()):
        v.sort(key=lambda c: int(c.get("order") or 0))


# ---------- 日付の言い方 ----------
def _dt(d: str) -> datetime:
    return datetime.strptime(d, "%Y%m%d")


def day_jp(d: str) -> str:
    x = _dt(d)
    return f"{x.month}月{x.day}日（{WD[x.weekday()]}）"


def publish_when(d: str) -> str:
    """予想の公開予定。重賞は枠順が出ていれば金・土の10:38の回（明日と明後日の分）で先に出し、遅くとも前日夜（20:41の回）に出す。
    だから土曜のレースは金曜、日曜・月曜（祝日）のレースは2日前の昼から前日の夜までに出る。"""
    x = _dt(d)
    prev = x - timedelta(days=1)
    first = x - timedelta(days=2 if x.weekday() in (6, 0) else 1)
    first = max(first, _dt(TODAY)) if TODAY else first
    if first.date() >= prev.date():
        return f"{day_jp(prev.strftime('%Y%m%d'))}の昼〜夜に公開予定"
    return f"{day_jp(first.strftime('%Y%m%d'))}の昼〜{day_jp(prev.strftime('%Y%m%d'))}の夜に公開予定"


# ---------- どのレースへ案内するか ----------
def target(slug: str) -> tuple | None:
    """('pred', 日付, 予想, 名前) 予想を公開済みで発走前／('done', …) 発走後3日以内／('sched', 日付, 日程, 名前) 予想はまだ／None。"""
    B = _B
    preds = PREDS.get(slug) or []
    for d, p, name, _g in preds:
        if d >= TODAY and B.before_post(d, p) or d > TODAY:
            return ("pred", d, p, name)
    for r in SCHED_BY_SLUG.get(slug) or []:
        if r["date"] >= TODAY and not any(d == r["date"] for d, *_ in preds):
            return ("sched", r["date"], r, r["name"])
    lo = (_dt(TODAY) - timedelta(days=3)).strftime("%Y%m%d")
    for d, p, name, _g in reversed(preds):
        if d >= lo:
            return ("done", d, p, name)
    return None


def _a(href: str, head: str, sub: str, where: str, to: str, main: bool = False) -> str:
    esc = _B.esc
    return (f"<a class='nbtn{' main' if main else ''}' href='{esc(href)}' data-ns='{esc(where)}' data-ns-to='{esc(to)}'>"
            f"<b>{esc(head)}</b><small>{esc(sub)}</small></a>")


def _has_graded(slug: str) -> bool:
    """重賞ページ（/graded/<slug>/）が作られるか：予想があるか、レースガイドがあるとき（extra.build_pages と同じ条件）。"""
    return bool(PREDS.get(slug)) or (_B.ROOT / "data" / "race_guides" / f"{slug}.json").exists()


def _vs_ok() -> bool:
    return bool(_B.LEAGUE_URL)


def _race_btns(d: str, p: dict, name: str, where: str) -> str:
    B = _B
    path = B.race_path(d, p)
    hon = (p.get("marks") or {}).get("◎")
    sub = f"◎{hon} {B.horse_name(p, hon)}・全頭の評価点と買い目" if hon is not None and p.get("confidence") != "見送り" else "全頭の評価点と印"
    out = _a(path, f"{day_jp(d)} {name}のAI予想", sub, where, "race", main=True)
    if _vs_ok() and p.get("confidence") != "見送り" and (d > TODAY or B.before_post(d, p)):
        out += _a(path + "#vs", "このレースでAIと単勝勝負", "あなたの◎を1頭選ぶだけ・無料。月間ランキングに載る", where, "vs")
    return out


def _weekend_btn(where: str, main: bool = False) -> str:
    return _a("/weekend/", "今週末の競馬まとめ", "重賞のAI予想・特集・先週の結果を毎週入れ替え。ブックマークに", where, "weekend", main)


def next_card(where: str, slug: str | None = None, race: tuple | None = None, here_graded: bool = False) -> str:
    """ページの下（馬のページは上）に置く「次に見る」。race=(日付, 予想) を渡せばそのレースへ、slug なら重賞の今年のレースへ。"""
    if _B is None:
        return ""
    B, esc = _B, _B.esc
    btns, note = "", ""
    if race:
        d, p = race
        name = B.race_label(p)
        if d >= TODAY:
            btns = _race_btns(d, p, name, where)
        else:
            btns = _a(B.race_path(d, p), f"{day_jp(d)} {name}の結果とAIの予想", "AIの◎は何着だったか・回顧", where, "race", main=True)
        btns += _weekend_btn(where)
    elif slug and (t := target(slug)):
        kind, d, obj, name = t
        if kind == "pred":
            btns = _race_btns(d, obj, name, where) + _weekend_btn(where)
        elif kind == "done":
            btns = (_a(B.race_path(d, obj), f"{day_jp(d)} {name}の結果とAIの予想", "AIの◎は何着だったか・回顧", where, "race", main=True)
                    + _weekend_btn(where))
        else:
            note = f"<p class='meta'>{esc(day_jp(d))}の{esc(name)}のAI予想は、{esc(publish_when(d))}（枠順の確定後）。公開したら下のまとめページにも載ります。</p>"
            btns = _weekend_btn(where, main=True)
            if not here_graded and _has_graded(slug):
                btns += _a(f"/graded/{slug}/", f"{name}の傾向と過去のAI予想", "予想を公開したらこのページにも追加", where, "graded")
    if not btns:
        btns = _a("/", "今日のAI予想", "中央・地方の全レースの印と買い目", where, "today", main=True) + _weekend_btn(where)
    if _vs_ok() and "data-ns-to='vs'" not in btns:
        btns += _a("/vs/guide/", "AI vs あなた 月間ランキング", "AIと同じレースで◎を選んで勝負。参加は名前を決めるだけ", where, "vsguide")
    return f"<section class='card nstep'><h2>次に見る</h2>{note}<div class='nbtns'>{btns}</div></section>"


def next_mini(where: str, slug: str) -> str:
    """特集・データ記事の冒頭に置く1行（本文の前に大きな箱を置くと読みにくいので、箱は記事の下に置く）。"""
    if _B is None or not (t := target(slug)):
        return ""
    B, esc = _B, _B.esc
    kind, d, obj, name = t
    if kind == "pred":
        return (f"<p class='notice nmini'><b>{esc(name)}のAI予想を公開中</b>（{esc(day_jp(d))}）："
                f"<a href='{B.race_path(d, obj)}' data-ns='{esc(where)}-top' data-ns-to='race'>全頭の評価と買い目を見る</a></p>")
    if kind == "done":
        return (f"<p class='notice nmini'>{esc(day_jp(d))}の{esc(name)}は確定：<a href='{B.race_path(d, obj)}' data-ns='{esc(where)}-top' data-ns-to='race'>"
                f"結果とAIの予想を見る</a></p>")
    return (f"<p class='notice nmini'>{esc(name)}（{esc(day_jp(d))}）のAI予想は{esc(publish_when(d))}。"
            f"<a href='/weekend/' data-ns='{esc(where)}-top' data-ns-to='weekend'>今週末の競馬まとめ（毎週更新）</a></p>")


# ---------- /weekend/ ----------
def _window(today: str) -> tuple[str, str]:
    t = _dt(today)
    sun = t + timedelta(days=6 - t.weekday())
    end = sun
    mon = (sun + timedelta(days=1)).strftime("%Y%m%d")
    if any(r["date"] == mon for r in SCHED):  # 月曜が祝日で重賞がある週
        end = sun + timedelta(days=1)
    return today, end.strftime("%Y%m%d")


def _feat_links(slug: str, n: int = 2) -> list[tuple[str, str]]:
    """特集の入口（order 1）と2本目。入口は「特集まとめ」、ほかは題名の「｜」より前。"""
    out = []
    for c in (FEAT.get(slug) or [])[:n]:
        t = "特集まとめ" if str(c.get("order")) == "1" else c.get("title", "").split("｜")[0].split("【")[0].strip()
        out.append((f"/column/{c['slug']}/", t))
    return out


def _race_card(r: dict) -> str:
    """今週末の1レース。r：{date, name, grade, venue, course, slug, pred(=(d,p)) or None}"""
    B, esc = _B, _B.esc
    d, slug = r["date"], r["slug"]
    pred = r.get("pred")
    head = (f"<h3><span class='wk-g g{esc(r['grade'].replace('・', ''))}'>{esc(r['grade'])}</span>{esc(r['name'])}</h3>"
            f"<p class='meta'>{esc(day_jp(d))} {esc(r['venue'])} {esc(r.get('course', ''))}</p>")
    if pred:
        p = pred
        path = B.race_path(d, p)
        hon = (p.get("marks") or {}).get("◎")
        sc = B.scored(p)
        if sc and sc.get("stake"):
            res = "的中" if sc["return"] else "不的中"
            fin = sc.get("honmei_finish") or "-"
            status = (f"<p class='wk-st done'>確定：AIの◎{esc(hon)} {esc(B.horse_name(p, hon))}は{esc(fin)}着（{res}・このレースの回収率{B.roi_txt(sc['stake'], sc['return'])}）"
                      f"　<a href='{path}' data-ns='weekend' data-ns-to='race'>結果と回顧</a></p>")
        elif p.get("confidence") == "見送り":
            status = f"<p class='wk-st'>AIは見送り（自信度が低い）。<a href='{path}' data-ns='weekend' data-ns-to='race'>全頭の評価を見る</a></p>"
        else:
            status = (f"<p class='wk-st on'>AI予想を公開中：◎{esc(hon)} {esc(B.horse_name(p, hon))}（自信度{esc(p.get('confidence') or '-')}）</p>"
                      f"<div class='nbtns'>{_a(path, '全頭の評価と買い目', '評価点・印・想定勝率', 'weekend', 'race', True)}"
                      + (_a(path + '#vs', 'AIと単勝勝負', '◎を1頭選ぶだけ', 'weekend', 'vs') if _vs_ok() and B.before_post(d, p) else "") + "</div>")
    else:
        status = f"<p class='wk-st'>AI予想は{esc(publish_when(d))}（枠順の確定後）</p>"
    links = []
    for href, t in _feat_links(slug):
        links.append(f"<a href='{href}'>{esc(t)}</a>")
    if slug in GDATA:
        links.append(f"<a href='/column/{GDATA[slug][0]['slug']}/'>過去20年の結果</a>")
    if _has_graded(slug):
        links.append(f"<a href='/graded/{slug}/'>レースの傾向・過去のAI予想</a>")
    return (f"<li class='wk-r'>{head}{status}" + (f"<p class='wk-l'>{'　'.join(links)}</p>" if links else "") + "</li>")


def build_page(by_date: dict) -> dict[str, str]:
    B = _B
    if B is None:
        return {}
    esc = B.esc
    start, end = _window(TODAY)
    races = []
    seen = set()
    for r in SCHED:
        if start <= r["date"] <= end:
            pred = next((p for d, p, *_ in PREDS.get(r["slug"]) or [] if d == r["date"]), None)
            races.append({**r, "pred": pred})
            seen.add((r["slug"], r["date"]))
    # 地方の重賞は日程の元データが無いので、予想を出したものだけ並べる
    nar = []
    for slug, items in PREDS.items():
        for d, p, name, g in items:
            if start <= d <= end and (slug, d) not in seen and B.venue_of(p) not in JRA:
                r_ = p["_race"]
                course = f"{r_.get('surface') or ''}{r_.get('distance') or ''}m" if r_.get("distance") else ""
                nar.append({"date": d, "name": name, "grade": g, "venue": B.VENUE_NAME.get(B.venue_of(p), B.venue_of(p)), "course": course,
                            "slug": slug, "pred": p})
    races.sort(key=lambda r: (r["date"], {"G1": 0, "J・G1": 1, "G2": 2, "J・G2": 3}.get(r["grade"], 4)))
    nar.sort(key=lambda r: (r["date"], r["name"]))
    g1 = [r for r in races if r["grade"] == "G1"]
    # 先週末（今週の窓の前7日）の重賞の結果
    lo = (_dt(start) - timedelta(days=8)).strftime("%Y%m%d")
    last = []
    for slug, items in PREDS.items():
        for d, p, name, g in items:
            if lo <= d < start and B.scored(p) and B.scored(p).get("stake"):
                last.append((d, p, name, g, slug))
    last.sort(key=lambda x: (x[0], x[1]["_race"].get("post_time") or ""))
    # 来週以降のG1（3つまで）
    later = [r for r in SCHED if r["date"] > end and r["grade"] == "G1"][:3]

    span = f"{day_jp(start)}〜{day_jp(end)}" if start != end else day_jp(start)
    lead = (f"{span}の中央競馬の重賞は{len(races)}レース"
            + (f"。G1は{'、'.join(r['name'] + '（' + day_jp(r['date']) + '）' for r in g1)}" if g1 else "")
            + (f"。地方の重賞のAI予想も{len(nar)}レース公開している" if nar else "")
            + "。このページは、その週の重賞とAI予想の公開状況、特集記事、先週の結果を毎回自動で入れ替えている。")
    body = ("<p class='crumb'><a href='/'>トップ</a> › 今週末の競馬まとめ</p>"
            f"<h1>今週末の競馬まとめ<small>{esc(span)}・毎週更新</small></h1>{B.banner('graded')}"
            f"<p class='answer'>{esc(lead)}</p>"
            "<section class='card bm'><h2>毎週、ここを見れば足ります</h2>"
            "<p>重賞のAI予想は、枠順が決まったあと<b>レースの前日（日曜・祝日のレースは2日前）の昼から夜</b>に公開します。このページをブックマーク（またはホーム画面に追加）しておくと、週末前に同じ場所で確認できます。</p>"
            "<details><summary>ブックマーク・ホーム画面への追加のしかた</summary><ul>"
            "<li>iPhone（Safari）：画面下の共有ボタン（□に↑）→「ブックマークを追加」または「ホーム画面に追加」</li>"
            "<li>Android（Chrome）：右上の︙ →「☆」または「ホーム画面に追加」</li>"
            "<li>パソコン：Ctrl＋D（Macは⌘＋D）</li></ul></details>"
            f"<p class='meta'>重賞の予想を公開したときは<a href='{B.X_URL}' target='_blank' rel='noopener me'>X（@zentou_log）</a>でもお知らせしています。</p></section>")
    if races:
        body += f"<section class='card'><h2>今週末の重賞（中央）</h2><ul class='wk'>{''.join(_race_card(r) for r in races)}</ul></section>"
    else:
        body += "<section class='card'><h2>今週末の重賞（中央）</h2><p>この期間に中央の重賞はありません。</p></section>"
    if nar:
        body += f"<section class='card'><h2>今週の地方の重賞（AI予想を公開済み）</h2><ul class='wk'>{''.join(_race_card(r) for r in nar)}</ul></section>"
    if _vs_ok():
        body += ("<section class='card'><h2>AI vs あなた（月間ランキング）</h2>"
                 "<p>各レースページで、あなたの◎を1頭選ぶだけでAIと勝負できます。順位はその月に選んだ◎の単勝の回収率。参加は名前を決めるだけで無料です。</p>"
                 f"<div class='nbtns'>{_a('/vs/', '今月のランキングを見る', 'リアルタイムで更新', 'weekend', 'vsrank', True)}"
                 f"{_a('/vs/guide/', '遊び方', '3分で分かる参加のしかた', 'weekend', 'vsguide')}</div></section>")
    if later:
        lis = ""
        for r in later:
            fl = _feat_links(r["slug"])
            lis += (f"<li><b>{esc(r['name'])}</b>（{esc(day_jp(r['date']))}・{esc(r['venue'])}{esc(r['course'])}）"
                    + ("：" + "・".join(f"<a href='{h}'>{esc(t)}</a>" for h, t in fl) if fl else
                       (f"：<a href='/graded/{r['slug']}/'>レースの傾向</a>" if _has_graded(r["slug"]) else ""))
                    + "</li>")
        body += f"<section class='card'><h2>来週以降のG1</h2><ul>{lis}</ul></section>"
    if last:
        rows = ""
        for d, p, name, g, slug in last:
            sc = B.scored(p)
            hon = (p.get("marks") or {}).get("◎")
            rows += (f"<tr><td class='nw'>{esc(day_jp(d))}</td><td><a href='{B.race_path(d, p)}'>{esc(name)}</a>（{esc(g)}）</td>"
                     f"<td>◎{esc(hon)} {esc(B.horse_name(p, hon))}</td><td>{esc(sc.get('honmei_finish') or '-')}着</td>"
                     f"<td>{'的中' if sc['return'] else '不的中'}</td></tr>")
        hits = sum(1 for x in last if B.scored(x[1])["return"])
        body += (f"<section class='card'><h2>この1週間の重賞の結果（AIの◎）</h2><p>{len(last)}レース中{hits}レースで的中。外れも含めてすべて載せています。</p>"
                 f"<div class='scroll'><table><thead><tr><th>日付</th><th>レース</th><th>AIの◎</th><th>着順</th><th>買い目</th></tr></thead><tbody>{rows}</tbody></table></div>"
                 "<p class='meta'><a href='/review/'>重賞回顧の一覧</a>・<a href='/results/'>全レースの成績</a></p></section>")
    body += ("<section class='card'><h2>毎週の流れ</h2><ol>"
             "<li>レースの約2週間前：その重賞の過去20年のデータ記事を公開</li>"
             "<li>G1の週の前半：特集（日程・有力馬・傾向）を更新</li>"
             "<li>レースの前日（日曜・祝日のレースは2日前）の昼〜夜：枠順の確定後に重賞のAI予想を公開</li>"
             "<li>レース当日：朝と昼のオッズで見直し、レース後に結果と回顧を追加</li></ol></section>"
             + B.share_links(B.BASE_URL + "/weekend/", f"今週末の競馬まとめ（{span}）重賞のAI予想と特集"))
    title = f"今週末の競馬まとめ｜重賞のAI予想・G1特集・先週の結果（毎週更新）｜{B.SITE_NAME}"
    desc = lead[:120]
    ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": B.SITE_NAME, "item": B.BASE_URL + "/"},
        {"@type": "ListItem", "position": 2, "name": "今週末の競馬まとめ", "item": B.BASE_URL + "/weekend/"}]}
    B.write("/weekend/", B.page(title, body, "/weekend/", desc=desc, head_extra=B.jsonld(ld)))
    return {"/weekend/": f"{TODAY[:4]}-{TODAY[4:6]}-{TODAY[6:8]}"}


CSS = """
.nstep h2{margin-bottom:6px}.nbtns{display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));margin:8px 0}
.nbtn{display:block;border:1px solid var(--line);border-left:4px solid var(--acc);background:var(--panel);padding:10px 12px;text-decoration:none;color:var(--fg);min-height:44px}
.nbtn b{display:block;font-size:15px;line-height:1.4;color:var(--acc)}.nbtn small{display:block;font-size:12px;color:var(--mut);line-height:1.5;margin-top:2px}
.nbtn.main{background:var(--acc);border-color:var(--acc)}.nbtn.main b,.nbtn.main small{color:var(--bg)}
.nbtn:hover{text-decoration:none;filter:brightness(1.05)}.nmini a{font-weight:700}
.wk{list-style:none;padding:0;margin:0}.wk-r{padding:12px 0;border-bottom:1px solid var(--line)}.wk-r:last-child{border-bottom:0}
.wk-r h3{margin:0 0 2px;font-size:17px}.wk-g{display:inline-block;font-size:12px;padding:1px 6px;margin-right:6px;border:1px solid var(--line);vertical-align:2px}
.wk-g.gG1,.wk-g.gJG1{background:var(--acc);color:var(--bg);border-color:var(--acc)}
.wk-st{margin:6px 0}.wk-st.on{font-weight:700}.wk-l{font-size:13px;margin:4px 0 0;line-height:1.9}
.bm{border-left:4px solid var(--acc)}.bm details{margin:6px 0}.bm summary{cursor:pointer;color:var(--acc)}
"""

JS = r"""
document.addEventListener('click',function(e){var a=e.target&&e.target.closest?e.target.closest('a[data-ns]'):null;
 if(a&&window.gtag){try{gtag('event','next_step',{from:a.dataset.ns,to:a.dataset.nsTo||''});}catch(x){}}});
"""
