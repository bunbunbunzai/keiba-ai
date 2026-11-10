"""戦略別回収率：「もし○○だけ買っていたら」を、確定した全レースの払戻から計算する。

- サイトの買い目（基準）、券種別、自信度別、中央／地方別
- ◎の単勝のみ・複勝のみ、◎-〇のワイド1点・馬連1点
- ◎の人気別（1番人気／2〜3番人気／4番人気以下）、◎の期待値（想定勝率×単勝）別
各点100円の均等買い。見送り・返還は除く。
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from pathlib import Path
import sys as _sys

_sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper"))
import bets as _BT  # noqa: E402
import blend as _BL  # noqa: E402

NEW_TMPL = "基本の買い方（11/8から）：自信度Aだけ3連複（トリガミの組み合わせを外し、複勝なし）＋◎の単複"
BLEND_TMPL = "基本の買い方（11/10）：◎と自信度を補正勝率で決め、11/8の型で買う"
TANPUKU_TMPL = "基本の買い方（11/11から）：◎の単複1点だけ（◎は補正勝率で決める）"

ROOT = Path(__file__).resolve().parent.parent


def _pay(res: dict, kind: str, combo: str) -> int:
    for x in (res.get("payouts") or {}).get(kind, []):
        if str(x.get("combo")) == combo:
            return int(x.get("yen") or 0)
    return 0


def _norm(a, b) -> str:
    return f"{min(int(a), int(b))}-{max(int(a), int(b))}"


class Bucket:
    __slots__ = ("n", "stake", "ret", "hit", "rows")

    def __init__(self):
        self.n = self.stake = self.ret = self.hit = 0
        self.rows: list[tuple[int, int]] = []  # (stake, ret) レースごと。除外検証用

    def add(self, stake: int, ret: int):
        self.n += 1
        self.stake += stake
        self.ret += ret
        self.hit += 1 if ret > 0 else 0
        self.rows.append((stake, ret))

    def roi(self) -> float | None:
        return 100 * self.ret / self.stake if self.stake else None

    def roi_ex_top(self, k: int = 3) -> float | None:
        """払戻の大きい上位k件を除いた回収率。数字が大当たり数件に支えられていないかの確認用。"""
        rest = sorted(self.rows, key=lambda x: -x[1])[k:]
        s = sum(x[0] for x in rest)
        return 100 * sum(x[1] for x in rest) / s if s else None


def collect(preds_by_date: dict[str, list[dict]], stats_from: str) -> dict[str, dict[str, Bucket]]:
    """preds は build.predictions() の出力（_race, _score, _result 付き）。"""
    g: dict[str, dict[str, Bucket]] = defaultdict(lambda: defaultdict(Bucket))

    def add(group: str, key: str, stake: int, ret: int):
        g[group][key].add(stake, ret)

    for d, preds in preds_by_date.items():
        if d < stats_from:
            continue
        for p in preds:
            sc = p.get("_score")
            if not sc or "stake" not in sc or sc.get("voided") or not sc["stake"]:
                continue
            res = p.get("_result") or {}
            if not res.get("payouts"):
                continue
            m = p.get("marks", {})
            hon, tai = m.get("◎"), m.get("〇")
            if hon is None:
                continue
            jra = str(p["race_id"]).startswith("jra_")
            conf = p.get("confidence") or "-"
            add("base", "サイトの買い目すべて", sc["stake"], sc["return"])
            add("conf", f"自信度{conf}のレースだけ", sc["stake"], sc["return"])
            add("src", "中央（JRA）だけ" if jra else "地方だけ", sc["stake"], sc["return"])
            # 券種別（サイトの買い目のうち、その券種だけ）
            hit = {}
            for h in sc.get("hits", []):
                parts = h.split()
                if len(parts) >= 3 and "返還" not in h and parts[2].rstrip("円").isdigit():
                    hit[" ".join(parts[:2])] = int(parts[2].rstrip("円"))
            bt = defaultdict(lambda: [0, 0])
            for b in p.get("bets", []):
                k = f"{b['type']} {b['combo']}"
                bt[b["type"]][0] += 100
                bt[b["type"]][1] += hit.get(k, 0)
            for t, (s_, r_) in bt.items():
                add("bet", f"{t}だけ", s_, r_)
            # ◎の単勝・複勝
            add("hon", "◎の単勝だけ（1点）", 100, _pay(res, "単勝", str(hon)))
            add("hon", "◎の複勝だけ（1点）", 100, _pay(res, "複勝", str(hon)))
            if tai is not None:
                add("hon", "◎-〇のワイド1点", 100, _pay(res, "ワイド", _norm(hon, tai)))
                add("hon", "◎-〇の馬連1点", 100, _pay(res, "馬連", _norm(hon, tai)))
            # 型の買い目（2026-11-02からの標準）：◎の単複（人気で切替）＋3連複 ◎→〇▲→印全部
            pop0 = next((h.get("popularity") for h in p["_race"].get("horses", []) or [] if h.get("number") == hon), None)
            od0 = next((h.get("odds") for h in p["_race"].get("horses", []) or [] if h.get("number") == hon), None)
            try:
                od0 = float(od0) if od0 else None
            except (TypeError, ValueError):
                od0 = None
            if (pop0 and pop0 <= 2) or (od0 and od0 < 4.0) or (not pop0 and not od0):
                tanpuku = ("複勝", _pay(res, "複勝", str(hon)))
            elif (pop0 and pop0 <= 5) or (od0 and od0 < 10.0):
                tanpuku = ("単勝", _pay(res, "単勝", str(hon)))
            else:
                tanpuku = None
            def _lst(k):
                v = m.get(k)
                return [int(x) for x in (v if isinstance(v, list) else [v] if v is not None else []) if x is not None and int(x) != int(hon)]
            top = _lst("〇") + _lst("▲")
            marks = top + _lst("△") + _lst("☆")
            fo = {tuple(sorted((int(hon), a, b))) for a in top for b in marks if b != a}
            fo_ret = sum(_pay(res, "3連複", "-".join(map(str, c))) for c in fo)
            if fo:
                add("tmpl", "3連複 ◎→〇▲→印全部（フォーメーション）", 100 * len(fo), fo_ret)
                add("tmpl", "基本の買い方：◎の単複（人気で切替）＋3連複フォーメーション", 100 * len(fo) + (100 if tanpuku else 0), fo_ret + (tanpuku[1] if tanpuku else 0))
                add("tmpl", "複勝◎＋3連複フォーメーション", 100 * len(fo) + 100, fo_ret + _pay(res, "複勝", str(hon)))
            if conf == "A" and fo:
                add("tmpl", "基本の買い方（11/7から）：◎の単複＋自信度Aだけ3連複フォーメーション", 100 * len(fo) + (100 if tanpuku else 0), fo_ret + (tanpuku[1] if tanpuku else 0))
            elif tanpuku:
                add("tmpl", "基本の買い方（11/7から）：◎の単複＋自信度Aだけ3連複フォーメーション", 100, tanpuku[1])
            # 11/8からの買い方：オッズを見てトリガミの組み合わせを外す（scraper/bets.py と同じ組み方。過去分は単勝オッズからの推定）
            try:
                built, _ = _BT.build(p, p.get("_race") or {}, _BT.load_trio(d, p.get("race_id")), with_trio=True)
            except Exception:  # noqa: BLE001
                built = None
            if built:
                add("tmpl", NEW_TMPL, 100 * len(built), sum(_pay(res, b["type"], str(b["combo"])) for b in built))
            try:  # 11/10からの型：◎と自信度を補正勝率で決め直してから買い目を組む（過去分はその時点の単勝オッズで）
                q = _BL.blend(p, p.get("_race") or {})
                built2, _ = _BT.build(q, p.get("_race") or {}, _BT.load_trio(d, p.get("race_id")), with_trio=True) if q else (None, "")
                built3, _ = _BT.build(q, p.get("_race") or {}) if q else (None, "")
            except Exception:  # noqa: BLE001
                built2 = built3 = None
            if built2:
                add("tmpl", BLEND_TMPL, 100 * len(built2), sum(_pay(res, b["type"], str(b["combo"])) for b in built2))
            if built3:  # 11/11からの型：補正勝率の◎の単複1点
                add("tmpl", TANPUKU_TMPL, 100 * len(built3), sum(_pay(res, b["type"], str(b["combo"])) for b in built3))
            if tanpuku:
                add("tmpl", f"◎の単複（人気で切替）のみ", 100, tanpuku[1])
            # 型の比較用（11/2の週次見直しで候補に残した買い方）：◎から印全部へ流す
            if marks:
                add("tmpl", "ワイド ◎→印全部", 100 * len(marks), sum(_pay(res, "ワイド", _norm(hon, x)) for x in marks))
                add("tmpl", "馬連 ◎→印全部", 100 * len(marks), sum(_pay(res, "馬連", _norm(hon, x)) for x in marks))
            if len(marks) >= 2:
                ng = {tuple(sorted((int(hon), a, b))) for a, b in combinations(marks, 2)}
                add("tmpl", "3連複 ◎→印全部（2頭流し）", 100 * len(ng), sum(_pay(res, "3連複", "-".join(map(str, c))) for c in ng))
            # ◎の人気
            pop = next((h.get("popularity") for h in p["_race"].get("horses", []) or [] if h.get("number") == hon), None)
            if pop:
                band = "◎が1番人気" if pop == 1 else "◎が2〜3番人気" if pop <= 3 else "◎が4〜6番人気" if pop <= 6 else "◎が7番人気以下"
                add("pop", band, sc["stake"], sc["return"])
                add("pop_win", band + "（単勝1点）", 100, _pay(res, "単勝", str(hon)))
                add("pop_place", band + "（複勝1点）", 100, _pay(res, "複勝", str(hon)))
            # ◎の期待値
            wp = next((h.get("win_pct") for h in p.get("horses", []) if h.get("number") == hon), None)
            od = next((h.get("odds") for h in p["_race"].get("horses", []) or [] if h.get("number") == hon), None)
            try:
                val = float(wp) / 100 * float(od) if wp is not None and od else None
            except (TypeError, ValueError):
                val = None
            if val is not None:
                band = "期待値1.5以上" if val >= 1.5 else "期待値1.0〜1.5" if val >= 1.0 else "期待値0.7〜1.0" if val >= 0.7 else "期待値0.7未満"
                add("val", band, sc["stake"], sc["return"])
                add("val_win", band + "（◎単勝1点）", 100, _pay(res, "単勝", str(hon)))
    return g


GROUPS = [
    ("base", "基準：サイトの買い目", "各レースの買い目をすべて各点100円で買った場合（成績ページと同じ）。"),
    ("tmpl", "基本の買い方", "11/11からは◎の単複1点だけ（1〜2番人気は複勝、3〜5番人気は単勝、6番人気以下は買わない）。◎と自信度は補正勝率（単勝オッズとAIの評価を合わせた勝つ確率）で決める。それまでの型も比べられるように残している：3連複フォーメーション（1頭目◎、2頭目〇▲、3頭目は印全部）を足した型（〜11/6）、3連複を自信度Aだけにした型（11/7）、オッズを見て当たっても購入額を下回る組み合わせ（トリガミ）を外し複勝を買わない型（11/8〜11/10）。過去のレースには、その時点の単勝オッズと推定オッズで当てはめている。補正勝率の計算式は過去のレースから求めたものなので、過去に当てはめた成績は実際より少し良く出やすい（学習に使っていないレースで試すと◎の単複は約83%だった）。比較用に、同じ印から◎を軸に印全部へ流すワイド・馬連・3連複（2頭流し）も載せる。"),
    ("hon", "◎・〇だけを買う", "印の上位だけを1点ずつ買った場合。買い目を減らすと当たる回数は減るが、使う金額も減る。"),
    ("bet", "券種をしぼる", "サイトの買い目のうち、その券種だけを買った場合。"),
    ("conf", "自信度でしぼる", "自信度が高いレースだけを買った場合。"),
    ("val", "◎の期待値でしぼる", "期待値＝AIの想定勝率×予想時点の単勝オッズ。1.0以上は、AIが世間の人気より高く評価している馬。サイトの買い目で計算。"),
    ("val_win", "◎の期待値でしぼる（単勝1点）", "同じ区分で、◎の単勝だけを100円買った場合。"),
    ("pop", "◎の人気でしぼる", "予想を出した時点の単勝人気。サイトの買い目で計算。"),
    ("pop_win", "◎の人気でしぼる（単勝1点）", "同じ区分で、◎の単勝だけを100円買った場合。"),
    ("pop_place", "◎の人気でしぼる（複勝1点）", "同じ区分で、◎の複勝だけを100円買った場合。単勝と見比べると、人気ごとにどちらが向くかが分かる。"),
    ("src", "中央と地方", "JRAと地方競馬を分けた場合。"),
]


def _order(group: str, keys: list[str]) -> list[str]:
    fixed = {
        "conf": ["自信度Aのレースだけ", "自信度Bのレースだけ", "自信度Cのレースだけ"],
        "val": ["期待値1.5以上", "期待値1.0〜1.5", "期待値0.7〜1.0", "期待値0.7未満"],
        "pop": ["◎が1番人気", "◎が2〜3番人気", "◎が4〜6番人気", "◎が7番人気以下"],
        "tmpl": [TANPUKU_TMPL, BLEND_TMPL, NEW_TMPL, "基本の買い方（11/7から）：◎の単複＋自信度Aだけ3連複フォーメーション", "基本の買い方：◎の単複（人気で切替）＋3連複フォーメーション", "◎の単複（人気で切替）のみ", "3連複 ◎→〇▲→印全部（フォーメーション）",
                 "複勝◎＋3連複フォーメーション", "3連複 ◎→印全部（2頭流し）", "ワイド ◎→印全部", "馬連 ◎→印全部"],
        "hon": ["◎の単勝だけ（1点）", "◎の複勝だけ（1点）", "◎-〇のワイド1点", "◎-〇の馬連1点"],
        "bet": ["単勝だけ", "複勝だけ", "ワイドだけ", "馬連だけ", "馬単だけ", "3連複だけ", "3連単だけ"],
    }
    base = fixed.get(group.replace("_win", "").replace("_place", ""), [])
    if group.endswith("_win") or group.endswith("_place"):
        base = [b + ("（単勝1点）" if group == "pop_win" else "（複勝1点）" if group == "pop_place" else "（◎単勝1点）") for b in base]
    return [k for k in base if k in keys] + sorted(k for k in keys if k not in base)


def render(g: dict[str, dict[str, Bucket]], esc, roi_txt, since: str, asof: str) -> tuple[str, list[tuple[str, float, int]]]:
    """HTML本文と、回収率上位（レース数20以上）の一覧を返す。"""
    base = g["base"].get("サイトの買い目すべて")
    sections = []
    ranking: list[tuple[str, float, int]] = []
    for key, title, note in GROUPS:
        bs = g.get(key) or {}
        if not bs:
            continue
        rows = []
        for k in _order(key, list(bs)):
            b = bs[k]
            r = b.roi()
            cls = "hit" if r is not None and r >= 100 else "tg" if r is not None and r >= 85 else ""
            ex = b.roi_ex_top(3)
            ex_txt = f"{ex:.1f}%" if ex is not None and b.n > 3 else "-"
            rows.append(f"<tr><td>{esc(k)}</td><td>{b.n:,}</td><td>{b.hit:,}（{100 * b.hit / b.n:.0f}%）</td>"
                        f"<td>{b.stake:,}円</td><td>{b.ret:,}円</td><td class='{cls}'><b>{roi_txt(b.stake, b.ret)}</b></td><td>{b.ret - b.stake:+,}円</td><td>{ex_txt}</td></tr>")
            if key != "base" and b.n >= 100 and r is not None:  # 冒頭で紹介するのは偶然の影響が小さい100レース以上の買い方だけ
                ranking.append((k, r, b.n, ex))
        sections.append(f"<section class='card'><h2>{esc(title)}</h2><p class='meta'>{esc(note)}</p><div class='scroll'><table>"
                        "<thead><tr><th>買い方</th><th>レース</th><th>的中</th><th>購入額</th><th>払戻</th><th>回収率</th><th>収支</th><th>大当たり3回を除く</th></tr></thead>"
                        f"<tbody>{''.join(rows)}</tbody></table></div></section>")
    ranking.sort(key=lambda x: -x[1])
    intro = ""
    if base:
        intro = (f"<p class='answer'>{since}〜{asof}の{base.n:,}レースで、サイトの買い目をすべて買った場合の回収率は{roi_txt(base.stake, base.ret)}。"
                 + (f"同じ予想でも買い方を変えると、100レース以上ある買い方の中で回収率が最も高かったのは「{esc(ranking[0][0])}」の{ranking[0][1]:.1f}%（{ranking[0][2]:,}レース"
                    + (f"、大当たり3回を除くと{ranking[0][3]:.1f}%" if ranking[0][3] is not None else "") + "）だった。" if ranking else "") + "</p>")
    note = ("<p class='meta'>どれも買い目を1点100円ずつ買ったとして計算。買い目を出さなかった「見送り」と、返還になったレースは含まない。レース数が少ない区分（目安50レース未満）は偶然の影響が大きく、"
            "高配当が1回出るだけで数字が大きく動く。「大当たり3回を除く」は払戻が大きかった3レースを除いた回収率。数字がたまたまの大当たりに支えられていないかの目安になる。"
            "「過去にこう買えば勝てた」は、これから勝てることを意味しない。</p>")
    return intro + note + "".join(sections), ranking
