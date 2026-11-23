"""馬ごとのページ（/horse/<id>/）：このサイトでの評価点・印・想定勝率と、実際の着順の履歴。

作る馬：2回以上評価した馬、1回でもAIの寸評（data/horse_notes）がある馬、重賞で評価した馬、
JRA発表のG1出走予定馬と重賞の特別登録馬で、JRAの馬ページの情報（data/horse_info）がある馬（AIの評価がまだでも作る。重賞の週は馬名で調べる人が多い）。
JRAの馬ページの情報がある馬は、毛色・馬名の意味・セリ・生産牧場・獲得賞金・これまでの成績も載せる。IDは馬名のハッシュ。
"""
from __future__ import annotations

import re
from collections import defaultdict

from extra import nfkc, pct, short_id

INFO: dict[str, dict] = {}  # 馬名 → data/horse_info の中身（JRAの馬ページ）
JRA = ("札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉")


def prepare(B) -> None:
    """build.py の最初の方（どの馬にリンクを張るか決める前）で1回だけ呼ぶ。"""
    INFO.clear()
    for f in (B.ROOT / "data" / "horse_info").glob("*.json"):
        x = B.load_json(f) or {}
        nm = nfkc(x.get("name") or "").replace(" ", "")
        if nm and x.get("profile"):
            INFO[nm] = x


def extra_names() -> set[str]:
    """評価が足りなくてもページを作る馬：JRA発表のG1出走予定馬と、これからの重賞の特別登録馬で、
    JRAの馬ページの情報がある馬（weekly.prepare のあとで呼ぶ）。"""
    import weekly  # noqa: PLC0415
    return {n for n in list(weekly.ENTRY_BY_HORSE) + list(weekly.NOM_BY_HORSE) if n in INFO}


def _finish(p: dict, num) -> str:
    for row in (p.get("_result") or {}).get("rows") or []:
        if row.get("number") == num:
            return str(row.get("finish") or "")
    return ""


TRACK = {"稍": "稍重", "不": "不良"}


def _course(r: dict) -> str:
    """「ダ1200m・稍重」。地方の近走は距離・芝ダが無いことがあるので、あるものだけ並べる。"""
    dist = r.get("distance")
    c = f"{r.get('surface') or ''}{dist}m" if dist else ""
    tr = TRACK.get(r.get("track") or "", r.get("track") or "")
    return "・".join(x for x in (c, tr) if x) or "-"


def _past_html(past: list, esc) -> str:
    if not past:
        return ""
    rs = past[:5]
    has_pop = any(r.get("popularity") for r in rs)  # 地方の近走は人気が無いので、そのときは列ごと出さない
    rows = "".join(
        f"<tr><td class='nw'>{esc(r.get('date') or '')}</td><td>{esc(r.get('venue') or '')} {esc(' '.join(nfkc(r.get('race_name') or '').split()))}</td>"
        f"<td>{esc(_course(r))}</td><td>{esc(r.get('field') or '-')}{'頭' if r.get('field') else ''}</td>"
        + (f"<td>{esc(r.get('popularity'))}番人気</td>" if has_pop and r.get('popularity') else "<td>-</td>" if has_pop else "")
        + f"<td><b>{esc(r.get('finish') or '-')}{'着' if str(r.get('finish') or '').isdigit() else ''}</b></td><td>{esc(r.get('corners') or '-')}</td><td>{esc(r.get('last3f') or '-')}</td></tr>"
        for r in rs)
    return ("<section class='card'><h2>近走（直近5走）</h2><div class='scroll'><table><thead><tr><th>日付</th><th>レース</th><th>コース・馬場</th><th>頭数</th>"
            + ("<th>人気</th>" if has_pop else "")
            + f"<th>着順</th><th>通過</th><th>上がり</th></tr></thead><tbody>{rows}</tbody></table></div>"
            "<p class='meta'>最後に評価したレースの出馬表に載っていた近走。</p></section>")


