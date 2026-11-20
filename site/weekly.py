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
import re
import sys
from datetime import datetime, timedelta

WD = "月火水木金土日"
JRA = ("札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉")
# 手で書いた特集（columns の series）と重賞ページの対応
FEATURE_RACE = {"eliza2026": "queen-elizabeth-cup", "mile2026": "mile-championship", "jc2026": "japan-cup",
                "jcd2026": "champions-cup", "arima2026": "arima-kinen", "hjf2026": "hanshin-juvenile-fillies", "afs2026": "asahi-hai-fs",
                "daishogai2026": "nakayama-daishogai", "hopeful2026": "hopeful-stakes", "tdt2026": "tokyo-daishoten"}

_B = None
TODAY = ""
SCHED: list[dict] = []           # これから（と直近）のJRA重賞：{date, name, grade, venue, course, slug}
SCHED_BY_SLUG: dict[str, list[dict]] = {}
PREDS: dict[str, list[tuple]] = {}  # 重賞の slug → [(日付, 予想)]（古い順）
FEAT: dict[str, list[dict]] = {}   # 重賞の slug → 特集の記事（order 順）
GDATA: dict[str, list[dict]] = {}  # 重賞の slug → 過去20年データ記事
ENTRIES: dict[str, dict] = {}       # 重賞の slug → 出走予定馬（JRA発表のプレレーティング。これから行われるレースだけ）
ENTRY_BY_HORSE: dict[str, dict] = {}  # 馬名 → {date, slug, name}（出走予定馬に載っている、これからのG1）
LAST_RUN: dict[str, dict] = {}      # 馬名 → このサイトで予想したレースでの直近の結果（出走予定馬の分だけ）
GRADED_YEAR: dict[str, list] = {}   # 馬名 → 今年のJRA重賞の出走（data/graded_hist。出走予定馬の分だけ）
NOMS: dict[str, dict] = {}          # 重賞の slug → 特別レース登録馬（data/nominations。JRA発表。プレレーティングより前から出る）
NOM_BY_HORSE: dict[str, dict] = {}  # 馬名 → {date, slug, name}（これからの重賞に特別登録している）
WAKU: dict[str, dict] = {}          # 重賞の slug → 出走馬・枠順（JRA発表。data/races の出馬表か data/waku。これから行われるレースだけ）
_K: dict = {}                       # graded_cols.keyed（JRA重賞の全年の結果。特集まとめの結果の箱に使う）
GRADES = ("G1", "G2", "G3", "J・G1", "J・G2", "J・G3")
JRA_VENUE_CODE ={"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京", "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}


def _schedule(root, today: str) -> list[dict]:
    global _K
    try:
        sys.path.insert(0, str(root / "scraper"))
        import graded_cols as G  # noqa: PLC0415
        with contextlib.redirect_stdout(io.StringIO()):
            keyed = G.keyed(G.load_all())
    except Exception:  # noqa: BLE001
        return []
    _K = keyed
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
    _load_entries(B, by_date)
    _load_nominations(B)
    _load_waku(B)


def _load_nominations(B) -> None:
    """data/nominations（scraper/jra_nominations.py が「特別レース登録馬」から作る）のうち、これからの重賞の分を読む。"""
    import unicodedata  # noqa: PLC0415
    import extra  # noqa: PLC0415
    nf = lambda x: unicodedata.normalize("NFKC", str(x or "")).replace(" ", "").replace("\u3000", "")
    NOMS.clear(); NOM_BY_HORSE.clear()
    for f in sorted((B.ROOT / "data" / "nominations").glob("*.json")):
        d = B.load_json(f) or {}
        if not d.get("grade") or d.get("date", "") < TODAY or not d.get("horses"):
            continue
        venue = JRA_VENUE_CODE.get((d.get("cname") or "")[9:11], "")
        slug = extra.graded_slug(d.get("race") or "", B.VENUE_SLUG.get(venue, "venue"))
        if slug not in SCHED_BY_SLUG:
            continue
        sch = SCHED_BY_SLUG.get(slug) or []
        name = next((r["name"] for r in sch if r["date"] == d["date"]), "") or d.get("race", "")
        NOMS[slug] = {**d, "name": name, "venue": venue}
        for h in d["horses"]:
            NOM_BY_HORSE.setdefault(nf(h["name"]), {"date": d["date"], "slug": slug, "name": name, "kind": "nom"})


def nominations_section(slug: str) -> str:
    """プレレーティング（出走予定馬）がまだの重賞に出す「特別登録馬」の表（JRA発表）。"""
    d = NOMS.get(slug)
    if not d or slug in ENTRIES or _B is None:
        return ""
    B, esc = _B, _B.esc
    import horses  # noqa: PLC0415
    import unicodedata  # noqa: PLC0415
    nf = lambda x: unicodedata.normalize("NFKC", str(x or "")).replace(" ", "").replace("\u3000", "")
    rows = ""
    for h in d["horses"]:
        nm = nf(h["name"])
        x = horses.INFO.get(nm) or {}
        ip = x.get("profile") or {}
        sa = h.get("sex_age") or (f"{ip.get('性別', '')}{re.sub(r'[^0-9]', '', ip.get('馬齢', ''))}" if ip.get("性別") else "")
        run = next((r for r in x.get("runs") or [] if (r.get("finish") or "").isdigit()), None)
        rd = (run or {}).get("date", "")
        rd = rd[5:] if rd[:4] == TODAY[:4] else rd  # 今年なら「11月1日」、去年より前なら「2025年12月28日」
        last = f"{esc(rd)} {esc(horses._where(run))} {esc(run.get('finish', ''))}着" if run else "-"
        rec = x.get("record") or {}
        rows += (f"<tr><td class='nm'>{B.link_horse(h['name'])}</td><td class='nw'>{esc(sa)}</td>"
                 f"<td>{esc(re.sub(r'（.*?）', '', ip.get('調教師名', '')).strip())}</td><td>{last}</td>"
                 f"<td class='nw'>{esc(str(rec.get('starts', '')) + '戦' + str(rec.get('wins', '')) + '勝') if rec else '-'}</td></tr>")
    when = f"このサイトのAI予想は{esc(publish_when(d['date']))}（枠順の確定後）。"
    return (f"<section class='card' id='entries'><h2>{esc(d['name'])}{d['date'][:4]}の特別登録馬（{len(d['horses'])}頭）</h2>"
            f"<p>{esc(day_jp(d['date']))}の{esc(d['name'])}に特別登録した馬の一覧（JRA発表）。実際に出走する馬は、出馬投票と枠順の確定で決まる。{when}</p>"
            "<div class='scroll'><table class='ent'><thead><tr><th>馬名</th><th>性齢</th><th>調教師</th><th>直近の出走</th><th>通算</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
            f"<p class='meta'>出典：JRA「特別レース登録馬」（{esc((d.get('fetched') or '')[:10])}時点）。直近の出走と通算の成績はJRAの競走馬情報による（地方・海外のレースを含む）。"
            "外国馬・地方馬は一覧に入らないことがある。</p></section>")


def _load_entries(B, by_date: dict) -> None:
    """data/entries（scraper/jra_entries.py が JRA のプレレーティングから作る）を読み、出走予定馬の前走と今年の重賞成績を添える。"""
    import unicodedata  # noqa: PLC0415
    nf = lambda x: unicodedata.normalize("NFKC", str(x or "")).replace(" ", "").replace("\u3000", "")
    ENTRIES.clear(); ENTRY_BY_HORSE.clear(); LAST_RUN.clear(); GRADED_YEAR.clear()
    for f in sorted((B.ROOT / "data" / "entries").glob("*.json")):
        d = B.load_json(f) or {}
        if not d.get("horses") or d.get("date", "") < TODAY:
            continue
        if d["slug"] in ENTRIES and ENTRIES[d["slug"]]["date"] <= d["date"]:
            continue
        sch = SCHED_BY_SLUG.get(d["slug"]) or []
        d["name"] = next((r["name"] for r in sch if r["date"] == d["date"]), "") or d.get("race", "")
        d["course"] = next((r["course"] for r in sch if r["date"] == d["date"]), "")
        ENTRIES[d["slug"]] = d
    for slug, d in ENTRIES.items():
        for h in d["horses"]:
            ENTRY_BY_HORSE.setdefault(nf(h["name"]), {"date": d["date"], "slug": slug, "name": d["name"]})
    if not ENTRY_BY_HORSE:
        return
    for d in sorted(by_date):
        if d > TODAY:
            continue
        for p in by_date[d]:
            rows = (p.get("_result") or {}).get("rows") or []
            if not rows:
                continue
            fin = {x.get("number"): x.get("finish") for x in rows}
            for h in p["_race"].get("horses") or []:
                nm = nf(h.get("name"))
                if nm in ENTRY_BY_HORSE and fin.get(h.get("number")) not in (None, ""):
                    LAST_RUN[nm] = {"date": d, "path": B.race_path(d, p), "label": B.race_label(p), "finish": str(fin.get(h.get("number"))),
                                    "pop": h.get("popularity")}
    try:
        import graded_cols as G  # noqa: PLC0415
        with contextlib.redirect_stdout(io.StringIO()):
            all_ = G.load_all()
        for r in all_.get(int(TODAY[:4]), []):
            for x in r.get("rows") or []:
                nm = nf(x.get("name"))
                if nm in ENTRY_BY_HORSE:
                    GRADED_YEAR.setdefault(nm, []).append({"date": r["date"], "race": r.get("abbr", ""), "grade": r.get("grade", ""),
                                                           "fin": x.get("fin"), "pop": x.get("pop")})
        for v in GRADED_YEAR.values():
            v.sort(key=lambda a: a["date"])
    except Exception:  # noqa: BLE001
        pass


def _rating_num(h: dict) -> int:
    m = re.match(r"\d+", h.get("rating") or "")
    return int(m.group(0)) if m else 0


def entries_section(slug: str) -> str:
    """重賞ページに出す「出走予定馬」の表（JRA発表）。これから行われるレースで、発表済みのときだけ。"""
    d = ENTRIES.get(slug)
    if not d or _B is None:
        return ""
    B, esc = _B, _B.esc
    import unicodedata  # noqa: PLC0415
    nf = lambda x: unicodedata.normalize("NFKC", str(x or "")).replace(" ", "").replace("\u3000", "")
    md_ = lambda x: f"{int(x[4:6])}/{int(x[6:8])}"
    rows = ""
    for h in sorted(d["horses"], key=lambda h: (-_rating_num(h), h["name"])):
        nm = nf(h["name"])
        gy = [a for a in GRADED_YEAR.get(nm, []) if a["date"] < d["date"]]
        lr = LAST_RUN.get(nm)
        gl = gy[-1] if gy else None
        last = ""
        if lr and (not gl or lr["date"] >= gl["date"]):
            last = (f"<a href='{lr['path']}'>{esc(md_(lr['date']))} {esc(lr['label'].split(' ', 1)[-1])}</a> {esc(lr['finish'])}"
                    + ("着" if lr["finish"].isdigit() else "") + (f"（{esc(lr['pop'])}人気）" if lr.get("pop") else ""))
        elif gl:
            f_ = gl["fin"]
            last = (f"{esc(md_(gl['date']))} {esc(gl['race'])} {esc(f_)}{'着' if isinstance(f_, int) else ''}"
                    + (f"（{esc(gl['pop'])}人気）" if gl.get("pop") else ""))
        ran = [a for a in gy if isinstance(a["fin"], int)]
        rec = f"{len(ran)}戦{sum(a['fin'] == 1 for a in ran)}勝" if ran else "-"
        tag = (f"<small>（{esc(h.get('country') or '外国')}の馬）</small>" if h.get("foreign")
               else (f"<small>（{esc(h['origin'])}）</small>" if h.get("origin") else ""))
        rows += (f"<tr><td class='nm'>{B.link_horse(h['name'])}{tag}</td><td class='nw'>{esc(h.get('sex', ''))}{esc(h.get('age', ''))}</td>"
                 f"<td>{esc(h.get('trainer', ''))}</td><td>{last or '-'}</td><td class='nw'>{esc(rec)}</td>"
                 f"<td>{esc(h.get('rating') or '-')}<small>{('　' + esc(h['rating_race'])) if h.get('rating_race') else ''}</small></td></tr>")
    n = len(d["horses"])
    reg = (f"特別登録{d['registered']}頭" + (f"と外国馬{d['registered_foreign']}頭" if d.get("registered_foreign") else "")) if d.get("registered") else f"{n}頭"
    pub = d.get("published") or ""
    pub_t = f"{int(pub[5:7])}月{int(pub[8:10])}日" if len(pub) == 10 else ""
    mx = f"出走できるのは最大{d['max_runners']}頭で、" if d.get("max_runners") else ""
    pred = next((p for dd, p, *_ in PREDS.get(slug) or [] if dd == d["date"]), None)
    when = ("AI予想を公開中：<a href='" + B.race_path(d["date"], pred) + "'>全頭の評価と買い目を見る</a>" if pred
            else f"このサイトのAI予想は{esc(publish_when(d['date']))}（枠順の確定後）。")
    return (f"<section class='card' id='entries'><h2>{esc(d['name'])}{d['date'][:4]}の出走予定馬（{esc(reg)}）</h2>"
            f"<p>{esc(day_jp(d['date']))}の{esc(d['name'])}に登録した馬の一覧（JRAが{esc(pub_t)}に発表した、出走予定馬のプレレーティング）。"
            f"{esc(mx)}登録がそれより多いときは、JRAの決まりで出走できる馬が決まる。下の表はレーティングの高い順。{when}</p>"
            "<div class='scroll'><table class='ent'><thead><tr><th>馬名</th><th>性齢</th><th>調教師</th><th>直近の出走（わかる範囲）</th><th>今年のJRA重賞</th><th>レーティング（今年の最高値）</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
            f"<p class='meta'>出典：JRA「<a href='{esc(d['source'])}' target='_blank' rel='noopener'>{esc(d['name'])} プレレーティング</a>」。"
            "直近の出走は、このサイトが予想したレース（10月26日から）とJRAの重賞の成績のうち新しいもの。オープン特別や海外のレースなどは入らないことがある。今年のJRA重賞は1月からの重賞だけの成績（海外・地方・重賞以外は含まない）。"
            "回避・除外などで変わることがあるので、正式な出走馬は枠順の確定（JRAの発表）で確認してほしい。</p></section>")


def entries_date(slug: str) -> str:
    """題名の元にしたJRAの発表（枠順・出走馬・出走予定馬）を取り込んだ日（YYYY-MM-DD）。サイトマップの更新日に使う。無ければ空。"""
    x = _pre(slug)
    if x:
        return x["since"]
    d = ENTRIES.get(slug)
    return (d.get("fetched") or d.get("published") or "")[:10] if d else ""


def entries_title(slug: str) -> tuple[str, str] | None:
    """JRAの発表（枠順・出走馬・出走予定馬）が出ていて、そのレースの予想がまだのときの (題名の頭, 説明文)。"""
    x = _pre(slug)
    return (x["head"], x["desc"]) if x else None


def _iso(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def _waku_day(d: str) -> str:
    """枠順（馬番）が出る日。JRA：G1など前日発売のある重賞は、その週の金曜の朝（G1の週は9時すぎ）。
    出走馬（馬番なし）はその前の木曜の16時すぎ。有馬記念は木曜の夕方の公開抽選で決まる（https://www.jra.go.jp/faq/pop02/2_2.html）。"""
    x = _dt(d)
    return (x - timedelta(days=(x.weekday() - 4) % 7)).strftime("%Y%m%d")


def _waku_when(slug: str, d: str) -> str:
    """出走馬が決まってから枠順が出るまでの「いつ」。はっきり分かるのは土日のG1（金曜の朝）と有馬記念（木曜の夕方の公開抽選）だけ。
    ほかの重賞（前日発売の無いレース・月曜の祝日のレースなど）は日が変わるので空（「枠順の確定で決まる」とだけ書く）。"""
    x = _dt(d)
    if slug == "arima-kinen":
        return f"{day_jp((x - timedelta(days=(x.weekday() - 3) % 7)).strftime('%Y%m%d'))}の夕方の公開抽選"
    if _sched_of(slug, d).get("grade") in ("G1", "J・G1") and x.weekday() in (5, 6):
        return f"{day_jp(_waku_day(d))}の朝"
    return ""


def _kg(w) -> str:
    try:
        return f"{float(w):.1f}"
    except (TypeError, ValueError):
        return str(w or "")


def _nf(x) -> str:
    import unicodedata  # noqa: PLC0415
    return unicodedata.normalize("NFKC", str(x or "")).replace(" ", "").replace("　", "")


def _top_names(slug: str, names: list[str], n: int = 3) -> list[str]:
    """説明文に名前を出す馬：JRAのプレレーティングの高い順。無い馬は獲得賞金（JRAの馬ページの総賞金）の多い順。"""
    import horses  # noqa: PLC0415
    rt = {_nf(h["name"]): _rating_num(h) for h in (ENTRIES.get(slug) or {}).get("horses") or []}

    def prize(nm: str) -> int:
        s = ((horses.INFO.get(_nf(nm)) or {}).get("profile") or {}).get("総賞金") or ""
        return int(re.sub(r"\D", "", s) or 0)
    return sorted(names, key=lambda nm: (-rt.get(_nf(nm), 0), -prize(nm)))[:n]


def _sched_of(slug: str, d: str) -> dict:
    return next((r for r in SCHED_BY_SLUG.get(slug) or [] if r["date"] == d), {})


def _pre(slug: str) -> dict | None:
    """これから行われる重賞で、予想がまだのときの、JRAの発表のうち新しいもの：
    枠順（馬番あり）→ 出走馬（木曜の夕方。馬番なし）→ 出走予定馬（G1のプレレーティング）。
    特別登録馬は外国馬が入らず頭数が実際と違うことがあるので、題名には使わない。{phase, head, desc, since} か None。"""
    up = sorted((r for r in SCHED_BY_SLUG.get(slug) or [] if r["date"] >= TODAY), key=lambda r: r["date"])
    if not up or any(dd == up[0]["date"] for dd, *_ in PREDS.get(slug) or []):
        return None
    r = up[0]
    d, name, y = r["date"], r["name"], r["date"][:4]
    where = f"{r.get('venue', '')}{r.get('course', '')}"
    prev = day_jp((_dt(d) - timedelta(days=1)).strftime("%Y%m%d"))
    w = WAKU.get(slug)
    if w and w["date"] == d:
        hs = w["horses"]
        top = _top_names(slug, [h["name"] for h in hs])
        if w["numbered"]:
            pos = {h["name"]: h for h in hs}
            desc = (f"{day_jp(d)}に{where}で行われる{name}{y}の枠順が確定した。"
                    + "、".join(f"{x}は{pos[x].get('frame')}枠{pos[x].get('number')}番" for x in top)
                    + f"。{len(hs)}頭の騎手・斤量つき。AI予想は{prev}の夜までに公開。")
            return {"phase": "waku", "date": d, "head": f"{name}{y}の枠順確定・出走馬{len(hs)}頭", "desc": desc, "since": w["since"]}
        desc = (f"{day_jp(d)}に{where}で行われる{name}{y}の出走馬{len(hs)}頭が決まった。{'、'.join(top)}など、騎手・斤量つき。"
                f"馬番と枠番は{_waku_when(slug, d) or '枠順の確定'}で決まり、AI予想は{prev}の夜までに公開。")
        return {"phase": "runners", "date": d, "head": f"{name}{y}の出走馬確定（{len(hs)}頭）", "desc": desc, "since": w["since"]}
    e = ENTRIES.get(slug)
    if e and e["date"] == d:
        n = len(e["horses"])
        names = "、".join(h["name"] for h in sorted(e["horses"], key=lambda h: -_rating_num(h))[:3])
        desc = (f"{day_jp(d)}に{e.get('venue', '') or r.get('venue', '')}{e.get('course', '') or r.get('course', '')}で行われる{e['name']}{y}の出走予定馬{n}頭。"
                f"{names}など、直近の出走・今年の重賞成績・レーティングつき。AI予想は{prev}の夜までに公開。")
        return {"phase": "entries", "date": d, "head": f"{e['name']}{y}の出走予定馬（{n}頭）", "desc": desc,
                "since": (e.get("fetched") or e.get("published") or "")[:10]}
    return None


def _load_waku(B) -> None:
    """出走馬・枠順（JRA発表）。予想の元データの出馬表（data/races。近走つき。金曜の昼と前日の夕方に取る）と、
    scraper/jra_waku.py が木曜の夕方（出走馬。馬番なし）と金曜の朝（枠順）に取る data/waku を見て、馬番の入っている方を使う。"""
    import extra  # noqa: PLC0415
    WAKU.clear()
    hi = (_dt(TODAY) + timedelta(days=5)).strftime("%Y%m%d")
    for d in sorted({r["date"] for r in SCHED if TODAY <= r["date"] <= hi}):
        cands = [("card", f) for f in sorted((B.ROOT / "data" / "races" / d).glob("jra_*.json"))]
        cands += [("waku", f) for f in sorted((B.ROOT / "data" / "waku").glob(f"{d}_*.json"))]
        for src, f in cands:
            x = B.load_json(f) or {}
            if x.get("grade") not in GRADES or not x.get("horses"):
                continue
            slug = extra.graded_slug(x.get("race_name") or x.get("title_text") or "", B.VENUE_SLUG.get(x.get("venue", ""), "venue"))
            if not _sched_of(slug, d):
                continue
            num = all(h.get("number") for h in x["horses"])
            cur = WAKU.get(slug)
            if cur and (cur["numbered"], cur["src"] == "card") >= (num, src == "card"):
                continue
            WAKU[slug] = {**x, "date": d, "src": src, "numbered": num,
                          "since": (x.get("fetched") or "")[:10] or _iso(min(TODAY, _waku_day(d)))}


def waku_section(slug: str) -> str:
    """これから行われる重賞の出走馬・枠順の表（JRA発表）。AI予想を公開していれば、印と予想ページへのリンクも付ける。"""
    w = WAKU.get(slug)
    if not w or _B is None:
        return ""
    B, esc = _B, _B.esc
    d = w["date"]
    name = _sched_of(slug, d).get("name") or w.get("race_name", "")
    pred = next((p for dd, p, *_ in PREDS.get(slug) or [] if dd == d), None)
    mk = B.mark_map(pred) if pred and pred.get("confidence") != "見送り" else {}
    num = w["numbered"]
    hs = sorted(w["horses"], key=lambda h: h.get("number") or 99) if num else list(w["horses"])
    rows = ""
    for h in hs:
        n, fr = h.get("number"), h.get("frame")
        rows += ("<tr>" + (f"<td class='nw'><b class='fr f{esc(fr or '')}'>{esc(fr or '')}</b></td><td class='nw'>{esc(n)}</td>" if num else "")
                 + (f"<td class='nw'><b>{esc(mk.get(n, ''))}</b></td>" if mk else "")
                 + f"<td class='nm'>{B.link_horse(h['name'])}</td><td class='nw'>{esc(h.get('sex_age') or '')}</td>"
                 f"<td class='nw'>{esc(_kg(h.get('weight')))}</td><td>{esc(h.get('jockey') or '')}</td><td>{esc(h.get('trainer') or '')}</td></tr>")
    th = ("<th>枠</th><th>馬番</th>" if num else "") + ("<th>AIの印</th>" if mk else "") + "<th>馬名</th><th>性齢</th><th>斤量</th><th>騎手</th><th>調教師</th>"
    pt = w.get("post_time") or ""
    when = f"{day_jp(d)}{f'{pt}発走' if pt else ''}"
    if num and mk:
        head = f"{name}{d[:4]}の枠順とAIの印"
        intro = (f"{esc(when)}の{esc(name)}の枠順（JRA発表）と、このサイトのAIの印（当日のオッズで変わることがある）。"
                 f"<a href='{B.race_path(d, pred)}'>全頭の評価点・短評と買い目を見る</a>")
    elif num:
        head = f"{name}{d[:4]}の枠順（{len(hs)}頭）"
        intro = f"{esc(when)}の{esc(name)}の枠順が確定した（JRA発表）。このサイトのAI予想は{esc(publish_when(d))}。"
    else:
        head = f"{name}{d[:4]}の出走馬（{len(hs)}頭）"
        intro = (f"{esc(day_jp(d))}の{esc(name)}に出走する{len(hs)}頭が決まった（JRA発表）。馬番と枠番は、{esc(_waku_when(slug, d) + 'の') if _waku_when(slug, d) else ''}枠順の確定で決まる。"
                 f"このサイトのAI予想は{esc(publish_when(d))}（枠順の確定後）。")
    at = (w.get("fetched") or "")[:16]
    return (f"<section class='card' id='entries'><h2>{esc(head)}</h2><p>{intro}</p>"
            f"<div class='scroll'><table class='ent nfix'><thead><tr>{th}</tr></thead><tbody>{rows}</tbody></table></div>"
            f"<p class='meta'>出典：JRA「出馬表」{f'（{esc(at)}時点）' if at else ''}。出走取消・競走除外などで変わることがある。</p></section>")


def live_section(slug: str) -> str:
    """重賞ページ・特集まとめに出すJRA発表の馬の表。出ている中でいちばん新しいもの：枠順（出走馬）→ 出走予定馬 → 特別登録馬。"""
    return waku_section(slug) or entries_section(slug) or nominations_section(slug)


def _guide_name(slug: str) -> str:
    return ((_B.load_json(_B.ROOT / "data" / "race_guides" / f"{slug}.json") or {}).get("name") or "") if _B else ""


def _result_of(slug: str, year: str) -> dict | None:
    """その年のレースの結果：このサイトが予想したレースの結果（data/results）を先に、無ければJRA重賞の成績（data/graded_hist）。"""
    B = _B
    for d, p, name, g in reversed(PREDS.get(slug) or []):
        if d[:4] != year:
            continue
        rows = sorted((x for x in (p.get("_result") or {}).get("rows") or [] if str(x.get("finish") or "").isdigit()),
                      key=lambda x: int(x["finish"]))
        if len(rows) < 3:
            continue
        hs = {h.get("number"): h for h in p["_race"].get("horses") or []}
        r = p["_race"]
        sch = _sched_of(slug, d)
        return {"date": d, "name": sch.get("name") or _guide_name(slug) or name, "p": p,
                "venue": sch.get("venue") or r.get("venue") or B.venue_of(p),
                "course": sch.get("course") or f"{ {'ダ': 'ダート', '障': '障害'}.get(r.get('surface'), r.get('surface') or '') }{r.get('distance') or ''}m".replace(" ", ""),
                "rows": [{"fin": int(x["finish"]), "num": x.get("number"), "frame": (hs.get(x.get("number")) or {}).get("frame"),
                          "name": x.get("name") or (hs.get(x.get("number")) or {}).get("name") or "", "pop": x.get("popularity"),
                          "jockey": (hs.get(x.get("number")) or {}).get("jockey") or ""} for x in rows],
                "pay": {k: [(v.get("combo"), v.get("yen"), v.get("pop")) for v in vs or []] for k, vs in ((p.get("_result") or {}).get("payouts") or {}).items()}}
    r = (_K.get(slug) or {}).get(int(year)) if year.isdigit() else None
    rows = sorted((x for x in (r or {}).get("rows") or [] if isinstance(x.get("fin"), int)), key=lambda x: x["fin"])
    if len(rows) < 3:
        return None
    return {"date": r["date"], "name": _guide_name(slug) or r.get("name") or r.get("abbr") or "", "p": None, "venue": r.get("venue") or "",
            "course": (r.get("course") or "").replace(" ", "").replace(",", "").replace("メートル", "m"),
            "rows": [{"fin": x["fin"], "num": x.get("num"), "frame": x.get("frame"), "name": x.get("name") or "", "pop": x.get("pop"),
                      "jockey": x.get("jockey") or ""} for x in rows],
            "pay": {k: [tuple(v) for v in vs or []] for k, vs in (r.get("pay") or {}).items()}}


def _yen(pay: dict, k: str, pop: bool = False) -> str:
    v = [x for x in pay.get(k) or [] if x and x[1]]
    return "・".join(f"{int(x[1]):,}円" + (f"（{x[2]}番人気）" if pop and len(x) > 2 and x[2] else "") for x in v)


def _hon_line(res: dict) -> str:
    """結果の箱・説明文に使う「AIの◎は〇〇で3着」の文（予想していない・見送りのときは空）。"""
    p = res.get("p")
    if not p or p.get("confidence") == "見送り" or (p.get("marks") or {}).get("◎") is None:
        return ""
    hon = p["marks"]["◎"]
    me = next((x for x in res["rows"] if x.get("num") == hon), None)
    return f"AIの◎{_B.horse_name(p, hon)}は" + (f"{me['fin']}着" if me else "着順なし（取消・除外・中止など）")


def result_box(slug: str, year: str) -> str:
    """終わったG1の特集まとめの冒頭に出す結果の箱：上位5頭（人気・騎手）、主な払戻、AIの◎の着順と予想ページへのリンク。"""
    res = _result_of(slug, year)
    if not res or _B is None:
        return ""
    B, esc = _B, _B.esc
    d, rows = res["date"], res["rows"]
    who = lambda x: x["name"] + (f"（{x['pop']}番人気）" if x.get("pop") else "")
    trs = "".join(
        f"<tr><td class='nw'>{x['fin']}着</td><td class='nw'>"
        + (f"<b class='fr f{esc(x['frame'])}'>{esc(x['num'])}</b>" if x.get("frame") else esc(x.get("num") or ""))
        + f"</td><td class='nm'>{B.link_horse(x['name'])}</td><td class='nw'>{esc(str(x['pop']) + '番人気') if x.get('pop') else '-'}</td>"
        f"<td>{esc(x.get('jockey') or '')}</td></tr>" for x in rows[:5])
    pays = "、".join(f"{k} {_yen(res['pay'], k, pop=k == '3連単')}" for k in ("単勝", "馬連", "3連複", "3連単") if _yen(res["pay"], k))
    ai = ""
    p = res.get("p")
    hl = _hon_line(res)
    if hl:
        sc = B.scored(p)
        bet = ("買い目は的中（払戻" + f"{sc['return']:,}" + "円）。") if sc and sc.get("return") else ("買い目は不的中。" if sc else "")
        ai = f"<p>このサイトの{esc(hl)}。{esc(bet)}<a href='{B.race_path(d, p)}'>AI予想の答え合わせ（全頭の評価点と着順）を見る</a></p>"
    return (f"<section class='card' id='result'><h2>{esc(res['name'])}{year}の結果</h2>"
            f"<p>{esc(day_jp(d))}に{esc(res['venue'])}競馬場の{esc(res['course'])}で行われ、{esc(who(rows[0]))}が勝った。"
            f"2着は{esc(who(rows[1]))}、3着は{esc(who(rows[2]))}。</p>"
            "<div class='scroll'><table class='ent nfix'><thead><tr><th>着順</th><th>馬番</th><th>馬名</th><th>人気</th><th>騎手</th></tr></thead>"
            f"<tbody>{trs}</tbody></table></div>" + (f"<p>払戻（100円あたり）：{esc(pays)}。</p>" if pays else "") + ai
            + "<p class='meta'>出典：JRAのレース結果。</p></section>")


def _pred_since(p: dict, d: str) -> str:
    """予想を最初に公開した日（updates の最初の時刻「11/20 11:30」）。分からなければ今日。"""
    m = re.match(r"(\d{1,2})/(\d{1,2})", ((p.get("updates") or [{}])[0] or {}).get("at") or "")
    if not m:
        return _iso(TODAY)
    y = int(d[:4]) - (1 if int(m.group(1)) > int(d[4:6]) else 0)
    return min(f"{y}-{int(m.group(1)):02d}-{int(m.group(2)):02d}", _iso(TODAY))


def hub_phase(slug: str, year: str) -> dict | None:
    """特集まとめ（〇〇2026-guide）の題名・説明文を、レースの進み具合で変える（検索で使われる言葉が「出走予定馬」→「枠順」→「予想」→「結果」と移るため）。
    出走予定馬（月曜のプレレーティング）→ 出走馬（木曜の夕方）→ 枠順（金曜の朝）→ AI予想（金曜の昼）→ 結果。
    どれでもないとき（登録の前）は None（記事に書いた題名のまま）。{phase, title, desc, since(YYYY-MM-DD)}"""
    if _B is None:
        return None
    B = _B
    tail = "過去10年の傾向もまとめた特集のトップページ。"
    res = _result_of(slug, year)
    if res:
        t = res["rows"]
        who = lambda x: x["name"] + (f"（{x['pop']}番人気）" if x.get("pop") else "")
        tan, t3 = _yen(res["pay"], "単勝"), _yen(res["pay"], "3連単")
        hl = _hon_line(res)
        desc = (f"{res['name']}{year}は{who(t[0])}が勝った。2着{who(t[1])}、3着{who(t[2])}。"
                + (f"単勝{tan}" + (f"、3連単{t3}" if t3 else "") + "。" if tan else "") + (f"{hl}。" if hl else "")
                + f"{day_jp(res['date'])}の{res['venue']}{res['course']}の結果と払戻、AI予想の答え合わせ、" + tail)
        return {"phase": "result", "title": f"{res['name']}{year}の結果と払戻・AI予想の答え合わせ【特集まとめ】", "desc": desc,
                "since": _iso(res["date"])}
    sch = next((r for r in sorted(SCHED_BY_SLUG.get(slug) or [], key=lambda r: r["date"]) if r["date"][:4] == year and r["date"] >= TODAY), None)
    if not sch:
        return None
    d, name = sch["date"], sch["name"]
    where = f"{sch.get('venue', '')}{sch.get('course', '')}"
    pred = next((p for dd, p, *_ in PREDS.get(slug) or [] if dd == d), None)
    if pred:
        pt = pred["_race"].get("post_time") or ""
        head = f"{name}{year}のAI予想"
        when = f"{day_jp(d)}{pt + '発走' if pt else ''}、{where}の"
        mk = pred.get("marks") or {}
        hon = mk.get("◎")
        if pred.get("confidence") == "見送り" or hon is None:
            desc = head + "は見送り（データ不足などで買い目なし）。" + when + "枠順と全頭の評価点、" + tail
        else:
            h = next((x for x in pred["_race"].get("horses") or [] if x.get("number") == hon), {})
            sub = "・".join(f"{m}{B.horse_name(pred, mk[m])}" for m in ("〇", "▲") if mk.get(m) is not None and B.horse_name(pred, mk[m]))
            desc = (head + "は◎" + (f"{h['frame']}枠" if h.get("frame") else "") + f"{hon}番{B.horse_name(pred, hon)}"
                    + (f"、相手は{sub}" if sub else "") + "。" + when + "枠順と全頭の評価点・印、" + tail)
        return {"phase": "pred", "title": f"【AI予想】{name}{year}の枠順と全頭診断・過去10年の傾向【特集まとめ】", "desc": desc,
                "since": _pred_since(pred, d)}
    x = _pre(slug)
    if x and x["date"] == d:
        return {"phase": x["phase"], "title": x["head"] + ("・日程" if x["phase"] == "entries" else "") + "と過去10年の傾向【特集まとめ】",
                "desc": x["desc"] + tail, "since": x["since"]}
    return None


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
            btns = ""
            if slug in ENTRIES and ENTRIES[slug]["date"] == d:
                btns = _a(f"/graded/{slug}/#entries", f"{name}の出走予定馬{len(ENTRIES[slug]['horses'])}頭", "JRA発表の登録馬。直近の出走・今年の重賞成績つき", where, "entries", True)
            btns += _weekend_btn(where, main=not btns)
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
    if slug in ENTRIES and ENTRIES[slug]["date"] == d:
        e = ENTRIES[slug]
        return (f"<p class='notice nmini'><b>{esc(name)}の出走予定馬{len(e['horses'])}頭</b>（JRA発表）："
                f"<a href='/graded/{slug}/#entries' data-ns='{esc(where)}-top' data-ns-to='entries'>直近の出走・今年の成績つきの一覧を見る</a>"
                f"　AI予想は{esc(publish_when(d))}</p>")
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
            status = (f"<p class='wk-st done'>確定：AIの◎{esc(hon)} {B.link_horse(B.horse_name(p, hon))}は{esc(fin)}着（{res}・このレースの回収率{B.roi_txt(sc['stake'], sc['return'])}）"
                      f"　<a href='{path}' data-ns='weekend' data-ns-to='race'>結果と回顧</a></p>")
        elif p.get("confidence") == "見送り":
            status = f"<p class='wk-st'>AIは見送り（自信度が低い）。<a href='{path}' data-ns='weekend' data-ns-to='race'>全頭の評価を見る</a></p>"
        else:
            status = (f"<p class='wk-st on'>AI予想を公開中：◎{esc(hon)} {B.link_horse(B.horse_name(p, hon))}（自信度{esc(p.get('confidence') or '-')}）</p>"
                      f"<div class='nbtns'>{_a(path, '全頭の評価と買い目', '評価点・印・想定勝率', 'weekend', 'race', True)}"
                      + (_a(path + '#vs', 'AIと単勝勝負', '◎を1頭選ぶだけ', 'weekend', 'vs') if _vs_ok() and B.before_post(d, p) else "") + "</div>")
    else:
        status = f"<p class='wk-st'>AI予想は{esc(publish_when(d))}（枠順の確定後）</p>"
    links = []
    if slug in ENTRIES and ENTRIES[slug]["date"] == d:
        links.append(f"<a href='/graded/{slug}/#entries'><b>出走予定馬{len(ENTRIES[slug]['horses'])}頭</b></a>")
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
                     f"<td>◎{esc(hon)} {B.link_horse(B.horse_name(p, hon))}</td><td>{esc(sc.get('honmei_finish') or '-')}着</td>"
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
.bm{border-left:4px solid var(--acc)}
.ent td,.ent th{vertical-align:top}.ent td.nm{white-space:nowrap}.ent small{color:var(--mut);font-size:12px}.bm details{margin:6px 0}.bm summary{cursor:pointer;color:var(--acc)}
/* 枠順・結果の表：1列目が枠・着順なので、馬名用の1列目の幅と固定をやめる */
.scroll table.ent.nfix td:first-child,.scroll table.ent.nfix th:first-child{min-width:0;position:static;box-shadow:none}
"""

JS = r"""
document.addEventListener('click',function(e){var a=e.target&&e.target.closest?e.target.closest('a[data-ns]'):null;
 if(a&&window.gtag){try{gtag('event','next_step',{from:a.dataset.ns,to:a.dataset.nsTo||''});}catch(x){}}});
"""
