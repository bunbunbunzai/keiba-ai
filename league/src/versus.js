/* 「AI vs あなた」月間ランキングのルールとサーバー側の検証。
 *
 * 読者はレースごとに◎を1頭選ぶ（発走時刻まで変更可）。結果が出たら、
 *   - 順位：その月に選んだ◎の単勝を100円ずつ買ったとしたときの回収率（MIN_PICKS レース以上が対象）
 *   - AIとの対戦成績：同じレースでの「あなたの◎の着順」と「AIの◎の着順」の比較（勝ち・負け・引き分け）
 * を出す。レース・出走馬・発走時刻・結果・単勝の払戻は、サイトが公開している /vsgame/<日付>.json だけを使う
 * （管理者の手入力は無い）。取消・除外になった◎と、払戻の無いレースは、買わなかった扱いで数えない。
 *
 * 利用者の登録とトークンは core.js（オーナーズリーグ）の users をそのまま使う。
 */
import { LeagueError } from "./core.js";

export const MIN_PICKS = 20;      // 月間ランキングの対象になる最少レース数
export const STAKE = 100;         // 1レースの購入額（円）
export const NAME_MIN = 2, NAME_MAX = 12;

export const VS_SCHEMA = [
  `CREATE TABLE IF NOT EXISTS vs_players (user_id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)`,
  // path：サイトのレースページのパス（/2026/11/19/kasamatsu/11r/）。post：発走（YYYYMMDDHHMM・日本時間）
  `CREATE TABLE IF NOT EXISTS vs_picks (user_id TEXT NOT NULL, path TEXT NOT NULL, date TEXT NOT NULL, post TEXT NOT NULL, number INTEGER NOT NULL, label TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL, PRIMARY KEY (user_id, path))`,
  `CREATE INDEX IF NOT EXISTS vs_picks_date ON vs_picks (date)`,
  // 確定したレース。fin：{馬番: 着順の文字}、win：[[馬番, 100円あたりの払戻], ...]（同着は複数）
  `CREATE TABLE IF NOT EXISTS vs_results (path TEXT PRIMARY KEY, date TEXT NOT NULL, ai INTEGER, fin TEXT NOT NULL, win TEXT NOT NULL, label TEXT NOT NULL DEFAULT '')`,
  `CREATE INDEX IF NOT EXISTS vs_results_date ON vs_results (date)`,
  `CREATE TABLE IF NOT EXISTS vs_fetch (date TEXT PRIMARY KEY, at INTEGER NOT NULL)`,
];

const bad = (m, status = 400) => { throw new LeagueError(status, m); };

/** 日本時間の "YYYYMMDDHHMM" */
export function jstKey(ms) {
  return new Date(ms + 9 * 3600e3).toISOString().slice(0, 16).replace(/[-T:]/g, "");
}
const PATH_RE = /^\/(\d{4})\/(\d{2})\/(\d{2})\/[a-z]+\/\d{2}r\/$/;

export function nameKey(name) {
  return String(name).normalize("NFKC").toLowerCase().replace(/[\s　]/g, "");
}

/** 1つの◎の結果。counted=false は「買わなかった扱い」（取消・除外、払戻なし）。 */
export function judge(number, res) {
  const fin = res.fin || {}, win = res.win || [];
  const mine = fin[String(number)];
  if (!win.length || mine === undefined || !/^\d+$/.test(String(mine))) return { counted: false, finish: mine === undefined ? "取消" : String(mine) };
  const w = win.find((x) => Number(x[0]) === Number(number));
  const out = { counted: true, finish: String(mine), ret: w ? Number(w[1]) : 0, hit: !!w, vs: null, ai: res.ai ?? null, ai_finish: null };
  if (res.ai != null) {
    const a = fin[String(res.ai)];
    out.ai_finish = a === undefined ? null : String(a);
    const me = parseInt(mine, 10), ai = /^\d+$/.test(String(a)) ? parseInt(a, 10) : 99;  // AIの◎が取消・中止なら最下位扱い（今の「AI vs あなた」と同じ）
    out.vs = me < ai ? "win" : me > ai ? "lose" : "draw";
  }
  return out;
}

