"""馬ごとのページ（/horse/<id>/）：このサイトでの評価点・印・想定勝率と、実際の着順の履歴。

2回以上評価した馬と、1回でもAIの寸評（data/horse_notes）がある馬について作る。IDは馬名のハッシュ。
"""
from __future__ import annotations

from collections import defaultdict

from extra import nfkc, pct, short_id


def _finish(p: dict, num) -> str:
    for row in (p.get("_result") or {}).get("rows") or []:
        if row.get("number") == num:
            return str(row.get("finish") or "")
    return ""


def _past_html(past: list, esc) -> str:
    if not past:
        return ""
    rows = "".join(
        f"<tr><td>{esc(r.get('date') or '')}</td><td>{esc(r.get('venue') or '')} {esc(r.get('race_name') or '')}</td>"
        f"<td>{esc(r.get('surface') or '')}{esc(r.get('distance') or '')}m・{esc(r.get('track') or '')}</td><td>{esc(r.get('field') or '')}頭</td>"
        f"<td>{esc(r.get('popularity') or '-')}番人気</td><td><b>{esc(r.get('finish') or '-')}着</b></td><td>{esc(r.get('corners') or '-')}</td><td>{esc(r.get('last3f') or '-')}</td></tr>"
        for r in past[:5])
    return ("<section class='card'><h2>近走（直近5走）</h2><div class='scroll'><table><thead><tr><th>日付</th><th>レース</th><th>コース</th><th>頭数</th>"
            f"<th>人気</th><th>着順</th><th>通過</th><th>上がり</th></tr></thead><tbody>{rows}</tbody></table></div>"
            "<p class='meta'>最後に評価したレースの出馬表に載っていた近走。</p></section>")


