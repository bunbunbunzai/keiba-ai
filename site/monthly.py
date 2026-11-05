"""月次レポート（/monthly/<yyyy>-<mm>/）：その月の成績を自動で記事にする。

レース数・回収率・的中率、良かった買い方・悪かった場、月内の最高払戻、自信度別、週ごとの推移。
月の途中は「今月（集計中）」として毎日更新され、月が変わるとそのまま確定記事として残る。
"""
from __future__ import annotations

from collections import defaultdict

import strategy


def _analysis_html(B, ym: str) -> str:
    """AIによるこの月の分析（data/monthly_notes）。"""
    n = B.load_json(B.ROOT / "data" / "monthly_notes" / f"{ym}.json")
    if not n:
        return ""
    esc = B.esc
    out = [f"<section class='card'><h2>この月の分析</h2><p>{esc(n.get('lead', ''))}</p>"]
    for x in n.get("findings") or []:
        out.append(f"<h3>{esc(x.get('title', ''))}</h3><p>{esc(x.get('text', ''))}</p>")
    if n.get("good"):
        out.append("<h3>よかった予想</h3><ul>" + "".join(f"<li><b>{esc(x.get('race', ''))}</b>：{esc(x.get('text', ''))}</li>" for x in n["good"]) + "</ul>")
    if n.get("bad"):
        out.append("<h3>悔しい外れ</h3><ul>" + "".join(f"<li><b>{esc(x.get('race', ''))}</b>：{esc(x.get('text', ''))}</li>" for x in n["bad"]) + "</ul>")
    if n.get("next"):
        out.append(f"<h3>次の月に向けて</h3><p>{esc(n['next'])}</p>")
    out.append(f"<p class='meta'>サイトの全予想の記録（{n.get('races')}レース）をもとにAIが{esc(n.get('updated', ''))}に書いた分析。</p></section>")
    return "".join(out)


