"""サイト生成：predictions/・data/races/・data/results/ から静的HTMLを _site/ に書き出す。

使い方: python site/build.py
"""
from __future__ import annotations

import csv
import html
import json
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"
SITE_NAME = "AI競馬 全レース予想と成績"
DOMAIN = "www.ai-keiba-log.com"
BASE_URL = f"https://{DOMAIN}/"
JST = timezone(timedelta(hours=9))
MARKS = ["◎", "〇", "▲", "△", "☆"]


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def page(title: str, body: str, depth: int = 0, desc: str = "", canon: str | None = None) -> str:
    up = "../" * depth
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | {SITE_NAME}</title>
<meta name="description" content="{esc(desc or 'AIが日本の競馬（JRA・地方）の全レースを毎日分析し、外れも含めた全予想の回収率を公開しています。')}">
<link rel="stylesheet" href="{up}style.css">
{"" if canon is None else f'<link rel="canonical" href="{BASE_URL}{canon}">'}
</head><body>
<header class="top"><div class="wrap">
<a class="logo" href="{up}index.html">{SITE_NAME}</a>
<nav><a href="{up}index.html">本日の予想</a><a href="{up}results.html">成績</a><a href="{up}about.html">予想の方法</a></nav>
</div></header>
<main class="wrap">{body}</main>
<footer class="wrap foot">
<p>本サイトの予想は情報提供を目的としたもので、的中や利益を保証するものではありません。馬券の購入はご自身の判断と責任で行ってください。20歳未満の方は馬券を購入できません。</p>
<p>レース情報は主催者の発表が正です。成績は全予想を各点100円の均等買いとして集計しています。</p>
</footer>
<script src="{up}app.js"></script>
</body></html>"""


def fmt_date(d: str) -> str:
    return f"{d[:4]}年{int(d[4:6])}月{int(d[6:8])}日"


def roi_txt(stake, ret) -> str:
    return f"{100 * ret / stake:.1f}%" if stake else "―"


# ---------------- データ読み込み ----------------
def all_dates() -> list[str]:
    ds = {p.name for p in (ROOT / "predictions").glob("*") if p.is_dir()}
    return sorted(ds, reverse=True)


def predictions(date: str) -> list[dict]:
    out = []
    for f in sorted((ROOT / "predictions" / date).glob("*.json")):
        p = load_json(f)
        if not p:
            continue
        race = load_json(ROOT / "data" / "races" / date / f"{p['race_id']}.json") or {}
        p["_race"] = race
        score = load_json(ROOT / "data" / "results" / date / "score.json") or {}
        p["_score"] = next((r for r in score.get("races", []) if r.get("race_id") == p["race_id"]), None)
        out.append(p)
    out.sort(key=lambda p: (p.get("venue") or p["_race"].get("venue") or "", p.get("race_no") or p["_race"].get("race_no") or 0))
    return out


def ledger() -> list[dict]:
    f = ROOT / "results_ledger.csv"
    if not f.exists():
        return []
    with f.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ---------------- ページ ----------------
def race_title(p: dict) -> str:
    r = p["_race"]
    v = p.get("venue") or r.get("venue", "")
    n = p.get("race_no") or r.get("race_no", "")
    name = p.get("race_name") or r.get("race_name") or r.get("title_text") or ""
    return f"{v}{n}R {name}".strip()


def race_page(date: str, p: dict) -> str:
    r = p["_race"]
    horses = {h.get("number"): h for h in r.get("horses", [])}
    marks = p.get("marks", {})
    mark_of = {}
    for m in MARKS:
        v = marks.get(m)
        for n in (v if isinstance(v, list) else [v] if v is not None else []):
            mark_of[n] = m
    evals = {e["number"]: e for e in p.get("horses", [])}
    rows = []
    for num in sorted(set(horses) | set(evals), key=lambda x: (x is None, x)):
        h, e = horses.get(num, {}), evals.get(num, {})
        rows.append(
            f"<tr class='{'mk' if num in mark_of else ''}'><td>{esc(h.get('frame'))}</td><td>{esc(num)}</td>"
            f"<td class='mark'>{esc(mark_of.get(num, ''))}</td><td>{esc(h.get('name') or e.get('name'))}</td>"
            f"<td>{esc(h.get('jockey'))}</td><td>{esc(h.get('odds'))}</td><td>{esc(e.get('score'))}</td>"
            f"<td class='cmt'>{esc(e.get('comment'))}</td></tr>")
    bets = "".join(f"<li>{esc(b['type'])} {esc(b['combo'])}</li>" for b in p.get("bets", []))
    sc = p.get("_score")
    res_html = ""
    if sc and "stake" in sc:
        hit = "的中" if sc["return"] > 0 else "不的中"
        res_html = (f"<section class='card'><h2>結果</h2><p>1〜3着：{esc(' - '.join(str(x) for x in sc.get('top3', [])))}"
                    f"／◎は{esc(sc.get('honmei_finish'))}着</p><p class='big {'' if sc['return'] else 'miss'}'>{hit}"
                    f"　投資{sc['stake']:,}円・払戻{sc['return']:,}円</p>"
                    + "".join(f"<p>{esc(x)}</p>" for x in sc.get("hits", [])) + "</section>")
    updates = "".join(f"<li><b>{esc(u.get('at'))}</b> {esc(u.get('text'))}</li>" for u in p.get("updates", []))
    meta = " ".join(x for x in [fmt_date(date), esc(r.get("post_time") and f"{r['post_time']}発走"),
                                esc(f"{r.get('surface') or ''}{r.get('distance') or ''}m" if r.get("distance") else ""),
                                esc(f"{r.get('field')}頭" if r.get("field") else "")] if x)
    body = f"""
