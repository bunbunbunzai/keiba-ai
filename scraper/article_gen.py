"""重賞の全頭診断記事を自動で作る（columns/<重賞slug>-<年>.md）。

- 予想がある重賞について、表（印・評価点・想定勝率・買い目・全頭短評）はプログラムで組み、
  文章（結論の根拠・展開・相手・人気との比較・注意点）だけAIに書かせる
- 確定後は「結果と回顧」の節を足す（表はプログラム、回顧文はAI）
- 記事の数字は予想ファイルと出馬表から引く。AIには数字を作らせない

使い方: python scraper/article_gen.py --date 20261108 [--results]
ANTHROPIC_API_KEY が無ければ何もしない。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ai
import digest
from common import DATA_DIR

ROOT = DATA_DIR.parent
sys.path.insert(0, str(ROOT / "site"))
import extra  # noqa: E402

JST = timezone(timedelta(hours=9))
VENUE_SLUG = {
    "札幌": "sapporo", "函館": "hakodate", "福島": "fukushima", "新潟": "niigata", "東京": "tokyo",
    "中山": "nakayama", "中京": "chukyo", "京都": "kyoto", "阪神": "hanshin", "小倉": "kokura",
    "帯広ば": "obihiro", "帯広": "obihiro", "門別": "monbetsu", "盛岡": "morioka", "水沢": "mizusawa",
    "浦和": "urawa", "船橋": "funabashi", "大井": "ooi", "川崎": "kawasaki", "金沢": "kanazawa",
    "笠松": "kasamatsu", "名古屋": "nagoya", "園田": "sonoda", "姫路": "himeji", "高知": "kochi", "佐賀": "saga",
}
WD = "月火水木金土日"
SYSTEM = (
    "あなたは、AIが競馬の全レースを予想して外れも含めた成績を公開するサイト「競馬全頭ログ」の編集者。"
    "与えられた出馬表データとAIの予想（印・評価点・想定勝率・短評・展開予想）をもとに、重賞の予想記事の文章部分を書く。"
    "だ・である調、短く具体的に、絵文字なし。「必ず当たる」などの誇大表現は使わない。"
    "読者は競馬を始めたばかりの人も含む。「想定勝率×単勝」の数値や「確度」「型」などサイト内の用語は並べず、「人気の割に勝ち目がある」「人気ほどの勝ち目はない」のように意味で書く。"
    "数字（着順・タイム・オッズ・評価点・想定勝率）は与えられたものだけを使い、推測で作らない。馬名は与えられた表記のまま。"
    "出力はJSONのみ（前置き・コードブロック不要）。キー："
    "description（検索結果用の説明、100字前後、レース名・年・◎の馬名を含む）、"
    "lead（冒頭の結論、2〜3文、◎とその根拠と相手）、"
    "honmei（◎の根拠、3〜5文）、tenkai（展開予想と有利な脚質、2〜4文）、aite（〇▲△☆の選び方、3〜5文）、"
    "ninki（人気との比較：過剰人気・妙味の馬、2〜4文。オッズが無ければ「オッズ未発表」と書く）、"
    "chui（このレースで外れるならどのパターンか、2〜3文）。"
)
SYSTEM_RESULT = (
    "あなたは「競馬全頭ログ」の編集者。重賞の予想と確定結果を照らして、回顧を書く。だ・である調、絵文字なし。サイト内の計算用語は使わず、初心者にも分かる言葉で書く。"
    "数字は与えられたものだけ。出力はJSONのみ。キー：kaiko（回顧、4〜6文：勝ち馬をどう評価していたか、◎はなぜ勝てた／負けたか、"
    "展開は予想どおりだったか、買い目は妥当だったか、次に活かす点）、"
    "summary（結果の一言、1文、60字以内：的中か不的中かと回収率を含める）。"
)


def load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def horse(race: dict, num) -> dict:
    return next((h for h in race.get("horses", []) or [] if h.get("number") == num), {})


def value_txt(wp, odds) -> str:
    try:
        v = float(wp) / 100 * float(odds)
    except (TypeError, ValueError):
        return "―"
    tag = "妙味あり" if v >= 1.2 else "過剰人気" if v < 0.8 else "妥当"
    return f"{tag}（{v:.2f}）"


def marks_table(pred: dict, race: dict) -> str:
    mk = pred.get("marks", {})
    ev = {e.get("number"): e for e in pred.get("horses", [])}
    rows = []
    for m in ("◎", "〇", "▲", "△", "☆"):
        v = mk.get(m)
        for n in (v if isinstance(v, list) else [v] if v is not None else []):
            h, e = horse(race, n), ev.get(n, {})
            odds = h.get("odds")
            odds_t = f"{odds}" if odds and float(odds) > 0 else "―"
            rows.append(f"| {m} | {n} | {h.get('name') or e.get('name') or ''} | {h.get('frame') or ''} | {h.get('weight') or ''} | {h.get('jockey') or ''} | "
                        f"{e.get('score', '')} | {str(e.get('win_pct')) + '%' if e.get('win_pct') is not None else '―'} | {odds_t} | {value_txt(e.get('win_pct'), odds) if odds and float(odds) > 0 else '―'} |")
    return "| 印 | 馬番 | 馬名 | 枠 | 斤量 | 騎手 | 評価点 | 想定勝率 | 単勝 | 判定 |\n|---|---|---|---|---|---|---|---|---|---|\n" + "\n".join(rows)


def all_table(pred: dict, race: dict) -> str:
    mkmap = {}
    for m, v in pred.get("marks", {}).items():
        for n in (v if isinstance(v, list) else [v] if v is not None else []):
            mkmap[n] = m
    rows = []
    for e in sorted(pred.get("horses", []), key=lambda x: (x.get("number") is None, x.get("number"))):
        n = e.get("number")
        h = horse(race, n)
        rows.append(f"| {n} | {mkmap.get(n, '')} | {h.get('name') or e.get('name') or ''} | {h.get('jockey') or ''} | {e.get('score', '')} | "
                    f"{str(e.get('win_pct')) + '%' if e.get('win_pct') is not None else ''} | {(e.get('comment') or '').replace('|', '｜')} |")
    return "| 馬番 | 印 | 馬名 | 騎手 | 評価点 | 想定勝率 | 短評 |\n|---|---|---|---|---|---|---|\n" + "\n".join(rows)


def bets_text(pred: dict) -> str:
    bets = pred.get("bets", [])
    if not bets:
        return "見送り（買い目なし）。"
    kinds: dict[str, list] = {}
    for b in bets:
        kinds.setdefault(b["type"], []).append(b["combo"])
    return "\n".join(f"- {k}：{'、'.join(v)}（{len(v)}点）" for k, v in kinds.items()) + f"\n\n合計{len(bets)}点・各100円（{len(bets) * 100}円）。"


def race_path(date: str, race: dict, pred: dict) -> str:
    v = pred.get("venue") or race.get("venue") or ""
    rno = int(pred.get("race_no") or race.get("race_no") or 0)
    return f"/{date[:4]}/{date[4:6]}/{date[6:8]}/{VENUE_SLUG.get(v, 'venue')}/{rno:02d}r/"


def _json(text: str) -> dict | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            return None


def frontmatter(meta: dict) -> str:
    return "---\n" + "\n".join(f"{k}: {v}" for k, v in meta.items()) + "\n---\n"


def parse_front(text: str) -> tuple[dict, str]:
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    meta = {}
    if not m:
        return meta, text
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, m.group(2)


def make(date: str, pred: dict, race: dict, slug: str, name: str, grade: str) -> bool:
    out = ROOT / "columns" / f"{slug}.md"
    if out.exists():
        return False
    detail = digest.detail(race, date)
    user = (f"【レース】{race.get('venue')}{race.get('race_no')}R {name}（{grade}）{race.get('surface') or ''}{race.get('distance') or ''}m {race.get('field')}頭 {race.get('post_time') or ''}発走\n"
            f"【出馬表と近走】\n{detail[:9000]}\n\n【AIの予想】\n印：{json.dumps(pred.get('marks'), ensure_ascii=False)}\n自信度：{pred.get('confidence')}\n"
            f"要約：{pred.get('summary')}\n展開：{pred.get('pace')}\n"
            f"全頭の評価：{json.dumps([{k: e.get(k) for k in ('number', 'name', 'score', 'win_pct', 'comment')} for e in pred.get('horses', [])], ensure_ascii=False)}\n"
            f"買い目：{bets_text(pred)}\n\n上のデータだけをもとに、記事の文章部分をJSONで。")
    text = ai.ask("article", SYSTEM, user, max_tokens=8000)
    j = _json(text or "")
    if not j:
        print("article: JSON が得られない", slug)
        return False
    dt = datetime.strptime(date, "%Y%m%d")
    hon = pred.get("marks", {}).get("◎")
    hon_name = horse(race, hon).get("name") or next((e.get("name") for e in pred.get("horses", []) if e.get("number") == hon), "")
    title = f"【AI予想】{name}{dt.year}（{grade}）全{race.get('field') or len(pred.get('horses', []))}頭診断と買い目｜{dt.month}月{dt.day}日（{WD[dt.weekday()]}）{race.get('post_time') or ''}発走"
    cond = " ".join(x for x in (race.get("race_name") or "", race.get("conditions") or "") if x)
    body = (f"## レースの基本情報\n\n- レース：{name}（{grade}）{race.get('venue')}競馬場 第{race.get('race_no')}レース\n"
            f"- 日時：{dt.year}年{dt.month}月{dt.day}日（{WD[dt.weekday()]}）{race.get('post_time') or ''}発走\n"
            f"- 条件：{race.get('surface') or ''}{race.get('distance') or ''}m・{race.get('field')}頭立て" + (f"・{cond}" if cond else "") + "\n"
            f"- このレースのAI予想ページ：[{race.get('venue')}{race.get('race_no')}R {name}]({race_path(date, race, pred)})（結果と的中・回収率はここに反映される）\n\n"
            f"## 結論と印\n\n{marks_table(pred, race)}\n\n自信度：{pred.get('confidence')}（◎の想定勝率で決まる。A：40%以上、B：30〜39%、C：30%未満）。"
            f"単勝は予想を出した時点のオッズ。判定は、AIの見積もった勝つ確率と単勝オッズを掛けた値が1.2以上なら「妙味あり」（人気の割に勝ち目がある）、0.8未満なら「過剰人気」（人気ほどの勝ち目はない）。\n\n"
            f"**◎{hon} {hon_name}の根拠。** {j.get('honmei', '')}\n\n"
            f"## 展開予想\n\n{j.get('tenkai', '')}\n\n## 相手の選び方\n\n{j.get('aite', '')}\n\n## 人気との比較\n\n{j.get('ninki', '')}\n\n"
            f"## 買い目（各100円）\n\n{bets_text(pred)}\n\n" + ("買い目はAIの裁量ではなく型で決めている（◎の単勝か複勝1点＋3連複フォーメーション◎→〇▲→印全部）。型の理由は[3連複フォーメーションのコラム](/column/sanrenpuku-formation/)と[単勝と複勝のコラム](/column/tansho-fukusho/)へ。\n\n" if date >= "20261102" else "") +
            f"## 外れるとしたら\n\n{j.get('chui', '')}\n\n## 全頭診断\n\n{all_table(pred, race)}\n\n"
            f"評価点は能力（×3）・条件適性（×2）・展開利（×2）・状態（×1）・人的要素（×1）の45点満点。予想は当日昼にオッズ・馬体重・馬場の傾向を見て見直すことがあり、変更はレースページの更新履歴に残す。\n\n"
            f"> 馬券は20歳から購入できる。予想は的中や利益を保証するものではない。")
    meta = {"title": title, "description": str(j.get("description", "")).replace("\n", " "), "lead": str(j.get("lead", "")).replace("\n", " "),
            "date": f"{dt.year}-{dt.month:02d}-{dt.day:02d}", "draft": "false", "order": 0, "auto": "true", "race_id": pred["race_id"], "race_date": date}
    out.write_text(frontmatter(meta) + body, encoding="utf-8")
    print("article:", out.name)
    return True


def add_result(date: str, pred: dict, race: dict, slug: str, name: str, grade: str) -> bool:
    out = ROOT / "columns" / f"{slug}.md"
    if not out.exists():
        return False
    meta, body = parse_front(out.read_text(encoding="utf-8"))
    if "## 結果と回顧" in body:
        return False
    rf = DATA_DIR / "results" / date / f"{pred.get('results_key') or pred['race_id']}.json"
    sf = DATA_DIR / "results" / date / "score.json"
    res, score = load(rf) or {}, load(sf) or {}
    sc = next((r for r in score.get("races", []) if r.get("race_id") == pred["race_id"]), None)
    if not res.get("rows") or not sc or "stake" not in sc or sc.get("voided"):
        return False
    rows = sorted((r for r in res["rows"] if str(r.get("finish", "")).isdigit()), key=lambda r: int(r["finish"]))
    mkmap = {}
    for m, v in pred.get("marks", {}).items():
        for n in (v if isinstance(v, list) else [v] if v is not None else []):
            mkmap[n] = m
    rtable = "| 着順 | 馬番 | 馬名 | 印 | 人気 | 4角 | 着差 | 上がり |\n|---|---|---|---|---|---|---|---|\n" + "\n".join(
        f"| {r['finish']} | {r.get('number')} | {r.get('name') or horse(race, r.get('number')).get('name') or ''} | {mkmap.get(r.get('number'), '')} | "
        f"{r.get('popularity') or ''} | {r.get('pos4') or ''} | {r.get('margin') or ''} | {r.get('last3f') or ''} |" for r in rows[:8])
    pay = "、".join(f"{k} {'/'.join(x['combo'] + ' ' + format(x['yen'], ',') + '円' for x in v[:3])}" for k, v in (res.get("payouts") or {}).items() if not k.startswith("_"))
    outcome = "的中（トリガミ）" if 0 < sc["return"] < sc["stake"] else "的中" if sc["return"] else "不的中"
    roi = f"{100 * sc['return'] / sc['stake']:.1f}%" if sc["stake"] else "―"
    user = (f"【レース】{name}（{grade}）{date}\n【予想】印：{json.dumps(pred.get('marks'), ensure_ascii=False)}、自信度{pred.get('confidence')}\n要約：{pred.get('summary')}\n展開予想：{pred.get('pace')}\n"
            f"買い目：{'、'.join(b['type'] + ' ' + b['combo'] for b in pred.get('bets', []))}\n"
            f"全頭の短評：{json.dumps([{k: e.get(k) for k in ('number', 'name', 'score', 'win_pct', 'comment')} for e in pred.get('horses', [])], ensure_ascii=False)}\n"
            f"【結果】\n{rtable}\n払戻：{pay}\n判定：{outcome}、投資{sc['stake']}円→払戻{sc['return']}円、回収率{roi}、的中した買い目：{'、'.join(sc.get('hits', [])) or 'なし'}\n\n回顧をJSONで。")
    text = ai.ask("article", SYSTEM_RESULT, user, max_tokens=5000)
    j = _json(text or "")
    if not j:
        return False
    sec = (f"\n\n## 結果と回顧\n\n{rtable}\n\n払戻：{pay}\n\n**{outcome}**　投資{sc['stake']:,}円→払戻{sc['return']:,}円（回収率{roi}）。"
           + (f"的中した買い目：{'、'.join(sc.get('hits', []))}。" if sc.get("hits") else "") + f"\n\n{j.get('kaiko', '')}\n")
    disclaimer = "> 馬券は20歳から購入できる。予想は的中や利益を保証するものではない。"
    body = body.replace(disclaimer, "").rstrip() + sec + "\n" + disclaimer + "\n"
    meta["title"] = meta.get("title", "").replace("【AI予想】", "【AI予想と結果】", 1)
    if j.get("summary"):
        meta["description"] = (str(j["summary"]).replace("\n", " ") + " " + meta.get("description", ""))[:160]
        meta["lead"] = str(j["summary"]).replace("\n", " ") + " " + meta.get("lead", "")
    out.write_text(frontmatter(meta) + body, encoding="utf-8")
    print("article result:", out.name)
    return True


def targets(date: str):
    for pf in sorted((ROOT / "predictions" / date).glob("*.json")):
        pred = load(pf) or {}
        if not pred.get("race_id") or pred.get("confidence") == "見送り":
            continue
        race = load(DATA_DIR / "races" / date / f"{pred['race_id']}.json") or {}
        name = pred.get("race_name") or race.get("race_name") or race.get("title_text") or ""
        g = extra.grade_of(race, name)
        if not g:
            continue
        cn = extra.clean_name(name)
        slug = f"{extra.graded_slug(name, VENUE_SLUG.get(pred.get('venue') or race.get('venue') or '', 'venue'))}-{date[:4]}"
        yield pred, race, slug, cn, g


def run(date: str, results: bool) -> int:
    if not ai.enabled():
        print("ANTHROPIC_API_KEY が無いので記事は作らない")
        return 0
    n = 0
    for pred, race, slug, cn, g in targets(date):
        if ai.too_many_failures():
            print("APIの失敗が続くので打ち切り", flush=True)
            break
        if results:
            n += add_result(date, pred, race, slug, cn, g)
        else:
            n += make(date, pred, race, slug, cn, g)
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--results", action="store_true", help="確定後の「結果と回顧」を足す")
    a = ap.parse_args()
    print("articles:", run(a.date, a.results))
