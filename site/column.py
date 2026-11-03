"""コラム：columns/*.md を /column/<slug>/ に書き出す。

記事ファイルの形式
---
title: 記事タイトル
description: 検索結果に出る説明（1〜2文）
lead: 冒頭の答え（AIや検索で引用されやすい1〜2文の結論）
date: 2026-10-30
draft: true            # true の間は一覧・サイトマップに出さず noindex（URLを知っていれば見られる）
order: 1
---
本文（Markdownの一部：## 見出し、段落、- 箇条書き、1. 番号、**太字**、[リンク](/path/)、| 表 |、> 補足）

{{変数}} はサイトの記録から作った数字に置き換わる（ビルドのたびに最新になる）。
{{table_bets}} {{table_popularity}} {{table_bias}} は表に置き換わる。
<!-- … --> は公開されない（体験談の書き込み欄など）。
"""
from __future__ import annotations

import csv
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLDIR = ROOT / "columns"
BET_KEYS = {"単勝": "tan", "複勝": "fuku", "枠連": "wakuren", "馬連": "umaren", "ワイド": "wide",
            "馬単": "umatan", "3連複": "sanrenpuku", "3連単": "sanrentan"}


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def pct(a, b, digits=1) -> str:
    return f"{100 * a / b:.{digits}f}%" if b else "―"


