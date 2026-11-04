"""週ごとの重賞回顧（/review/<年>-w<週>/）。

その週（月〜日）に確定した重賞を、予想（印・自信度・要約）と結果（着順・払戻・回収率）で振り返る。
日曜の夜に自動で更新され、翌週以降もそのまま残る。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date as _date, timedelta

from extra import clean_name, grade_of


def week_key(d: str) -> tuple[str, _date, _date]:
    dt = _date(int(d[:4]), int(d[4:6]), int(d[6:8]))
    mon = dt - timedelta(days=dt.weekday())
    y, w, _ = mon.isocalendar()
    return f"{y}-w{w:02d}", mon, mon + timedelta(days=6)


def build_pages(B, by_date: dict, today: str) -> dict[str, str]:
    esc, write, page, jsonld = B.esc, B.write, B.page, B.jsonld
    lastmod: dict[str, str] = {}
    weeks: dict[str, list] = defaultdict(list)
    span: dict[str, tuple[_date, _date]] = {}
    for d, ps in by_date.items():
        for p in ps:
            name = p.get("race_name") or p["_race"].get("race_name") or p["_race"].get("title_text") or ""
            g = grade_of(p["_race"], name)
            if not g:
                continue
            k, a, b = week_key(d)
            span[k] = (a, b)
            weeks[k].append((d, p, clean_name(name), g))
    this_week = week_key(today)[0]
    index_rows = []
    for k, items in sorted(weeks.items(), reverse=True):
        done = [(d, p, n, g, B.scored(p)) for d, p, n, g in items if B.scored(p) and B.scored(p)["stake"]]
        if not done:
            continue
        a, b = span[k]
        items.sort(key=lambda x: (x[0], x[1]["_race"].get("post_time") or ""))
        st = sum(s["stake"] for *_, s in done)
        rt = sum(s["return"] for *_, s in done)
        hit = sum(1 for *_, s in done if s["return"] > 0)
        win = sum(1 for *_, s in done if str(s.get("honmei_finish")) == "1")
        top3 = sum(1 for *_, s in done if str(s.get("honmei_finish")) in ("1", "2", "3"))
        label = f"{a.year}年{a.month}月{a.day}日〜{b.month}月{b.day}日"
        cards = []
        for d, p, n, g, in items:
            sc = B.scored(p)
            hon = p.get("marks", {}).get("◎")
            v = B.VENUE_NAME.get(B.venue_of(p), B.venue_of(p))
            marks = "　".join(f"{m}{p['marks'][m]} {esc(B.horse_name(p, p['marks'][m]))}" for m in ("◎", "〇", "▲") if p.get("marks", {}).get(m) is not None)
            if sc and sc["stake"]:
                top = "-".join(str(x) for x in sc.get("top3", []) if x is not None)
                hf = sc.get("honmei_finish") or "-"
                res = (f"<p class='big {'hit' if sc['return'] >= sc['stake'] else 'tg' if sc['return'] else 'miss'}'>"
                       f"結果 {esc(top)}　◎は{esc(hf)}着　{'的中' if sc['return'] else '不的中'}　購入{sc['stake']:,}円→払戻{sc['return']:,}円（回収率{B.roi_txt(sc['stake'], sc['return'])}）</p>")
                # 勝ち馬にどの印を打っていたか
                mm = B.mark_map(p)
                w = sc.get("top3", [None])[0]
                wm = mm.get(w)
                look = (f"勝った{esc(B.horse_name(p, w))}には{'印を打っていなかった' if not wm else f'{wm}を打っていた'}。" if w is not None else "")
            else:
                res = f"<p class='meta'>{esc(p['_race'].get('post_time') or '')}発走・結果待ち</p>"
                look = ""
            summ = esc((p.get("summary") or "")[:160])
            cards.append(f"<section class='card'><h2><a href='{B.race_path(d, p)}'>{esc(n)}（{esc(g)}・{esc(v)}）</a> <small>{esc(B.fmt_date(d))}</small></h2>"
                         f"<p>{marks}　自信度{esc(p.get('confidence'))}</p>{res}"
                         f"<p>{summ}{'…' if len(p.get('summary') or '') > 160 else ''}</p>" + (f"<p class='meta'>{look}</p>" if look else "") + "</section>")
        cur = k == this_week
        h1 = f"{'今週' if cur else label}の重賞回顧：AI予想の結果と回収率"
        lead = (f"{label}の重賞{len(done)}レースで、AI予想は的中{hit}レース、◎の1着{win}回・3着以内{top3}回、回収率{B.roi_txt(st, rt)}（購入{st:,}円→払戻{rt:,}円）。"
                + ("今週はまだ確定していない重賞がある。" if cur and len(done) < len(items) else ""))
        path = f"/review/{k}/"
        body = (f"<p class='crumb'><a href='/'>トップ</a> › <a href='/review/'>重賞回顧</a> › {esc(label)}</p><h1>{esc(h1)}</h1>"
                f"<p class='answer'>{esc(lead)}</p>"
                f"<div class='kpis'><div><b>{len(done)}</b><span>確定した重賞</span></div><div><b>{hit}</b><span>的中レース</span></div>"
                f"<div><b>{win}・{top3}</b><span>◎の1着・3着内</span></div><div><b>{B.roi_txt(st, rt)}</b><span>回収率</span></div></div>"
                + "".join(cards)
                + "<p class='meta'>買い目を1点100円ずつ買った計算。重賞以外も含めた全成績は<a href='/results/'>成績ページ</a>、各重賞の過去の予想は<a href='/graded/'>重賞一覧</a>へ。</p>")
        ld = {"@context": "https://schema.org", "@type": "Article", "headline": h1, "datePublished": f"{b.isoformat()}",
              "dateModified": f"{max(d for d, *_ in items)[:4]}-{max(d for d, *_ in items)[4:6]}-{max(d for d, *_ in items)[6:8]}",
              "author": {"@type": "Organization", "name": B.SITE_NAME}, "mainEntityOfPage": B.BASE_URL + path}
        write(path, page(f"{label} 重賞回顧｜AI予想の結果と回収率 | {B.SITE_NAME}", body, path, desc=lead[:120], head_extra=jsonld(ld)))
        lastmod[path] = f"{max(d for d, *_ in items)[:4]}-{max(d for d, *_ in items)[4:6]}-{max(d for d, *_ in items)[6:8]}"
        names = "・".join(n for _, _, n, _ in items[:6]) + ("…" if len(items) > 6 else "")
        index_rows.append(f"<li><a href='{path}'><span>{esc(label)}{'（今週）' if cur else ''}　{esc(names)}</span><span>{len(done)}レース・回収率{B.roi_txt(st, rt)}</span></a></li>")
    write("/review/", page(f"重賞回顧 一覧｜週ごとのAI予想の結果 | {B.SITE_NAME}",
                           "<p class='crumb'><a href='/'>トップ</a> › 重賞回顧</p><h1>重賞回顧（週ごと）</h1>" + B.banner("review") +
                           "<p class='answer'>毎週の重賞について、AI予想の印・自信度と、確定した結果・回収率を振り返る。日曜の夜に自動で更新。</p>"
                           f"<ul class='days'>{''.join(index_rows)}</ul>", "/review/",
                           desc="毎週の重賞のAI予想と結果・回収率の振り返り。", noindex=not index_rows))
    if index_rows:
        lastmod["/review/"] = f"{today[:4]}-{today[4:6]}-{today[6:8]}"
    return lastmod
