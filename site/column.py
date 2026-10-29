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
        m = re.fullmatch(r"\{\{(table_\w+)\}\}", s.strip())
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
    return re.sub(r"\{\{(\w+)\}\}", lambda m: v.get(m.group(1), m.group(0)), s)


def columns() -> list[dict]:
    return sorted((parse(f) for f in COLDIR.glob("*.md")), key=lambda c: (c["order"], c["slug"]))


def build(write, page, jsonld, base_url: str, site_name: str, stats_from: str, today_iso: str) -> dict[str, str]:
    """コラムを書き出し、サイトマップ用の {path: lastmod} を返す（下書きは含めない）。"""
    cols = columns()
    if not cols:
        return {}
    v, tables = stats(stats_from)
    pub = [c for c in cols if not c["draft"]]
    lastmod = {}
    for c in cols:
        path = f"/column/{c['slug']}/"
        title, lead = subst(c.get("title", ""), v), subst(c.get("lead", ""), v)
        desc = subst(c.get("description", ""), v)
        body_html = render(subst(c["body"], v), tables)
        related = "".join(f"<li><a href='/column/{o['slug']}/'>{esc(subst(o.get('title', ''), v))}</a></li>"
                          for o in pub if o is not c)
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
                 "<section class='card'><h2>このサイトについて</h2><p>AIが中央・地方の全レースを毎日予想し、外れも含めた全成績を公開している。"
                 "<a href='/'>今日の予想</a>・<a href='/results/'>成績</a>・<a href='/about/'>予想の方法</a></p>"
                 "<p class='meta'>馬券の購入は20歳から。予想は的中や利益を保証するものではない。</p></section>"
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
    items = "".join(f"<li><a href='/column/{c['slug']}/'><b>{esc(subst(c.get('title', ''), v))}</b>"
                    f"<span>{esc(subst(c.get('description', ''), v))}</span></a></li>" for c in pub)
    write("/column/", page(f"競馬初心者向けコラム | {site_name}",
                           "<p class='crumb'><a href='/'>トップ</a> › コラム</p><h1>競馬初心者向けコラム</h1>"
                           "<p class='answer'>馬券の種類や回収率の考え方などを、このサイトの全レースの記録（実データ）を使って解説する。数字は記録が増えるたびに自動で更新される。</p>"
                           + (f"<ul class='cols'>{items}</ul>" if items else "<p>準備中。</p>"),
                           "/column/", desc="競馬初心者向けに、馬券の種類・回収率・人気と勝率・トラックバイアスを、AI予想の全レースの実データで解説するコラム。",
                           noindex=not pub))
    if pub:
        lastmod["/column/"] = today_iso
    return lastmod