# ---------------- 記録から数字を作る ----------------
def stats(stats_from: str) -> tuple[dict, dict]:
    v: dict[str, str] = {}
    tables: dict[str, str] = {}
    dates = sorted(p.name for p in (ROOT / "predictions").glob("*") if p.is_dir() and p.name >= stats_from)
    # 券種別（このサイトの買い目）
    bt = defaultdict(lambda: [0, 0, 0])  # 点数, 払戻, 的中点数
    n_races = stake = ret = 0
    last = None
    for d in dates:
        sc = load(ROOT / "data" / "results" / d / "score.json") or {}
        by = {r.get("race_id"): r for r in sc.get("races", [])}
        for pf in (ROOT / "predictions" / d).glob("*.json"):
            p = load(pf) or {}
            s = by.get(p.get("race_id"))
            if not s or "stake" not in s or s.get("voided") or not s["stake"]:
                continue
            last = d
            n_races += 1
            stake += s["stake"]
            ret += s["return"]
            hit = {}
            for h in s.get("hits", []):
                parts = h.split()
                if len(parts) >= 3 and "返還" not in h:
                    hit[" ".join(parts[:2])] = int(parts[2].rstrip("円"))
            for b in p.get("bets", []):
                k = f"{b['type']} {b['combo']}"
                bt[b["type"]][0] += 1
                bt[b["type"]][1] += hit.get(k, 0)
                bt[b["type"]][2] += k in hit
    v.update(races=f"{n_races:,}", roi=pct(ret, stake), stake=f"{stake:,}円", ret=f"{ret:,}円",
             asof=f"{int(last[4:6])}月{int(last[6:8])}日" if last else "―",
             since=f"{int(stats_from[4:6])}月{int(stats_from[6:8])}日")
    total_pts = sum(x[0] for x in bt.values())
    v["bet_points"] = f"{total_pts:,}"
    rows = []
    for t, key in BET_KEYS.items():
        pts, r, h = bt.get(t, [0, 0, 0])
        v[f"bet_{key}_points"] = f"{pts:,}"
        v[f"bet_{key}_hit"] = pct(h, pts)
        v[f"bet_{key}_roi"] = pct(r, pts * 100)
        if pts:
            rows.append(f"<tr><td>{t}</td><td>{pts:,}点</td><td>{h:,}点</td><td>{pct(h, pts)}</td><td>{pct(r, pts * 100)}</td></tr>")
    tables["table_bets"] = ("<div class='scroll'><table><thead><tr><th>券種</th><th>買った点数</th><th>的中</th><th>的中率</th><th>回収率</th></tr></thead>"
                            f"<tbody>{''.join(rows)}</tbody></table></div>"
                            f"<p class='meta'>このサイトのAI予想の買い目（{v['since']}〜{v['asof']}、各点100円）。点数が少ない券種は偶然の影響が大きい。</p>")
    # 人気別（全レースの確定結果。単勝回収率は「その人気の馬の単勝を毎レース100円」）
    pop = defaultdict(lambda: [0, 0, 0, 0])  # レース, 1着, 3着内, 単勝払戻
    n_pop_races = 0
    for d in dates:
        for f in (ROOT / "data" / "results" / d).glob("*.json"):
            if f.name == "score.json":
                continue
            r = load(f) or {}
            rows_ = r.get("rows") or []
            if not rows_ or not any(x.get("popularity") for x in rows_) or not r.get("payouts"):
                continue
            n_pop_races += 1
            win = {str(p["combo"]): p["yen"] for p in r["payouts"].get("単勝", [])}
            for x in rows_:
                try:
                    k = int(x.get("popularity"))
                except (TypeError, ValueError):
                    continue
                if k > 5:
                    continue
                fin = str(x.get("finish"))
                pop[k][0] += 1
                pop[k][1] += fin == "1"
                pop[k][2] += fin in ("1", "2", "3")
                pop[k][3] += win.get(str(x.get("number")), 0) if fin == "1" else 0
    v["pop_races"] = f"{n_pop_races:,}"
    rows = []
    for k in range(1, 6):
        n, w, t3, y = pop.get(k, [0, 0, 0, 0])
        v[f"pop{k}_n"], v[f"pop{k}_win"], v[f"pop{k}_top3"], v[f"pop{k}_roi"] = f"{n:,}", pct(w, n), pct(t3, n), pct(y, n * 100)
        v[f"pop{k}_wins"] = f"{w:,}"
        if n:
            rows.append(f"<tr><td>{k}番人気</td><td>{n:,}</td><td>{pct(w, n)}</td><td>{pct(t3, n)}</td><td>{pct(y, n * 100)}</td></tr>")
    tables["table_popularity"] = ("<div class='scroll'><table><thead><tr><th>人気</th><th>頭数</th><th>勝率</th><th>3着内率</th><th>単勝回収率</th></tr></thead>"
                                  f"<tbody>{''.join(rows)}</tbody></table></div>"
                                  f"<p class='meta'>{v['since']}〜{v['asof']}の確定結果{v['pop_races']}レース（人気の記録があるレース）。単勝回収率は、その人気の馬の単勝を毎レース100円ずつ買った場合。</p>")
    # バイアス判定
    bc = Counter()
    for f in (ROOT / "data" / "bias").glob("*.json"):
        if f.name[:8] < stats_from:
            continue
        for b in (load(f) or {}).get("bias", {}).values():
            bc[b["judgement"]] += 1
    nb = sum(bc.values())
    v["bias_n"] = f"{nb:,}"
    front = sum(c for j, c in bc.items() if "先行" in j)
    closer = sum(c for j, c in bc.items() if "差し" in j)
    v["bias_front"], v["bias_front_pct"] = f"{front:,}", pct(front, nb, 0)
    v["bias_closer"], v["bias_flat"] = f"{closer:,}", f"{bc.get('フラット', 0):,}"
    rows = "".join(f"<tr><td>{esc(j)}</td><td>{c}</td><td>{pct(c, nb, 0)}</td></tr>" for j, c in bc.most_common())
    tables["table_bias"] = ("<div class='scroll'><table><thead><tr><th>判定</th><th>件数</th><th>割合</th></tr></thead>"
                            f"<tbody>{rows}</tbody></table></div>"
                            f"<p class='meta'>{v['since']}〜{v['asof']}、場×芝ダートごとの当日判定{nb}件（判定の方法は本文）。</p>")
    # 全レースの確定結果から：単勝オッズ帯別・4角位置別・枠別・頭数別（1番人気）・馬体重増減別・間隔別
    def band_odds(o):
        return "1.9倍以下" if o < 2 else "2.0〜3.9倍" if o < 4 else "4.0〜9.9倍" if o < 10 else "10〜19.9倍" if o < 20 else "20〜49.9倍" if o < 50 else "50倍以上"
    ob = defaultdict(lambda: [0, 0, 0, 0]); p4 = defaultdict(lambda: [0, 0, 0]); fr = defaultdict(lambda: [0, 0, 0])
    fs = defaultdict(lambda: [0, 0, 0]); bw = defaultdict(lambda: [0, 0, 0]); gap = defaultdict(lambda: [0, 0, 0])
    n_all = 0
    from datetime import date as _date
    for d in dates:
        key2race = {}
        for pf in (ROOT / "predictions" / d).glob("*.json"):
            pp = load(pf) or {}
            if pp.get("race_id"):
                key2race[pp.get("results_key") or pp["race_id"]] = pp["race_id"]
        for f in (ROOT / "data" / "results" / d).glob("*.json"):
            if f.name == "score.json":
                continue
            r = load(f) or {}
            rows_ = r.get("rows") or []
            if not rows_ or not r.get("payouts"):
                continue
            race = load(ROOT / "data" / "races" / d / f"{key2race.get(f.stem, f.stem)}.json") or {}
            hs = {h.get("number"): h for h in race.get("horses", []) or []}
            if not hs:
                continue
            n_all += 1
            win = {str(p["combo"]): p["yen"] for p in r["payouts"].get("単勝", [])}
            nf = len(rows_)
            # 人気はオッズの順位から（JRAの出馬表は人気が無い）
            ranked = sorted((hh for hh in hs.values() if hh.get("odds") and float(hh["odds"]) > 0), key=lambda hh: float(hh["odds"]))
            fav_no = ranked[0].get("number") if ranked else None
            fb = "8頭以下" if nf <= 8 else "9〜12頭" if nf <= 12 else "13〜15頭" if nf <= 15 else "16頭以上"
            for x in rows_:
                fin = str(x.get("finish")); w = fin == "1"; t = fin in ("1", "2", "3")
                h = hs.get(x.get("number"), {})
                if x.get("number") == fav_no or (fav_no is None and (x.get("popularity") == 1 or h.get("popularity") == 1)):
                    fs[fb][0] += 1; fs[fb][1] += w; fs[fb][2] += t
                try:
                    o = float(h.get("odds"))
                    if o <= 0:
                        raise ValueError
                    b = band_odds(o)
                    ob[b][0] += 1; ob[b][1] += w; ob[b][2] += t; ob[b][3] += win.get(str(x.get("number")), 0) if w else 0
                except (TypeError, ValueError):
                    pass
                q = x.get("pos4")
                if q:
                    pb = "先頭（4角1番手）" if q == 1 else "2〜3番手" if q <= 3 else "4〜6番手" if q <= 6 else "7番手以降"
                    p4[pb][0] += 1; p4[pb][1] += w; p4[pb][2] += t
                fr_ = x.get("frame") or h.get("frame")
                if fr_ and nf >= 10:
                    frb = "1〜2枠" if fr_ <= 2 else "3〜4枠" if fr_ <= 4 else "5〜6枠" if fr_ <= 6 else "7〜8枠"
                    fr[frb][0] += 1; fr[frb][1] += w; fr[frb][2] += t
                m = re.fullmatch(r"\(?([+-]?\d+)\)?", str(h.get("body_weight_change") or "").replace(" ", ""))
                if m:
                    c = int(m.group(1))
                    cb = "−10kg以下" if c <= -10 else "−9〜−4kg" if c <= -4 else "−3〜+3kg" if c <= 3 else "+4〜+9kg" if c <= 9 else "+10kg以上"
                    bw[cb][0] += 1; bw[cb][1] += w; bw[cb][2] += t
                past = h.get("past") or []
                if past and past[0].get("date"):
                    try:
                        pd = str(past[0]["date"]).replace("/", "-")
                        y, mo, da = [int(z) for z in re.findall(r"\d+", pd)[:3]]
                        wk = (_date(int(d[:4]), int(d[4:6]), int(d[6:8])) - _date(y, mo, da)).days // 7
                        gb = "連闘〜2週" if wk <= 2 else "3〜4週" if wk <= 4 else "5〜8週" if wk <= 8 else "9〜16週" if wk <= 16 else "17週以上（4ヶ月超）"
                        gap[gb][0] += 1; gap[gb][1] += w; gap[gb][2] += t
                    except Exception:  # noqa: BLE001
                        pass
    v["all_races"] = f"{n_all:,}"

    def tbl(dic, order, label, note, roi=False):
        rows = []
        for k in order:
            x = dic.get(k)
            if not x or not x[0]:
                continue
            rows.append(f"<tr><td>{k}</td><td>{x[0]:,}</td><td>{pct(x[1], x[0])}</td><td>{pct(x[2], x[0])}</td>" + (f"<td>{pct(x[3], x[0] * 100)}</td>" if roi else "") + "</tr>")
        return (f"<div class='scroll'><table><thead><tr><th>{label}</th><th>頭数</th><th>勝率</th><th>3着内率</th>{'<th>単勝回収率</th>' if roi else ''}</tr></thead>"
                f"<tbody>{''.join(rows)}</tbody></table></div><p class='meta'>{v['since']}〜{v['asof']}の確定結果{n_all:,}レース。{note}</p>")
    tables["table_odds_band"] = tbl(ob, ["1.9倍以下", "2.0〜3.9倍", "4.0〜9.9倍", "10〜19.9倍", "20〜49.9倍", "50倍以上"], "単勝オッズ（予想時点）", "単勝回収率は、その帯の馬の単勝を毎回100円買った場合。オッズは予想時点のもので最終オッズとは異なる。", roi=True)
    tables["table_pos4"] = tbl(p4, ["先頭（4角1番手）", "2〜3番手", "4〜6番手", "7番手以降"], "4コーナーの位置", "通過順の記録があるレースのみ（ばんえいを除く）。")
    tables["table_frame"] = tbl(fr, ["1〜2枠", "3〜4枠", "5〜6枠", "7〜8枠"], "枠", "10頭以上のレースのみ。外枠ほど頭数が多いため、頭数の列も見ること。")
    tables["table_field_fav"] = tbl(fs, ["8頭以下", "9〜12頭", "13〜15頭", "16頭以上"], "頭数（1番人気の成績）", "各レースの1番人気の馬だけを集計。")
    tables["table_bodyweight"] = tbl(bw, ["−10kg以下", "−9〜−4kg", "−3〜+3kg", "+4〜+9kg", "+10kg以上"], "馬体重の増減", "前走からの増減が記録されている馬のみ（中央が中心）。")
    tables["table_gap"] = tbl(gap, ["連闘〜2週", "3〜4週", "5〜8週", "9〜16週", "17週以上（4ヶ月超）"], "前走からの間隔", "前走の日付が記録されている馬のみ。")
    for dic, name, order in ((ob, "odds", ["1.9倍以下", "2.0〜3.9倍", "4.0〜9.9倍", "10〜19.9倍", "20〜49.9倍", "50倍以上"]), (p4, "pos4", ["先頭（4角1番手）", "2〜3番手", "4〜6番手", "7番手以降"]),
                            (fr, "frame", ["1〜2枠", "3〜4枠", "5〜6枠", "7〜8枠"]), (fs, "fieldfav", ["8頭以下", "9〜12頭", "13〜15頭", "16頭以上"]),
                            (bw, "bw", ["−10kg以下", "−9〜−4kg", "−3〜+3kg", "+4〜+9kg", "+10kg以上"]), (gap, "gap", ["連闘〜2週", "3〜4週", "5〜8週", "9〜16週", "17週以上（4ヶ月超）"])):
        for i, k in enumerate(order, start=1):
            x = dic.get(k, [0, 0, 0, 0])
            v[f"{name}{i}_n"], v[f"{name}{i}_win"], v[f"{name}{i}_top3"] = f"{x[0]:,}", pct(x[1], x[0]), pct(x[2], x[0])
            if len(x) > 3:
                v[f"{name}{i}_roi"] = pct(x[3], x[0] * 100)
    # 買い方別（strategy.py と同じ集計）：{{st:グループ:区分:roi}} / :n / :hit / :diff で本文から参照できる
    try:
        import build as _b
        import strategy as _s
        by_date = {d: _b.predictions(d) for d in dates}
        g = _s.collect(by_date, stats_from)
        for grp, bs in g.items():
            rows = []
            for k in _s._order(grp, list(bs)):
                b = bs[k]
                v[f"st:{grp}:{k}:roi"] = pct(b.ret, b.stake)
                v[f"st:{grp}:{k}:n"] = f"{b.n:,}"
                v[f"st:{grp}:{k}:hit"] = pct(b.hit, b.n)
                v[f"st:{grp}:{k}:diff"] = f"{b.ret - b.stake:+,}円"
                rows.append(f"<tr><td>{esc(k)}</td><td>{b.n:,}</td><td>{pct(b.hit, b.n)}</td><td>{pct(b.ret, b.stake)}</td><td>{b.ret - b.stake:+,}円</td></tr>")
            tables[f"table_st_{grp}"] = ("<div class='scroll'><table><thead><tr><th>買い方・区分</th><th>レース</th><th>的中率</th><th>回収率</th><th>収支</th></tr></thead>"
                                        f"<tbody>{''.join(rows)}</tbody></table></div><p class='meta'>{v['since']}〜{v['asof']}。買い目を1点100円ずつ買った計算で、「見送り」のレースは除く。</p>")
        # 較正：◎の想定勝率の帯ごとに、実際に◎が勝った割合・3着内の割合
        cal = defaultdict(lambda: [0, 0, 0])
        conf_c = defaultdict(lambda: [0, 0, 0])
        for d, ps in by_date.items():
            for p in ps:
                sc = p.get("_score")
                if not sc or "stake" not in sc or sc.get("voided") or not sc["stake"]:
                    continue
                hon = p.get("marks", {}).get("◎")
                wp = next((h.get("win_pct") for h in p.get("horses", []) if h.get("number") == hon), None)
                fin = str(sc.get("honmei_finish"))
                c = p.get("confidence") or "-"
                conf_c[c][0] += 1; conf_c[c][1] += fin == "1"; conf_c[c][2] += fin in ("1", "2", "3")
                try:
                    wp = float(wp)
                except (TypeError, ValueError):
                    continue
                band = "40%以上" if wp >= 40 else "30〜39%" if wp >= 30 else "20〜29%" if wp >= 20 else "20%未満"
                cal[band][0] += 1; cal[band][1] += fin == "1"; cal[band][2] += fin in ("1", "2", "3")
        rows = []
        for band in ("40%以上", "30〜39%", "20〜29%", "20%未満"):
            n, w, t = cal.get(band, [0, 0, 0])
            key = band.replace("%", "").replace("〜", "_").replace("以上", "up").replace("未満", "dn")
            v[f"cal_{key}_n"], v[f"cal_{key}_win"], v[f"cal_{key}_top3"] = f"{n:,}", pct(w, n), pct(t, n)
            if n:
                rows.append(f"<tr><td>{band}</td><td>{n:,}</td><td>{pct(w, n)}</td><td>{pct(t, n)}</td></tr>")
        tables["table_calibration"] = ("<div class='scroll'><table><thead><tr><th>AIの想定勝率（◎）</th><th>レース</th><th>実際の◎勝率</th><th>◎3着内率</th></tr></thead>"
                                       f"<tbody>{''.join(rows)}</tbody></table></div><p class='meta'>{v['since']}〜{v['asof']}。想定勝率はAIが予想時に付けた数字、実際の勝率は確定結果。</p>")
        rows = []
        for c in ("A", "B", "C"):
            n, w, t = conf_c.get(c, [0, 0, 0])
            v[f"conf_{c}_n"], v[f"conf_{c}_win"], v[f"conf_{c}_top3"] = f"{n:,}", pct(w, n), pct(t, n)
            if n:
                rows.append(f"<tr><td>自信度{c}</td><td>{n:,}</td><td>{pct(w, n)}</td><td>{pct(t, n)}</td><td>{v.get(f'st:conf:自信度{c}のレースだけ:hit', '―')}</td><td>{v.get(f'st:conf:自信度{c}のレースだけ:roi', '―')}</td></tr>")
        tables["table_confidence"] = ("<div class='scroll'><table><thead><tr><th>自信度</th><th>レース</th><th>◎勝率</th><th>◎3着内率</th><th>的中率</th><th>回収率</th></tr></thead>"
                                      f"<tbody>{''.join(rows)}</tbody></table></div><p class='meta'>{v['since']}〜{v['asof']}、見送りは除く。</p>")
    except Exception as e:  # noqa: BLE001
        print("column stats (strategy) error:", e)
    return v, tables