<p class="crumb"><a href="../../index.html?d={date}">{fmt_date(date)}の予想</a></p>
<h1>{esc(race_title(p))}</h1><p class="meta">{meta}</p>
<section class="card"><h2>結論</h2><p class="big">{esc(p.get('summary'))}</p>
<p>自信度 <span class="conf c{esc(p.get('confidence'))}">{esc(p.get('confidence'))}</span></p>
<h3>買い目（各100円・計{len(p.get('bets', []))}点）</h3><ul class="bets">{bets}</ul></section>
{res_html}
<section class="card"><h2>展開予想</h2><p>{esc(p.get('pace'))}</p></section>
<section class="card"><h2>全頭評価</h2><div class="scroll"><table class="horses">
<thead><tr><th>枠</th><th>馬番</th><th>印</th><th>馬名</th><th>騎手</th><th>単勝</th><th>評価点</th><th>短評</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></section>
{f'<section class="card"><h2>更新履歴</h2><ul>{updates}</ul></section>' if updates else ''}
"""
    return page(race_title(p), body, depth=2, desc=f"{race_title(p)}のAI予想（{fmt_date(date)}）。全頭の評価点と買い目、結果。", canon=f"races/{date}/{p['race_id']}.html")


def day_section(date: str, preds: list[dict]) -> str:
    by_venue = defaultdict(list)
    for p in preds:
        by_venue[p.get("venue") or p["_race"].get("venue", "")].append(p)
    st = sum(p["_score"]["stake"] for p in preds if p.get("_score") and "stake" in p["_score"])
    rt = sum(p["_score"]["return"] for p in preds if p.get("_score") and "stake" in p["_score"])
    parts = [f"<section class='day' data-date='{date}'><h2>{fmt_date(date)}</h2>"
             f"<p class='meta'>{len(preds)}レース　当日回収率 {roi_txt(st, rt)}</p>"]
    for v, ps in by_venue.items():
        parts.append(f"<h3>{esc(v)}</h3><ul class='races'>")
        for p in ps:
            sc = p.get("_score")
            badge = ""
            if sc and "stake" in sc:
                badge = f"<span class='hit'>的中 {sc['return']:,}円</span>" if sc["return"] else "<span class='miss'>不的中</span>"
            hon = p.get("marks", {}).get("◎")
            hn = next((h.get("name") for h in p["_race"].get("horses", []) if h.get("number") == hon), "")
            parts.append(
                f"<li data-conf='{esc(p.get('confidence'))}'><a href='races/{date}/{esc(p['race_id'])}.html'>"
                f"<span class='rno'>{esc(p.get('race_no') or p['_race'].get('race_no'))}R</span>"
                f"<span class='rt'>{esc(p['_race'].get('post_time'))}</span>"
                f"<span class='hon'>◎{esc(hon)} {esc(hn)}</span>"
                f"<span class='conf c{esc(p.get('confidence'))}'>{esc(p.get('confidence'))}</span>{badge}</a></li>")
        parts.append("</ul>")
    parts.append("</section>")
    return "".join(parts)


def svg_line(points: list[float], w=640, h=160) -> str:
    if len(points) < 2:
        return ""
    lo, hi = min(points + [100]), max(points + [100])
    pad = (hi - lo) * 0.1 or 10
    lo, hi = lo - pad, hi + pad
    xs = [i * (w - 40) / (len(points) - 1) + 30 for i in range(len(points))]
    ys = [h - 20 - (v - lo) / (hi - lo) * (h - 40) for v in points]
    y100 = h - 20 - (100 - lo) / (hi - lo) * (h - 40)
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(zip(xs, ys)))
    return (f"<svg viewBox='0 0 {w} {h}' class='chart' role='img' aria-label='累計回収率の推移'>"
            f"<line x1='30' x2='{w - 10}' y1='{y100:.1f}' y2='{y100:.1f}' class='base'/>"
            f"<text x='2' y='{y100 + 4:.1f}' class='lbl'>100%</text>"
            f"<path d='{path}' class='ln'/><circle cx='{xs[-1]:.1f}' cy='{ys[-1]:.1f}' r='4' class='pt'/>"
            f"<text x='{xs[-1] - 4:.1f}' y='{ys[-1] - 8:.1f}' class='lbl end'>{points[-1]:.1f}%</text></svg>")


def results_page(rows: list[dict]) -> str:
    by_day = defaultdict(lambda: [0, 0, 0, 0, 0])  # stake, ret, races, hon_win, hon_top3
    for r in rows:
        d = by_day[r["date"]]
        d[0] += int(r["stake"]); d[1] += int(r["return"]); d[2] += 1
        d[3] += r["honmei_finish"] == "1"; d[4] += r["honmei_finish"] in ("1", "2", "3")
    days = sorted(by_day)
    cum, cs, cr = [], 0, 0
    for d in days:
        cs += by_day[d][0]; cr += by_day[d][1]
        cum.append(100 * cr / cs if cs else 100)
    tot = [sum(by_day[d][i] for d in days) for i in range(5)]
    conf = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        c = conf[r["confidence"] or "-"]; c[0] += int(r["stake"]); c[1] += int(r["return"]); c[2] += 1
    tr = "".join(f"<tr><td>{fmt_date(d)}</td><td>{v[2]}</td><td>{v[0]:,}</td><td>{v[1]:,}</td><td>{roi_txt(v[0], v[1])}</td>"
                 f"<td>{v[3]}/{v[2]}</td><td>{v[4]}/{v[2]}</td></tr>" for d, v in sorted(by_day.items(), reverse=True))
    ctr = "".join(f"<tr><td>{esc(k)}</td><td>{v[2]}</td><td>{roi_txt(v[0], v[1])}</td></tr>" for k, v in sorted(conf.items()))
    body = f"""<h1>成績</h1>