def build_pages(B, by_date: dict, led: list[dict], venue_of_race: dict, today: str) -> dict[str, str]:
    esc, write, page, jsonld = B.esc, B.write, B.page, B.jsonld
    lastmod: dict[str, str] = {}
    months = sorted({d[:6] for d in by_date if d >= B.STATS_FROM}, reverse=True)
    index_rows = []
    for ym in months:
        sub = {d: ps for d, ps in by_date.items() if d.startswith(ym) and d >= B.STATS_FROM}
        rows = [r for r in led if r["date"].startswith(ym)]
        if not rows:
            continue
        t = B.totals(rows)
        st = sum(int(r["stake"]) for r in rows)
        rt = sum(int(r["return"]) for r in rows)
        # 場別
        vb = defaultdict(lambda: [0, 0, 0])
        for r in rows:
            v = venue_of_race.get(r["race_id"], "")
            vb[v][0] += int(r["stake"]); vb[v][1] += int(r["return"]); vb[v][2] += 1
        venues = sorted(((B.VENUE_NAME.get(v, v), x) for v, x in vb.items() if x[2] >= 5), key=lambda kv: -(kv[1][1] / kv[1][0]))
        # 買い方別（その月だけ）
        sg = strategy.collect(sub, B.STATS_FROM)
        best = []
        for grp, bs in sg.items():
            for k, b in bs.items():
                if b.n >= 20 and grp != "base":
                    best.append((k, b.roi(), b.n))
        best.sort(key=lambda x: -x[1])
        # 最高払戻
        top = max(rows, key=lambda r: int(r["return"]) - int(r["stake"]), default=None)
        top_p = None
        if top:
            for d, ps in sub.items():
                for p in ps:
                    if p["race_id"] == top["race_id"]:
                        top_p = (d, p)
        # 自信度別
        cb = defaultdict(lambda: [0, 0, 0])
        for r in rows:
            cb[r["confidence"]][0] += int(r["stake"]); cb[r["confidence"]][1] += int(r["return"]); cb[r["confidence"]][2] += 1
        # 日別の推移
        db = defaultdict(lambda: [0, 0, 0])
        for r in rows:
            db[r["date"]][0] += int(r["stake"]); db[r["date"]][1] += int(r["return"]); db[r["date"]][2] += 1
        days = sorted(db.items())
        cum_s = cum_r = 0
        pts = []
        for d, (s_, r_, n_) in days:
            cum_s += s_; cum_r += r_
            pts.append(100 * cum_r / cum_s if cum_s else 0)
        chart = B.svg_line(pts, labels=[B.md(d) for d, _ in days]) if len(pts) >= 2 else ""
        y, m = int(ym[:4]), int(ym[4:])
        cur = ym == today[:6]
        label = f"{y}年{m}月"
        lead = (f"{label}は{t['n']}レースを予想し、回収率{t['roi']}（購入{st:,}円→払戻{rt:,}円）、的中率{t['hit']}、◎の勝率{t['win']}・3着内率{t['top3']}だった。"
                + (f"買い方別では「{best[0][0]}」が{best[0][1]:.1f}%（{best[0][2]}レース）で最も高く、" if best else "")
                + (f"場別では{venues[0][0]}が{B.roi_txt(venues[0][1][0], venues[0][1][1])}で最も良く、{venues[-1][0]}が{B.roi_txt(venues[-1][1][0], venues[-1][1][1])}で最も悪かった。" if len(venues) >= 2 else "")
                + ("月の途中の集計で、毎日更新される。" if cur else ""))
        vrows = "".join(f"<tr><td>{esc(v)}</td><td>{x[2]}</td><td>{B.roi_txt(x[0], x[1])}</td><td>{x[1] - x[0]:+,}円</td></tr>" for v, x in venues)
        brows = "".join(f"<tr><td>{esc(k)}</td><td>{n}</td><td>{r:.1f}%</td></tr>" for k, r, n in best[:8])
        crows = "".join(f"<tr><td>{esc(c)}</td><td>{x[2]}</td><td>{B.roi_txt(x[0], x[1])}</td></tr>" for c, x in sorted(cb.items()))
        top_html = ""
        if top and top_p:
            d, p = top_p
            top_html = (f"<section class='card'><h2>月内の最高払戻</h2><p><a href='{B.race_path(d, p)}'>{esc(B.fmt_date(d))} {esc(B.race_label(p))}</a>："
                        f"購入{int(top['stake']):,}円→払戻{int(top['return']):,}円（回収率{B.roi_txt(int(top['stake']), int(top['return']))}）</p></section>")
        path = f"/monthly/{y}-{m:02d}/"
        body = (f"<p class='crumb'><a href='/'>トップ</a> › <a href='/monthly/'>月次レポート</a> › {esc(label)}</p>"
                f"<h1>{esc(label)}の成績レポート{'（集計中）' if cur else ''}</h1>{B.banner('monthly')}<p class='answer'>{esc(lead)}</p>"
                f"<div class='kpis'><div><b>{t['n']}</b><span>レース</span></div><div><b>{t['roi']}</b><span>回収率</span></div><div><b>{t['hit']}</b><span>的中率</span></div><div><b>{rt - st:+,}円</b><span>収支</span></div></div>"
                + _analysis_html(B, f"{y}-{m:02d}")
                + (f"<section class='card'><h2>累計回収率の推移（月内）</h2>{chart}</section>" if chart else "")
                + f"<section class='card'><h2>場別</h2><div class='scroll'><table><thead><tr><th>場</th><th>レース</th><th>回収率</th><th>収支</th></tr></thead><tbody>{vrows}</tbody></table></div><p class='meta'>5レース以上の場のみ。</p></section>"
                + (f"<section class='card'><h2>買い方別（この月）</h2><div class='scroll'><table><thead><tr><th>買い方</th><th>レース</th><th>回収率</th></tr></thead><tbody>{brows}</tbody></table></div><p class='meta'>20レース以上の区分のみ。買い方の意味は<a href='/strategy/'>買い方別の回収率</a>へ。</p></section>" if brows else "")
                + f"<section class='card'><h2>自信度別</h2><div class='scroll'><table><thead><tr><th>自信度</th><th>レース</th><th>回収率</th></tr></thead><tbody>{crows}</tbody></table></div></section>"
                + top_html
                + "<p class='meta'>買い目を1点100円ずつ買った計算で、外れも含む。買い目を出さなかった「見送り」と返還になったレースは含まない。</p>")
        ld = {"@context": "https://schema.org", "@type": "Article", "headline": f"{label}の成績レポート", "author": {"@type": "Organization", "name": B.SITE_NAME},
              "datePublished": f"{y}-{m:02d}-01", "dateModified": f"{today[:4]}-{today[4:6]}-{today[6:8]}" if cur else f"{y}-{m:02d}-{max(db)[6:8]}", "mainEntityOfPage": B.BASE_URL + path}
        write(path, page(f"{label}の成績レポート：回収率{t['roi']}・{t['n']}レース | {B.SITE_NAME}", body, path, desc=lead[:120], head_extra=jsonld(ld)))
        lastmod[path] = f"{today[:4]}-{today[4:6]}-{today[6:8]}" if cur else f"{y}-{m:02d}-{max(db)[6:8]}"
        index_rows.append(f"<li><a href='{path}'><span>{esc(label)}{'（集計中）' if cur else ''}</span><span>{t['n']}レース・回収率{t['roi']}</span></a></li>")
    write("/monthly/", page(f"月次レポート一覧 | {B.SITE_NAME}",
                            "<p class='crumb'><a href='/'>トップ</a> › 月次レポート</p><h1>月次レポート</h1>" + B.banner("monthly") +
                            "<p class='answer'>月ごとの成績を、場別・買い方別・自信度別にまとめた記事。月の途中は毎日更新し、月が変わると確定版として残る。</p>"
                            f"<ul class='days'>{''.join(index_rows)}</ul>", "/monthly/", desc="AI競馬予想の月ごとの成績レポート。", noindex=not index_rows))
    if index_rows:
        lastmod["/monthly/"] = f"{today[:4]}-{today[4:6]}-{today[6:8]}"
    return lastmod