# ---------------- Markdown（必要な分だけ） ----------------
def inline(s: str) -> str:
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"<a href='\2'>\1</a>", s)
    return s


def render(text: str, tables: dict) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    out, para, lst, ltype, tbl = [], [], [], None, []

    def flush():
        nonlocal para, lst, ltype, tbl
        if para:
            out.append("<p>" + "<br>".join(inline(x) for x in para) + "</p>")
        if lst:
            out.append(f"<{ltype}>" + "".join(f"<li>{inline(x)}</li>" for x in lst) + f"</{ltype}>")
        if tbl:
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in tbl if not re.fullmatch(r"\|?[\s:\-|]+\|?", r.strip())]
            head, body = cells[0], cells[1:]
            out.append("<div class='scroll'><table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body) + "</tbody></table></div>")
        para, lst, ltype, tbl = [], [], None, []

    for line in text.splitlines():
        s = line.rstrip()
        m = re.fullmatch(r"\{\{(table_\w+|aff_\w+)\}\}", s.strip())
        if m:
            flush()
            out.append(tables.get(m.group(1), ""))
        elif not s.strip():
            flush()
        elif s.startswith("#"):
            flush()
            lv = len(s) - len(s.lstrip("#"))
            out.append(f"<h{lv}>{inline(s[lv:].strip())}</h{lv}>")
        elif s.startswith("> "):
            flush()
            out.append(f"<p class='note'>{inline(s[2:])}</p>")
        elif s.startswith("|"):
            if para or lst:
                flush()
            tbl.append(s)
        elif re.match(r"^(- |\d+\. )", s):
            t = "ol" if s[0].isdigit() else "ul"
            if para or tbl or (ltype and ltype != t):
                flush()
            ltype = t
            lst.append(re.sub(r"^(- |\d+\. )", "", s))
        else:
            if lst or tbl:
                flush()
            para.append(s.strip())
    flush()
    return "\n".join(out)


def parse(f: Path) -> dict:
    raw = f.read_text(encoding="utf-8")
    meta, body = {}, raw
    m = re.match(r"---\n(.*?)\n---\n(.*)", raw, re.S)
    if m:
        body = m.group(2)
        for line in m.group(1).splitlines():
            if ":" in line:
                k, val = line.split(":", 1)
                meta[k.strip()] = val.split(" #")[0].strip()
    meta.setdefault("slug", f.stem)
    meta["draft"] = meta.get("draft", "false").lower() == "true"
    meta["order"] = int(meta.get("order", 99))
    meta["body"] = body
    return meta


def subst(s: str, v: dict) -> str:
    return re.sub(r"\{\{([^{}\n]+?)\}\}", lambda m: v.get(m.group(1).strip(), m.group(0)), s)


def columns() -> list[dict]:
    return sorted((parse(f) for f in COLDIR.glob("*.md")), key=lambda c: (c["order"], c["slug"]))


def build(write, page, jsonld, base_url: str, site_name: str, stats_from: str, today_iso: str) -> dict[str, str]:
    """コラムを書き出し、サイトマップ用の {path: lastmod} を返す（下書きは含めない）。"""
    cols = columns()
    if not cols:
        return {}
    v, tables = stats(stats_from)
    try:
        tables["aff_rakuten"] = __import__("build").aff_rakuten("column")
        tables["aff_saikyo"] = __import__("build").aff_saikyo()
    except Exception:  # noqa: BLE001
        tables["aff_rakuten"] = tables["aff_saikyo"] = ""
    pub = [c for c in cols if not c["draft"]]
    lastmod = {}
    for c in cols:
        path = f"/column/{c['slug']}/"
        title, lead = subst(c.get("title", ""), v), subst(c.get("lead", ""), v)
        desc = subst(c.get("description", ""), v)
        body_html = render(subst(c["body"], v), tables)
        auto_c = c.get("auto") == "true"
        rel_src = [o for o in pub if o is not c and (o.get("auto") != "true" or (auto_c and o.get("auto") == "true"))]
        if auto_c:
            rel_src = [o for o in pub if o is not c and o.get("auto") == "true"][:5] + [o for o in pub if o.get("auto") != "true"][:6]
        else:
            rel_src = [o for o in pub if o is not c and o.get("auto") != "true"] + [o for o in pub if o.get("auto") == "true"][:3]
        related = "".join(f"<li><a href='/column/{o['slug']}/'>{esc(subst(o.get('title', ''), v))}</a></li>" for o in rel_src)
        ld = {"@context": "https://schema.org", "@type": "Article", "headline": title, "description": desc,
              "datePublished": c.get("date"), "dateModified": today_iso, "inLanguage": "ja",
              "author": {"@type": "Organization", "name": site_name, "url": base_url + "/operator/"},
              "publisher": {"@type": "Organization", "name": site_name}, "mainEntityOfPage": base_url + path}
        crumb = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": site_name, "item": base_url + "/"},
            {"@type": "ListItem", "position": 2, "name": "コラム", "item": base_url + "/column/"},
            {"@type": "ListItem", "position": 3, "name": title, "item": base_url + path}]}
        html_ = (("<p class='draft'>下書き（検索エンジンには出ず、一覧にも載らない）</p>" if c["draft"] else "")
                 + f"<p class='crumb'><a href='/'>トップ</a> › <a href='/column/'>コラム</a></p><article class='col'>"
                 f"<h1>{esc(title)}</h1><p class='meta'>公開 {esc(c.get('date'))}・データは{esc(v['asof'])}までの記録で自動更新</p>"
                 + (f"<p class='answer'>{inline(lead)}</p>" if lead else "") + body_html + "</article>"
                 "<section class='card'><h2>このサイトについて</h2>"
                 + ("<div class='zkfoot'><img class='zk' src='/assets/zk-normal.png' alt='全頭くん' width='64' height='64' loading='lazy'><p>" if (ROOT / "site" / "assets" / "zk-normal.png").exists() else "<p>")
                 + "AIが中央・地方の全レースを毎日予想し、外れも含めた全成績を公開している。案内役は公式キャラの全頭くん。"
                 "<a href='/'>今日の予想</a>・<a href='/results/'>成績</a>・<a href='/about/'>予想の方法</a></p>"
                 + ("</div>" if (ROOT / "site" / "assets" / "zk-normal.png").exists() else "")
                 + "<p class='meta'>馬券の購入は20歳から。予想は的中や利益を保証するものではない。</p></section>"
                 + (f"<section class='card'><h2>ほかのコラム</h2><ul>{related}</ul></section>" if related else ""))
        img = ROOT / "site" / "assets" / f"col-{c['slug']}.jpg"
        og_img = f"/assets/col-{c['slug']}.jpg" if img.exists() else "/og/default.jpg"
        if img.exists():
            html_ = html_.replace("</h1>", "</h1>", 1).replace(
                "<p class='meta'>公開", f"<img class='hero' src='/assets/col-{c['slug']}.jpg' alt='' width='1200' height='800'><p class='meta'>公開", 1)
            ld["image"] = base_url + og_img
        write(path, page(f"{title} | {site_name}", html_, path, desc=desc, noindex=c["draft"],
                         head_extra=jsonld(ld) + jsonld(crumb), og_image=og_img))
        if not c["draft"]:
            lastmod[path] = today_iso
    def _li(c):
        return (f"<li><a href='/column/{c['slug']}/'><b>{esc(subst(c.get('title', ''), v))}</b>"
                f"<span>{esc(subst(c.get('description', ''), v))}</span></a></li>")
    items = "".join(_li(c) for c in pub if c.get("auto") != "true")
    autos = sorted((c for c in pub if c.get("auto") == "true"), key=lambda c: c.get("date", ""), reverse=True)
    auto_items = "".join(_li(c) for c in autos[:40])
    if auto_items:
        auto_items = ("<h2>重賞の全頭診断（レースごと）</h2><p class='meta'>重賞ごとに、AIの印・評価点・想定勝率・買い目と、確定後の結果・回顧を1本の記事にしている。レース当日の昼までに公開。</p>"
                      f"<ul class='cols'>{auto_items}</ul>" + ("<p class='meta'>直近40本を表示。</p>" if len(autos) > 40 else ""))
    write("/column/", page(f"競馬初心者向けコラム | {site_name}",
                           "<p class='crumb'><a href='/'>トップ</a> › コラム</p><h1>競馬初心者向けコラム</h1>" + __import__("build").banner("column") +
                           "<p class='answer'>馬券の種類や回収率の考え方などを、このサイトの全レースの記録（実データ）を使って解説する。数字は記録が増えるたびに自動で更新される。</p>"
                           + (f"<h2>初心者向け・データ分析</h2><ul class='cols'>{items}</ul>" if items else "<p>準備中。</p>") + auto_items,
                           "/column/", desc="競馬初心者向けに、馬券の種類・回収率・人気と勝率・トラックバイアスを、AI予想の全レースの実データで解説するコラム。",
                           noindex=not pub))
    if pub:
        lastmod["/column/"] = today_iso
    return lastmod