<p>外れも含めた全予想の成績です。買い目は各点100円の均等買いとして集計しています。</p>
<div class="kpis"><div><b>{tot[2]}</b><span>集計レース</span></div><div><b>{roi_txt(tot[0], tot[1])}</b><span>累計回収率</span></div>
<div><b>{(100 * tot[3] / tot[2]) if tot[2] else 0:.1f}%</b><span>◎勝率</span></div><div><b>{(100 * tot[4] / tot[2]) if tot[2] else 0:.1f}%</b><span>◎複勝率</span></div></div>
<section class="card"><h2>累計回収率の推移</h2>{svg_line(cum) or '<p>2日分以上たまると表示します。</p>'}</section>
<section class="card"><h2>日別</h2><div class="scroll"><table><thead><tr><th>日付</th><th>レース</th><th>投資</th><th>払戻</th><th>回収率</th><th>◎1着</th><th>◎3着内</th></tr></thead><tbody>{tr}</tbody></table></div></section>
<section class="card"><h2>自信度別</h2><table><thead><tr><th>自信度</th><th>レース</th><th>回収率</th></tr></thead><tbody>{ctr}</tbody></table></section>
<p class="meta">全予想の記録（CSV）は<a href="https://github.com/bunbunbunzai/keiba-ai/blob/main/results_ledger.csv">GitHub</a>で公開しています。</p>"""
    return page("成績", body, desc="AI競馬予想の全成績。日別・自信度別の回収率と◎の勝率・複勝率。")


ABOUT = """<h1>予想の方法</h1>
<section class="card"><h2>このサイトについて</h2><p>AI（Claude）が、日本で開催される中央競馬（JRA）と地方競馬の全レースを毎日分析しています。予想は前日夜（翌日の出馬表をもとに）と当日昼（当日のオッズ・馬場・午前の傾向をもとに）の2回更新し、全レース終了後に結果と回収率を記録します。外れた予想も削除しません。</p></section>
<section class="card"><h2>評価の5軸（45点満点）</h2><ul>
<li>能力（×3）：直近5走のレースレベル、着差、時計。不利のあった走は内容で補正</li>
<li>条件適性（×2）：距離、コース、馬場状態、回り</li>
<li>展開利（×2）：想定ペースと脚質、枠順、当日の馬場の傾向</li>
<li>状態・ローテ（×1）：間隔、休み明け、馬体重</li>
<li>人的・その他（×1）：騎手、厩舎、斤量、血統</li></ul></section>
<section class="card"><h2>印と買い目</h2><p>評価点の上位に想定勝率を付け、「想定勝率×単勝オッズ」が1.2以上を妙味あり、0.8未満を過剰人気とします。印は◎〇▲△☆、自信度はA・B・C・見送りの4段階です。買い目は原則10点以内です。</p></section>
<section class="card"><h2>データについて</h2><p>出馬表・オッズ・結果は主催者等の公開情報をもとにしています。正式な情報は必ず主催者の発表でご確認ください。</p></section>"""

CSS = """:root{--bg:#f6f5f1;--fg:#1d1d1b;--mut:#6b6a63;--card:#fff;--line:#e3e1d9;--acc:#1f6f4a;--hit:#c0392b;--miss:#8a8a85}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ecebe6;--mut:#a3a29b;--card:#1e1e1c;--line:#33322e;--acc:#5fbf8c;--hit:#ff7a6b;--miss:#8a8a85}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.7 "Hiragino Sans","Noto Sans JP",system-ui,sans-serif}
a{color:var(--acc);text-decoration:none}.wrap{max-width:960px;margin:0 auto;padding:0 16px}
.top{background:var(--card);border-bottom:1px solid var(--line)}.top .wrap{display:flex;flex-wrap:wrap;gap:8px 20px;align-items:center;padding:12px 16px}
.logo{font-weight:700;color:var(--fg)}nav{display:flex;gap:16px;font-size:14px}
h1{font-size:24px;margin:24px 0 4px}h2{font-size:18px;margin:0 0 8px}h3{font-size:15px;margin:16px 0 6px}
.meta,.crumb{color:var(--mut);font-size:14px;margin:0 0 12px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0}
.big{font-size:17px;font-weight:600}.miss{color:var(--miss)}.hit{color:var(--hit);font-weight:700}
.races{list-style:none;padding:0;margin:0;display:grid;gap:6px}.races a{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 12px;color:var(--fg)}
.rno{font-weight:700;min-width:36px}.rt{color:var(--mut);font-size:13px;min-width:44px}.hon{flex:1;min-width:160px}
.conf{display:inline-block;min-width:28px;text-align:center;border-radius:4px;font-size:12px;font-weight:700;padding:0 6px;border:1px solid var(--line)}
.cA{background:#1f6f4a;color:#fff}.cB{background:#3f8f6a;color:#fff}.cC{background:#c9c6b8;color:#1d1d1b}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
.scroll{overflow-x:auto}.horses th,.horses td:not(.cmt){white-space:nowrap}.horses .cmt{min-width:260px}.mark{font-weight:700;color:var(--acc)}.cmt{min-width:220px}tr.mk td{background:rgba(31,111,74,.06)}
.bets{display:flex;flex-wrap:wrap;gap:6px;list-style:none;padding:0}.bets li{border:1px solid var(--line);border-radius:6px;padding:2px 8px;font-size:14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:16px 0}.kpis div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.kpis b{display:block;font-size:24px}.kpis span{color:var(--mut);font-size:13px}
.chart{width:100%;height:auto}.chart .ln{fill:none;stroke:var(--acc);stroke-width:2.5}.chart .base{stroke:var(--mut);stroke-dasharray:4 4}.chart .pt{fill:var(--acc)}.chart .lbl{fill:var(--mut);font-size:12px}.chart .end{text-anchor:end;fill:var(--fg)}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.filters button{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:16px;padding:4px 12px;font:inherit;font-size:13px;cursor:pointer}.filters button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.foot{color:var(--mut);font-size:12px;padding:24px 16px 40px}"""

JS = """(function(){var f=document.querySelector('.filters');if(!f)return;
f.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;
f.querySelectorAll('button').forEach(function(x){x.classList.toggle('on',x===b)});var c=b.dataset.conf;
document.querySelectorAll('.races li').forEach(function(li){li.style.display=(c==='all'||li.dataset.conf===c)?'':'none'})});})();"""


def build() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    (OUT / "style.css").write_text(CSS, encoding="utf-8")
    (OUT / "app.js").write_text(JS, encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    dates = all_dates()
    sections = []
    for i, d in enumerate(dates):
        ps = predictions(d)
        for p in ps:
            f = OUT / "races" / d / f"{p['race_id']}.html"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(race_page(d, p), encoding="utf-8")
        if i < 7:
            sections.append(day_section(d, ps))
    led = ledger()
    st = sum(int(r["stake"]) for r in led)
    rt = sum(int(r["return"]) for r in led)
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    filt = ("<div class='filters'><button class='on' data-conf='all'>すべて</button><button data-conf='A'>自信度A</button>"
            "<button data-conf='B'>B</button><button data-conf='C'>C</button><button data-conf='見送り'>見送り</button></div>")
    body = (f"<h1>本日の全レース予想</h1><p class='meta'>最終更新 {now}　累計回収率 {roi_txt(st, rt)}（{len(led)}レース）</p>"
            + filt + ("".join(sections) or "<p>予想はまだありません。</p>"))
    (OUT / "index.html").write_text(page("本日の全レース予想", body, canon=""), encoding="utf-8")
    (OUT / "results.html").write_text(results_page(led), encoding="utf-8")
    (OUT / "about.html").write_text(page("予想の方法", ABOUT), encoding="utf-8")
    (OUT / "CNAME").write_text(DOMAIN + "\n", encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}sitemap.xml\n", encoding="utf-8")
    urls = sorted(str(p.relative_to(OUT)).replace("\\", "/") for p in OUT.rglob("*.html"))
    sm = "".join(f"<url><loc>{BASE_URL}{'' if u == 'index.html' else u}</loc></url>" for u in urls)
    (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + sm + "</urlset>\n", encoding="utf-8")
    print(f"built {len(dates)} days into {OUT}")


if __name__ == "__main__":
    build()