export class Versus {
  /** sql: { exec(query, ...binds) → { toArray() } }、now: () => epoch ms、load: async (date "YYYYMMDD") → /vsgame/<date>.json の中身（無ければ null） */
  constructor(sql, now = () => Date.now(), load = async () => null) {
    this.sql = sql; this.now = now; this.load = load;
    for (const q of VS_SCHEMA) this.sql.exec(q);
  }
  all(q, ...b) { return this.sql.exec(q, ...b).toArray(); }
  one(q, ...b) { return this.all(q, ...b)[0] || null; }
  run(q, ...b) { this.sql.exec(q, ...b); }
  nowKey() { return jstKey(this.now()); }

  // ---------------- 名前 ----------------
  player(uid) { return this.one("SELECT name FROM vs_players WHERE user_id = ?", uid); }
  saveName(uid, name) {
    name = String(name || "").normalize("NFKC").trim();
    const n = [...name].length;
    if (n < NAME_MIN || n > NAME_MAX) bad(`名前は${NAME_MIN}〜${NAME_MAX}文字で入れてください。`);
    if (/[<>&"'\\/\u0000-\u001f]|https?:|www\./i.test(name)) bad("名前に使えない文字が入っています。");
    const key = nameKey(name);
    if (/^(ai|全頭くん|競馬全頭ログ|運営|管理者|admin)$/.test(key)) bad("その名前は使えません。");
    const dup = this.one("SELECT user_id FROM vs_players WHERE name_key = ?", key);
    if (dup && dup.user_id !== uid) bad("その名前はすでに使われています。", 409);
    this.run("INSERT INTO vs_players (user_id, name, name_key, created_at) VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET name = excluded.name, name_key = excluded.name_key",
      uid, name, key, this.nowKey());
    return { name };
  }

  /** 管理者：不適切な名前の参加者を、選んだ◎ごと消す（本人は別の名前で登録し直せる）。 */
  removePlayer(name) {
    const r = this.one("SELECT user_id FROM vs_players WHERE name_key = ?", nameKey(String(name || "")));
    if (!r) bad("その名前の参加者はいません。", 404);
    this.run("DELETE FROM vs_picks WHERE user_id = ?", r.user_id);
    this.run("DELETE FROM vs_players WHERE user_id = ?", r.user_id);
    return { removed: true };
  }

  // ---------------- ◎を選ぶ ----------------
  async pick(uid, path, number) {
    if (!this.player(uid)) bad("先にランキング用の名前を登録してください。");
    const m = PATH_RE.exec(String(path || ""));
    if (!m) bad("レースの指定が正しくありません。");
    number = Number(number);
    if (!Number.isInteger(number)) bad("馬番が正しくありません。");
    const date = m[1] + m[2] + m[3];
    const day = await this.load(date);
    const rc = day && day[path];
    if (!rc) bad("このレースは対象外です（予想が出ていないか、見送りのレース）。", 404);
    if (!(rc.nums || []).includes(number)) bad("その馬番は出走していません。");
    if (!rc.post || this.nowKey() >= rc.post) bad("発走時刻を過ぎたので、選べません。", 409);
    this.run("INSERT INTO vs_picks (user_id, path, date, post, number, label, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
      + "ON CONFLICT(user_id, path) DO UPDATE SET number = excluded.number, post = excluded.post, label = excluded.label, updated_at = excluded.updated_at",
      uid, path, date, rc.post, number, String(rc.label || "").slice(0, 60), this.nowKey());
    return { path, number, post: rc.post };
  }
  myPick(uid, path) {
    const r = this.one("SELECT number FROM vs_picks WHERE user_id = ? AND path = ?", uid, path);
    return { path, number: r ? r.number : null };
  }

  // ---------------- 結果の取り込み ----------------
  /** 発走を過ぎたのに結果がまだ無い◎がある日のデータを読み直す（同じ日は1分に1回まで）。 */
  async settle() {
    const now = this.nowKey(), sec = Math.floor(this.now() / 1000);
    const days = this.all("SELECT DISTINCT p.date AS date FROM vs_picks p LEFT JOIN vs_results r ON r.path = p.path WHERE r.path IS NULL AND p.post <= ? ORDER BY p.date", now);
    for (const { date } of days) {
      const f = this.one("SELECT at FROM vs_fetch WHERE date = ?", date);
      if (f && sec - f.at < 60) continue;
      this.run("INSERT INTO vs_fetch (date, at) VALUES (?, ?) ON CONFLICT(date) DO UPDATE SET at = excluded.at", date, sec);
      let day = null;
      try { day = await this.load(date); } catch { day = null; }
      if (!day) continue;
      for (const [path, rc] of Object.entries(day)) {
        if (!rc || !rc.fin) continue;  // まだ確定していない
        this.run("INSERT INTO vs_results (path, date, ai, fin, win, label) VALUES (?, ?, ?, ?, ?, ?) "
          + "ON CONFLICT(path) DO UPDATE SET ai = excluded.ai, fin = excluded.fin, win = excluded.win, label = excluded.label",
          path, date, rc.ai ?? null, JSON.stringify(rc.fin), JSON.stringify(rc.win || []), String(rc.label || "").slice(0, 60));
      }
    }
  }

  // ---------------- 集計 ----------------
  /** その月（"YYYY-MM"）の利用者ごとの成績。確定したレースだけ。 */
  stats(ym) {
    const pre = ym.replace("-", "");
    const rows = this.all("SELECT p.user_id, p.path, p.number, r.ai, r.fin, r.win FROM vs_picks p JOIN vs_results r ON r.path = p.path WHERE p.date LIKE ? ORDER BY p.date, p.path", pre + "%");
    const by = new Map();
    for (const x of rows) {
      const j = judge(x.number, { ai: x.ai, fin: JSON.parse(x.fin), win: JSON.parse(x.win) });
      if (!j.counted) continue;
      const s = by.get(x.user_id) || { user_id: x.user_id, n: 0, hits: 0, ret: 0, win: 0, lose: 0, draw: 0 };
      s.n++; s.ret += j.ret; if (j.hit) s.hits++;
      if (j.vs) s[j.vs]++;
      by.set(x.user_id, s);
    }
    for (const s of by.values()) { s.stake = s.n * STAKE; s.roi = s.stake ? Math.round(s.ret * 1000 / s.stake) / 10 : 0; }
    return by;
  }
  async ranking(ym, uid = null, minPicks = MIN_PICKS) {
    if (!/^\d{4}-\d{2}$/.test(String(ym || ""))) bad("月の指定が正しくありません。");
    await this.settle();
    const by = this.stats(ym);
    const names = new Map(this.all("SELECT user_id, name FROM vs_players").map((r) => [r.user_id, r.name]));
    const rows = [...by.values()].filter((s) => names.has(s.user_id)).map((s) => ({ ...s, name: names.get(s.user_id) }));
    // 回収率の高い順。同じなら的中数、レース数の多い順。まったく同じなら同順位
    const cmp = (a, b) => b.roi - a.roi || b.hits - a.hits || b.n - a.n;
    const ranked = rows.filter((s) => s.n >= minPicks).sort(cmp);
    ranked.forEach((s, i) => { s.rank = i > 0 && cmp(ranked[i - 1], s) === 0 ? ranked[i - 1].rank : i + 1; });
    const pub = (s) => ({ rank: s.rank ?? null, name: s.name, n: s.n, hits: s.hits, stake: s.stake, ret: s.ret, roi: s.roi, win: s.win, lose: s.lose, draw: s.draw, me: s.user_id === uid });
    const meRow = uid ? rows.find((s) => s.user_id === uid) : null;
    const pending = uid ? this.one("SELECT COUNT(*) AS n FROM vs_picks p LEFT JOIN vs_results r ON r.path = p.path WHERE p.user_id = ? AND p.date LIKE ? AND r.path IS NULL", uid, ym.replace("-", "") + "%").n : 0;
    return {
      ym, min_picks: minPicks, ranked: ranked.slice(0, 100).map(pub), players: rows.length,
      beat_ai: rows.filter((s) => s.win > s.lose).length,
      me: uid ? { name: names.get(uid) || null, stats: meRow ? pub(meRow) : null, pending } : null,
      months: this.all("SELECT DISTINCT substr(date, 1, 6) AS m FROM vs_picks ORDER BY m DESC LIMIT 12").map((r) => r.m.slice(0, 4) + "-" + r.m.slice(4)),
    };
  }
  /** 自分の最近の◎（結果つき） */
  history(uid, limit = 30) {
    const rows = this.all("SELECT p.path, p.number, p.label, p.post, r.ai, r.fin, r.win FROM vs_picks p LEFT JOIN vs_results r ON r.path = p.path WHERE p.user_id = ? ORDER BY p.post DESC LIMIT ?", uid, limit);
    return rows.map((x) => {
      const o = { path: x.path, label: x.label, post: x.post, number: x.number, settled: !!x.fin };
      if (x.fin) Object.assign(o, judge(x.number, { ai: x.ai, fin: JSON.parse(x.fin), win: JSON.parse(x.win) }));
      return o;
    });
  }
}