ABROAD = {"仏": "フランス", "英": "イギリス", "米": "アメリカ", "愛": "アイルランド", "豪": "オーストラリア", "ア首": "UAE", "サウ": "サウジアラビア",
          "香港": "香港", "華": "台湾", "韓": "韓国", "独": "ドイツ", "伊": "イタリア", "加": "カナダ", "新": "シンガポール"}
LOCAL = {"名古": "名古屋"}  # JRAの成績表で短く書かれる地方の競馬場


def _where(r: dict) -> str:
    """成績の開催場の書き方をそろえる：海外は「ジャック・ル（フランス）」、名古屋などは正式名に。"""
    v, n = r.get("venue") or "", nfkc(r.get("race_name") or "")
    if v in ABROAD:
        return f"{n}（{ABROAD[v]}）"
    return f"{LOCAL.get(v, v)}{' ' if v else ''}{n}"


def _ymd(s: str) -> str:
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s or "")
    return f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}" if m else ""


def _yen(s: str) -> str:
    """「32,910,000 円」→「3,291万円」、「1,234,560,000 円」→「12億3,456万円」。"""
    n = int(re.sub(r"\D", "", s or "") or 0)
    if not n:
        return ""
    man = n // 10000
    oku, rest = divmod(man, 10000)
    return (f"{oku}億" if oku else "") + (f"{rest:,}万" if rest else "") + "円"


def _info_runs_html(x: dict, esc) -> str:
    """JRAの馬ページに載っている成績（新しい順に10走）。"""
    runs = [r for r in x.get("runs") or [] if _ymd(r.get("date", ""))]
    if not runs:
        return ""
    rs = runs[:10]
    rows = "".join(
        f"<tr><td class='nw'>{esc(_ymd(r['date'])[:4])}/{int(_ymd(r['date'])[4:6])}/{int(_ymd(r['date'])[6:8])}</td>"
        f"<td>{esc(_where(r))}</td>"
        f"<td>{esc((r.get('surface') or '') + (str(r.get('distance')) + 'm' if r.get('distance') else ''))}</td>"
        f"<td>{esc(r.get('field') or '-')}{'頭' if r.get('field') else ''}</td>"
        f"<td>{esc(r.get('popularity') or '-')}{'番人気' if r.get('popularity') else ''}</td>"
        f"<td><b>{esc(r.get('finish') or '-')}{'着' if str(r.get('finish') or '').isdigit() else ''}</b></td><td>{esc(r.get('jockey') or '')}</td></tr>"
        for r in rs)
    rec = x.get("record") or {}
    other = rec.get("starts", 0) - rec.get("wins", 0) - rec.get("second", 0) - rec.get("third", 0)
    return ("<section class='card'><h2>これまでの成績（JRAの記録）</h2>"
            f"<p>通算{rec.get('starts', 0)}戦{rec.get('wins', 0)}勝（{rec.get('wins', 0)}-{rec.get('second', 0)}-{rec.get('third', 0)}-{max(other, 0)}）。新しい順に{len(rs)}走。</p>"
            "<div class='scroll'><table><thead><tr><th>日付</th><th>レース</th><th>コース</th><th>頭数</th><th>人気</th><th>着順</th><th>騎手</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
            f"<p class='meta'>JRAの競走馬情報（{esc((x.get('fetched') or '')[:10])}時点）。地方・海外のレースを含む。レース名は短く省略されていることがある。</p></section>")


def _clean(v: str) -> str:
    return "" if "�" in (v or "") else re.sub(r"\s+", " ", (v or "").replace("　", " ")).strip()


def _graded_wins(names: list[str]) -> dict[str, list]:
    try:
        import horse_info_cols as HC  # noqa: PLC0415  （scraper/ は weekly.prepare が読み込み先に足している）
        return HC.graded_wins([INFO[n] for n in names if n in INFO])
    except Exception:  # noqa: BLE001
        return {}