def build_pages(B, by_date: dict, today: str) -> dict[str, str]:
    esc, write, page, jsonld = B.esc, B.write, B.page, B.jsonld
    lastmod: dict[str, str] = {}
    horses: dict[str, list] = defaultdict(list)
    for d, ps in by_date.items():
        for p in ps:
            mm = B.mark_map(p)
            race_h = {h.get("number"): h for h in p["_race"].get("horses", []) or []}
            for e in p.get("horses", []):
                name = nfkc(e.get("name") or race_h.get(e.get("number"), {}).get("name") or "").replace(" ", "")
                if not name or len(name) < 2:
                    continue
                num = e.get("number")
                rh = race_h.get(num, {})
                horses[name].append({"d": d, "p": p, "num": num, "mark": mm.get(num, ""), "score": e.get("score"),
                                     "win_pct": e.get("win_pct"), "comment": e.get("comment") or "", "finish": _finish(p, num),
                                     "odds": rh.get("odds"), "pop": rh.get("popularity"), "jockey": rh.get("jockey"),
                                     "sire": rh.get("sire"), "sex_age": rh.get("sex_age"), "past": rh.get("past") or []})
    index_rows = []
    notes_dir = B.ROOT / "data" / "horse_notes"
    for name, items in horses.items():
        hid = short_id(name)
        note = B.load_json(notes_dir / f"{hid}.json") if (notes_dir / f"{hid}.json").exists() else None
        if len(items) < 2 and not note:
            continue
        B.LINK_HORSES.add(name)
        items.sort(key=lambda x: x["d"], reverse=True)
        path = f"/horse/{hid}/"
        n_hon = sum(1 for x in items if x["mark"] == "◎")
        runs = [x for x in items if x["finish"].isdigit()]
        wins = sum(1 for x in runs if x["finish"] == "1")
        top3 = sum(1 for x in runs if x["finish"] in ("1", "2", "3"))
        latest = items[0]
        prof = "・".join(x for x in (latest.get("sex_age") or "", f"父{latest['sire']}" if latest.get("sire") else "") if x)
        venues = sorted({B.VENUE_NAME.get(B.venue_of(x["p"]), B.venue_of(x["p"])) for x in items})
        lead = (f"{name}{'（' + prof + '）' if prof else ''}は、このサイトのAI予想で{len(items)}回評価され、◎は{n_hon}回。"
                + (f"結果が出ている{len(runs)}走で1着{wins}回・3着以内{top3}回（3着内率{pct(top3, len(runs))}）。" if runs else "")
                + f"主な出走場：{'・'.join(venues[:4])}。")
        rows = []
        for x in items:
            p = x["p"]
            wp = f"{x['win_pct']}%" if x["win_pct"] is not None else "-"
            od = f"{x['odds']}倍" if x.get("odds") else "-"
            fin = x["finish"] + "着" if x["finish"].isdigit() else (x["finish"] or "結果待ち")
            rows.append(f"<tr><td><a href='{B.race_path(x['d'], p)}'>{esc(B.md(x['d']))} {esc(B.race_label(p))}</a></td>"
                        f"<td>{esc(x['mark'] or '無印')}</td><td>{esc(x['score'] if x['score'] is not None else '-')}</td><td>{esc(wp)}</td>"
                        f"<td>{esc(od)}</td><td>{esc(fin)}</td><td>{esc(x['jockey'] or '')}</td></tr>")
        comments = "".join(f"<li><b>{esc(B.md(x['d']))} {esc(B.race_label(x['p']))}</b>：{esc(x['comment'])}</li>" for x in items[:6] if x["comment"])
        body = (f"<p class='crumb'><a href='/'>トップ</a> › <a href='/horse/'>馬別</a> › {esc(name)}</p>"
                f"<h1>{esc(name)} AI評価と成績の履歴</h1><p class='answer'>{esc(lead)}</p>"
                f"<div class='kpis'><div><b>{len(items)}</b><span>評価回数</span></div><div><b>{n_hon}</b><span>◎の回数</span></div>"
                f"<div><b>{wins}・{top3}</b><span>1着・3着内（{len(runs)}走）</span></div></div>"
                f"<section class='card'><h2>出走ごとのAI評価</h2><div class='scroll'><table><thead><tr><th>レース</th><th>印</th><th>評価点</th><th>想定勝率</th><th>単勝</th><th>着順</th><th>騎手</th></tr></thead>"
                f"<tbody>{''.join(rows)}</tbody></table></div></section>"
                + (f"<section class='card'><h2>AIの見立て</h2><div class='kaiko'>{B.zk('normal', 48)}<p><b>全頭くん</b>{esc(note['text'])}</p></div>"
                   f"<p class='meta'>近走と、このサイトのAIの評価をもとにAIが書いた寸評（{esc(B.md(note['updated']))}時点）。</p></section>" if note else "")
                + _past_html(latest.get("past") or [], esc)
                + (f"<section class='card'><h2>レースごとのAIの短評</h2><ul>{comments}</ul></section>" if comments else "")
                + "<p class='meta'>評価点はAIが5軸で採点した合計、想定勝率はAIの見立て。単勝は予想時点のオッズ。着順は主催者の発表が正。</p>")
        ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": B.SITE_NAME, "item": B.BASE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": "馬別", "item": B.BASE_URL + "/horse/"},
            {"@type": "ListItem", "position": 3, "name": name, "item": B.BASE_URL + path}]}
        write(path, page(f"{name} AI評価の履歴（印・想定勝率・着順）｜{B.SITE_NAME}", body, path, desc=lead[:120], head_extra=jsonld(ld)))
        lastmod[path] = f"{latest['d'][:4]}-{latest['d'][4:6]}-{latest['d'][6:8]}"
        index_rows.append((latest["d"], name, path, len(items), n_hon))
    index_rows.sort(key=lambda x: (x[0], x[3]), reverse=True)
    lis = "".join(f"<li><a href='{r[2]}'><span>{esc(r[1])}</span><span>{r[3]}回評価・◎{r[4]}回</span></a></li>" for r in index_rows[:300])
    write("/horse/", page(f"馬別 AI評価の履歴一覧｜{B.SITE_NAME}",
                          "<p class='crumb'><a href='/'>トップ</a> › 馬別</p><h1>馬別のAI評価履歴</h1>" + B.banner("horses") +
                          f"<p class='answer'>このサイトで2回以上評価した馬{len(index_rows):,}頭の、印・想定勝率・着順の履歴。最近出走した順。</p>"
                          f"<ul class='days'>{lis}</ul>" + ("<p class='meta'>300頭まで表示。</p>" if len(index_rows) > 300 else ""),
                          "/horse/", desc="AI予想で2回以上評価した馬の、印・評価点・想定勝率と実際の着順の履歴。", noindex=not index_rows))
    if index_rows:
        lastmod["/horse/"] = f"{today[:4]}-{today[4:6]}-{today[6:8]}"
    return lastmod