def _major_graded(p: dict) -> bool:
    """中央の重賞（G1〜G3・J・G1〜3）と、地方のダートグレード（Jpn1〜3・G1〜3）。地方だけの重賞（M2・S1 など）は入れない。"""
    import extra  # noqa: PLC0415
    r = p.get("_race") or {}
    g = extra.grade_of(r, p.get("race_name") or r.get("race_name") or r.get("title_text") or "") or ""
    return bool(re.match(r"(J・)?G[1-3]$|Jpn[1-3]$", nfkc(g).replace(" ", ""), re.I))


def _hist_runners() -> set[str]:
    """JRAの重賞の成績（data/graded_hist。過去20年）に名前がある馬。"""
    import weekly  # noqa: PLC0415
    out: set[str] = set()
    for ys in (weekly._K or {}).values():
        for r in ys.values():
            for x in r.get("rows") or []:
                if x.get("name"):
                    out.add(nfkc(x["name"]).replace(" ", ""))
    return out


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
                                     "sire": rh.get("sire"), "dam": rh.get("dam"), "damsire": rh.get("damsire"), "trainer": rh.get("trainer"),
                                     "sex_age": rh.get("sex_age"), "past": rh.get("past") or [], "profile": rh.get("profile") or {}})
    index_rows = []
    notes_dir = B.ROOT / "data" / "horse_notes"
    import weekly  # noqa: PLC0415
    names = [n for n in set(horses) | extra_names() if n in B.LINK_HORSES]
    gw = _graded_wins(names)
    hist = _hist_runners()
    for name in names:
        items = horses.get(name, [])
        hid = short_id(name)
        note = B.load_json(notes_dir / f"{hid}.json") if (notes_dir / f"{hid}.json").exists() else None
        info = INFO.get(name) or {}
        ip = info.get("profile") or {}
        items.sort(key=lambda x: x["d"], reverse=True)
        path = f"/horse/{hid}/"
        n_hon = sum(1 for x in items if x["mark"] == "◎")
        runs = [x for x in items if x["finish"].isdigit()]
        wins = sum(1 for x in runs if x["finish"] == "1")
        top3 = sum(1 for x in runs if x["finish"] in ("1", "2", "3"))
        latest = items[0] if items else {}
        cp = latest.get("profile") or {}  # 出馬表の馬の情報（11/21からは毛色・馬名の意味・取引市場も入る）
        sa = latest.get("sex_age") or (f"{ip.get('性別', '')}{re.sub(r'[^0-9]', '', ip.get('馬齢', ''))}" if ip.get("性別") else "")
        sire = latest.get("sire") or ip.get("父")
        prof = "・".join(x for x in (sa, f"父{sire}" if sire else "") if x)
        meaning = _clean(ip.get("馬名意味") or cp.get("馬名意味") or "")
        coat = _clean(ip.get("毛色") or cp.get("毛色") or "")
        market = _clean(ip.get("取引市場") or cp.get("取引市場") or "")
        info_runs = [r for r in info.get("runs") or [] if _ymd(r.get("date", ""))]
        venues = sorted({B.VENUE_NAME.get(B.venue_of(x["p"]), B.venue_of(x["p"])) for x in items}) or sorted({ABROAD.get(r["venue"], LOCAL.get(r["venue"], r["venue"])) for r in info_runs[:10] if r.get("venue")})
        # 馬名で調べる人が知りたい順に書く：どんな馬か → 次に走るレース → 直近の結果 → このサイトのAIの評価
        nxt = [x for x in items if x["d"] >= today and not x["finish"].isdigit() and x["finish"] not in ("取消", "除外", "中止")]
        nxt = sorted(nxt, key=lambda x: x["d"])[:1]
        last_run = runs[0] if runs else None
        ir = next((r for r in info_runs if (r.get("finish") or "").isdigit()), None) if not last_run else None
        jra = any(B.venue_of(x["p"]) in JRA for x in items) or any(r.get("venue") in JRA for r in info_runs[:10])
        ent = None if nxt else (weekly.ENTRY_BY_HORSE.get(name) or weekly.NOM_BY_HORSE.get(name))  # JRA発表の出走予定馬・特別登録馬に載っている（予想はまだ）
        ent_note = "（特別登録）" if ent and ent.get("kind") == "nom" else "（JRA発表の出走予定馬）"
        wins_g = gw.get(name) or []
        rec = info.get("record") or {}
        lead = (f"{name}{'（' + prof + '）' if prof else ''}の成績{'とAI評価' if items else ''}。"
                + (f"馬名の意味は「{meaning[:40]}」。" if meaning else "")
                + (f"次走は{B.md(nxt[0]['d'])}の{B.race_label(nxt[0]['p'])}（AIの印は{nxt[0]['mark'] or '無印'}）。" if nxt else "")
                + (f"次走予定は{weekly.day_jp(ent['date'])}の{ent['name']}{ent_note}。" if ent else "")
                + (f"直近は{B.md(last_run['d'])}の{B.race_label(last_run['p'])}で{last_run['finish']}着"
                   + (f"（{last_run['pop']}番人気）" if last_run.get("pop") else "") + "。" if last_run else "")
                + (f"直近は{int(_ymd(ir['date'])[4:6])}/{int(_ymd(ir['date'])[6:8])}の{_where(ir).replace(' ', '')}で{ir['finish']}着"
                   + (f"（{ir['popularity']}番人気）" if ir.get("popularity") else "") + "。" if ir else "")
                + (f"通算{rec.get('starts', 0)}戦{rec.get('wins', 0)}勝。" if rec.get("starts") else "")
                + (f"JRAの重賞は{len(wins_g)}勝。" if wins_g else "")
                + (f"このサイトのAI予想では{len(items)}回評価し、◎は{n_hon}回。" if items else "このサイトのAIの評価は、出走するレースの予想で追加される。")
                + (f"結果が出ている{len(runs)}走で1着{wins}回・3着以内{top3}回（3着内率{pct(top3, len(runs))}）。" if runs else "")
                + (f"主な出走場：{'・'.join(venues[:4])}。" if venues else ""))
        trainer = latest.get("trainer") or _clean(ip.get("調教師名"))
        prof_rows = [("性齢", sa), ("毛色", coat), ("父", sire), ("母", latest.get("dam") or ip.get("母")),
                     ("母の父", latest.get("damsire") or ip.get("母の父")), ("調教師", trainer), ("馬主", _clean(ip.get("馬主名"))),
                     ("生産牧場", "・".join(x for x in (_clean(ip.get("生産牧場")), _clean(ip.get("産地"))) if x)),
                     ("セリ（取引市場）", market), ("獲得賞金", _yen(ip.get("総賞金") or "")),
                     ("馬名の意味", meaning),
                     ("主な出走", (("中央競馬" if jra else "地方競馬") + "（" + "・".join(venues[:4]) + "）") if venues else ""),
                     ("最近の騎手", "、".join(dict.fromkeys(x["jockey"] for x in items[:5] if x.get("jockey"))))]
        prof_html = ("<section class='card'><h2>プロフィール</h2><div class='scroll'><table><tbody>"
                     + "".join(f"<tr><th>{k}</th><td>{esc(v)}</td></tr>" for k, v in prof_rows if v) + "</tbody></table></div>"
                     + ("<p class='meta'>毛色・馬名の意味・セリ・生産牧場・獲得賞金はJRAの競走馬情報による。</p>" if info or meaning else "") + "</section>")
        wins_html = ""
        if wins_g:
            order = {"G1": 0, "J・G1": 0, "G2": 1, "J・G2": 1, "G3": 2, "J・G3": 2}
            lis = "".join(f"<li>{esc(d[:4])}年 {esc(n)}（{esc(gr)}）</li>" for d, n, gr in sorted(wins_g, key=lambda w: (order.get(w[2], 3), w[0]))[:8])
            wins_html = (f"<section class='card'><h2>JRAの重賞の勝ち（{len(wins_g)}勝）</h2><ul>{lis}</ul>"
                         "<p class='meta'>2016年以降のJRAの重賞（障害を含む）。このサイトが集めた重賞の全着順と、JRAの競走馬情報の成績を照らし合わせた。</p></section>")
        next_html = ""
        if nxt:
            x = nxt[0]
            next_html = (f"<p class='notice'>次走：<a href='{B.race_path(x['d'], x['p'])}'>{esc(B.md(x['d']))} {esc(B.race_label(x['p']))}</a>"
                         f"（AIの印：{esc(x['mark'] or '無印')}{'・想定勝率' + str(x['win_pct']) + '%' if x['win_pct'] is not None else ''}）→ 全頭の評価と買い目を見る</p>")
        # 馬名で調べた人の次の1クリック：次走があればそのレースの予想と対戦、G1の出走予定馬ならその一覧、無ければ今週末のまとめ
        if ent:
            next_html = (f"<p class='notice'>次走予定：<a href='/graded/{ent['slug']}/#entries'>{esc(weekly.day_jp(ent['date']))} {esc(ent['name'])}</a>"
                         f"{'（JRAの特別登録馬に掲載）' if ent.get('kind') == 'nom' else '（JRA発表の出走予定馬に掲載）'}→ ほかの登録馬と、直近の出走・成績の一覧を見る</p>")
            nstep = weekly.next_card("horse", slug=ent["slug"])
        else:
            nstep = weekly.next_card("horse", race=(nxt[0]["d"], nxt[0]["p"]) if nxt else ((items[0]["d"], items[0]["p"]) if items and items[0]["d"] >= B.TODAY else None))
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
        if items:
            kpis = (f"<div class='kpis'><div><b>{len(items)}</b><span>評価回数</span></div><div><b>{n_hon}</b><span>◎の回数</span></div>"
                    f"<div><b>{wins}・{top3}</b><span>1着・3着内（{len(runs)}走）</span></div></div>")
            evals = (f"<section class='card'><h2>出走ごとのAI評価</h2><div class='scroll'><table><thead><tr><th>レース</th><th>印</th><th>評価点</th><th>想定勝率</th><th>単勝</th><th>着順</th><th>騎手</th></tr></thead>"
                     f"<tbody>{''.join(rows)}</tbody></table></div></section>")
        else:
            kpis = (f"<div class='kpis'><div><b>{rec.get('starts', 0)}</b><span>通算の出走</span></div><div><b>{rec.get('wins', 0)}</b><span>1着</span></div>"
                    f"<div><b>{esc(_yen(ip.get('総賞金') or '') or '-')}</b><span>獲得賞金</span></div></div>")
            evals = ("<section class='card'><h2>このサイトのAIの評価</h2><p>まだ評価していない。出走するレースのAI予想（全頭の評価点・印・買い目）を出したときに、"
                     "このページにも評価の記録が加わる。</p></section>")
        body = (f"<p class='crumb'><a href='/'>トップ</a> › <a href='/horse/'>馬別</a> › {esc(name)}</p>"
                f"<h1>{esc(name)}の成績{'とAI評価' if items else '・次走と馬名の意味' if meaning else 'と次走'}</h1><p class='answer'>{esc(lead)}</p>{next_html}"
                + kpis + evals
                + (f"<section class='card'><h2>AIの見立て</h2><div class='kaiko'>{B.zk('normal', 48)}<p><b>全頭くん</b>{esc(note['text'])}</p></div>"
                   f"<p class='meta'>近走と、このサイトのAIの評価をもとにAIが書いた寸評（{esc(B.md(note['updated']))}時点）。</p></section>" if note else "")
                + nstep + wins_html
                + (_info_runs_html(info, esc) if info_runs else _past_html(latest.get("past") or [], esc)) + prof_html
                + (f"<section class='card'><h2>レースごとのAIの短評</h2><ul>{comments}</ul></section>" if comments else "")
                + ("<p class='meta'>評価点はAIが5軸で採点した合計、想定勝率はAIの見立て。単勝は予想時点のオッズ。着順は主催者の発表が正。</p>" if items else
                   "<p class='meta'>成績はJRAの競走馬情報による。出走予定はJRAの発表で、回避・除外などで変わることがある。</p>"))
        ld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": B.SITE_NAME, "item": B.BASE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": "馬別", "item": B.BASE_URL + "/horse/"},
            {"@type": "ListItem", "position": 3, "name": name, "item": B.BASE_URL + path}]}
        head = f"{name}{'（' + sa + '）' if sa else ''}の成績・"
        if items:
            title = head + ("次走・" if nxt or ent else "") + ("馬名の意味とAI評価" if meaning else ("AI評価" if nxt or ent else "近走とAI評価"))
        else:
            title = head + ("次走と馬名の意味" if meaning else "次走と血統")
        # Googleに載せる馬のページ（2026-11-23〜）は、重賞に関わる馬だけ：
        #   このサイトが予想した重賞（中央の重賞・ダートグレード）に出た馬／これからの重賞に特別登録・出走予定の馬／JRAの重賞の成績に名前がある馬。
        # 11/20の「JRAの馬情報あり、またはAIが3回以上評価」は、地方の馬のほぼ全部が数週間で3回に届き、3日で1,553→2,020ページに増えたので締め直した。
        # 条件に合わないページも残し、サイト内のリンクもそのまま。Googleにだけ載せない設定（noindex="google"）にしてサイトマップから外す
        index_me = (any(_major_graded(x["p"]) for x in items) or name in hist
                    or bool(weekly.ENTRY_BY_HORSE.get(name) or weekly.NOM_BY_HORSE.get(name)))
        write(path, page(f"{title}｜{B.SITE_NAME}", body, path, desc=lead[:120], head_extra=jsonld(ld), noindex=False if index_me else "google"))
        last_d = latest.get("d") or _ymd(info_runs[0]["date"]) if (items or info_runs) else today
        if index_me:
            lastmod[path] = max(f"{last_d[:4]}-{last_d[4:6]}-{last_d[6:8]}", (info.get("fetched") or "")[:10] if not items else "")
        index_rows.append((last_d, name, path, len(items), n_hon))
    index_rows.sort(key=lambda x: (x[0], x[3]), reverse=True)
    lis = "".join(f"<li><a href='{r[2]}'><span>{esc(r[1])}</span><span>{f'{r[3]}回評価・◎{r[4]}回' if r[3] else '重賞に登録・AI評価はこれから'}</span></a></li>"
                  for r in index_rows[:300])
    write("/horse/", page(f"馬別 AI評価の履歴一覧｜{B.SITE_NAME}",
                          "<p class='crumb'><a href='/'>トップ</a> › 馬別</p><h1>馬別のAI評価履歴</h1>" + B.banner("horses") +
                          f"<p class='answer'>このサイトで評価した馬と、これからの重賞に登録した馬の{len(index_rows):,}頭の、印・想定勝率・着順の履歴。最近出走した順。</p>"
                          f"<ul class='days'>{lis}</ul>" + ("<p class='meta'>300頭まで表示。</p>" if len(index_rows) > 300 else ""),
                          "/horse/", desc="AI予想で評価した馬とG1の出走予定馬の、印・評価点・想定勝率と実際の着順の履歴。", noindex=not index_rows))
    if index_rows:
        lastmod["/horse/"] = f"{today[:4]}-{today[4:6]}-{today[6:8]}"
    return lastmod
