/* 全頭ログ オーナーズリーグ：ゲームのルールとサーバー側の検証（Workers の Durable Object とテストで共用）。
 *
 * 時刻はすべて JST。締切・発走は "YYYY-MM-DDTHH:MM" の JST 文字列で持ち、比較は epoch ミリ秒で行う。
 * 得点は実レースの確定着順だけから計算する（賞金・オッズは使わない）。
 * 同じ結果を何度入れ直しても、節ごとの得点は「その節の得点を全部消して作り直す」ので二重にならない。
 */

export const STATS = ["speed", "stamina", "power"];
export const STAT_LABEL = { speed: "スピード", stamina: "スタミナ", power: "パワー" };
export const APTITUDES = ["turf_short", "turf_long", "dirt"];
export const APT_LABEL = { turf_short: "芝短距離", turf_long: "芝中長距離", dirt: "ダート" };
export const APT_STAT = { turf_short: "speed", turf_long: "stamina", dirt: "power" };
export const POINTS = { 1: 1000, 2: 600, 3: 400, 4: 250, 5: 150 };
export const BONUS_PER_LEVEL = 0.05;
export const BONUS_MAX = 0.10;
export const ROUNDS_PER_MONTH = 4;
export const BEST_OF = 3;
export const PRIZES = [1000, 500, 500]; // 円（Amazonギフトカード）。月間総額2,000円
export const SILK_COLORS = ["#146b45", "#c0122d", "#1d4ed8", "#f2c200", "#ffffff", "#17201b", "#e8792b", "#7c3aed", "#ec4899", "#0ea5e9"];
export const SILK_PATTERNS = ["solid", "stripes", "hoops", "sash", "stars", "halves"];

export class LeagueError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const bad = (m) => { throw new LeagueError(400, m); };

export function jstMs(s) {
  // "YYYY-MM-DDTHH:MM" (JST) → epoch ms
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(String(s || ""));
  if (!m) bad("日時の形式が正しくありません（YYYY-MM-DDTHH:MM、日本時間）");
  return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4] - 9, +m[5]);
}
export function jstNowStr(ms) {
  const d = new Date(ms + 9 * 3600 * 1000);
  return d.toISOString().slice(0, 16);
}

export const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS horses (user_id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE, silks TEXT NOT NULL, created_at TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS months (ym TEXT PRIMARY KEY, prize_enabled INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'open', finalized_at TEXT, approved INTEGER NOT NULL DEFAULT 0, approved_at TEXT)`,
  `CREATE TABLE IF NOT EXISTS rounds (id TEXT PRIMARY KEY, ym TEXT NOT NULL, idx INTEGER NOT NULL, title TEXT, deadline TEXT, UNIQUE(ym, idx))`,
  `CREATE TABLE IF NOT EXISTS races (id TEXT PRIMARY KEY, round_id TEXT NOT NULL, label TEXT NOT NULL, post TEXT NOT NULL, aptitude TEXT NOT NULL, site_race_id TEXT, article_url TEXT, field TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'scheduled', result TEXT, result_version INTEGER NOT NULL DEFAULT 0)`,
  `CREATE TABLE IF NOT EXISTS trainings (user_id TEXT NOT NULL, round_id TEXT NOT NULL, ym TEXT NOT NULL, idx INTEGER NOT NULL, stat TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY (user_id, round_id))`,
  `CREATE TABLE IF NOT EXISTS entries (user_id TEXT NOT NULL, round_id TEXT NOT NULL, race_id TEXT NOT NULL, number INTEGER NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (user_id, round_id))`,
  `CREATE TABLE IF NOT EXISTS scores (user_id TEXT NOT NULL, round_id TEXT NOT NULL, ym TEXT NOT NULL, race_id TEXT NOT NULL, number INTEGER NOT NULL, finish TEXT, base INTEGER NOT NULL, bonus_pct INTEGER NOT NULL, points INTEGER NOT NULL, note TEXT, PRIMARY KEY (user_id, round_id))`,
  `CREATE TABLE IF NOT EXISTS month_results (ym TEXT NOT NULL, user_id TEXT NOT NULL, rank INTEGER NOT NULL, total INTEGER NOT NULL, best TEXT NOT NULL, title TEXT, prize_yen INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (ym, user_id))`,
  `CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS reg_limits (k TEXT PRIMARY KEY, n INTEGER NOT NULL, exp INTEGER NOT NULL)`,
];

async function sha256(s) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
function randomId(bytes = 24) {
  const a = new Uint8Array(bytes);
  crypto.getRandomValues(a);
  return btoa(String.fromCharCode(...a)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export class League {
  /** sql: { exec(query, ...binds) → { toArray() } }、now: () => epoch ms */
  constructor(sql, now = () => Date.now()) {
    this.sql = sql;
    this.now = now;
    for (const q of SCHEMA) this.sql.exec(q);
  }
  all(q, ...b) { return this.sql.exec(q, ...b).toArray(); }
  one(q, ...b) { return this.all(q, ...b)[0] || null; }
  run(q, ...b) { this.sql.exec(q, ...b); }
  nowStr() { return jstNowStr(this.now()); }

  // ---------------- 設定 ----------------
  setting(k, def = "0") { const r = this.one("SELECT v FROM settings WHERE k = ?", k); return r ? r.v : def; }
  setSetting(k, v) { this.run("INSERT INTO settings (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", k, String(v)); }
  flags(env = {}) {
    // 環境変数（運営側の大元のスイッチ）と管理画面の設定の両方が ON のときだけ ON
    return {
      public: env.LEAGUE_PUBLIC === "1" && this.setting("public") === "1",
      prizes_allowed: env.PRIZES_ALLOWED === "1" && this.setting("prizes_allowed") === "1",
    };
  }

  // ---------------- 利用者 ----------------
  async register(ipKey = "") {
    if (ipKey) {
      const now = Math.floor(this.now() / 1000);
      this.run("DELETE FROM reg_limits WHERE exp < ?", now);
      const r = this.one("SELECT n FROM reg_limits WHERE k = ?", ipKey);
      if (r && r.n >= 5) throw new LeagueError(429, "登録が多すぎます。時間をおいてからどうぞ。");
      this.run("INSERT INTO reg_limits (k, n, exp) VALUES (?, 1, ?) ON CONFLICT(k) DO UPDATE SET n = n + 1", ipKey, now + 86400);
    }
    const id = "u_" + randomId(9);
    const token = randomId(24);
    this.run("INSERT INTO users (id, token_hash, created_at) VALUES (?, ?, ?)", id, await sha256(token), this.nowStr());
    return { user_id: id, token };
  }
  async auth(token) {
    if (!token) throw new LeagueError(401, "厩舎の登録が必要です。");
    const u = this.one("SELECT id FROM users WHERE token_hash = ?", await sha256(token));
    if (!u) throw new LeagueError(401, "登録情報が見つかりません。もう一度、厩舎を作ってください。");
    return u.id;
  }

  // ---------------- 馬 ----------------
  saveHorse(uid, { name, silks }) {
    const nm = String(name || "").trim().normalize("NFKC");
    if (nm.length < 2 || nm.length > 12) bad("馬名は2〜12文字で入力してください。");
    if (/https?:|www\.|@|[<>{}\\]|[\u0000-\u001f]/i.test(nm)) bad("馬名に使えない文字が含まれています。");
    const s = silks || {};
    const sk = { body: s.body, sleeve: s.sleeve, pattern: s.pattern, accent: s.accent || s.sleeve };
    if (![sk.body, sk.sleeve, sk.accent].every((c) => SILK_COLORS.includes(c))) bad("勝負服の色は一覧から選んでください。");
    if (!SILK_PATTERNS.includes(sk.pattern)) bad("勝負服の柄は一覧から選んでください。");
    const key = nm.toLowerCase().replace(/\s+/g, "");
    const dup = this.one("SELECT user_id FROM horses WHERE name_key = ?", key);
    if (dup && dup.user_id !== uid) bad("その馬名はすでに使われています。");
    const ex = this.one("SELECT user_id FROM horses WHERE user_id = ?", uid);
    if (ex) this.run("UPDATE horses SET name = ?, name_key = ?, silks = ? WHERE user_id = ?", nm, key, JSON.stringify(sk), uid);
    else this.run("INSERT INTO horses (user_id, name, name_key, silks, created_at) VALUES (?, ?, ?, ?, ?)", uid, nm, key, JSON.stringify(sk), this.nowStr());
    return this.horse(uid);
  }
  horse(uid) {
    const h = this.one("SELECT name, silks, created_at FROM horses WHERE user_id = ?", uid);
    return h ? { name: h.name, silks: JSON.parse(h.silks), created_at: h.created_at } : null;
  }
  needHorse(uid) { const h = this.horse(uid); if (!h) bad("先に厩舎で馬を登録してください。"); return h; }

  // ---------------- 節とレース（管理） ----------------
  saveRound({ id, ym, idx, title, deadline }) {
    if (!/^\d{4}-\d{2}$/.test(ym || "")) bad("月は YYYY-MM で指定してください。");
    idx = parseInt(idx, 10);
    if (!(idx >= 1 && idx <= ROUNDS_PER_MONTH)) bad(`節は1〜${ROUNDS_PER_MONTH}で指定してください。`);
    id = id || `${ym}-${idx}`;
    if (deadline) jstMs(deadline);
    const other = this.one("SELECT id FROM rounds WHERE ym = ? AND idx = ? AND id != ?", ym, idx, id);
    if (other) bad("その月のその節はすでにあります。");
    this.run("INSERT INTO months (ym) VALUES (?) ON CONFLICT(ym) DO NOTHING", ym);
    this.run(`INSERT INTO rounds (id, ym, idx, title, deadline) VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET ym = excluded.ym, idx = excluded.idx, title = excluded.title, deadline = excluded.deadline`,
      id, ym, idx, title || `${+ym.slice(5)}月 第${idx}節`, deadline || null);
    return this.round(id);
  }
  saveRace({ id, round_id, label, post, aptitude, site_race_id, article_url, field }) {
    const rd = this.one("SELECT id FROM rounds WHERE id = ?", round_id);
    if (!rd) bad("節が見つかりません。");
    if (!APTITUDES.includes(aptitude)) bad("適性は turf_short / turf_long / dirt から選んでください。");
    jstMs(post);
    if (!label) bad("レース名を入れてください。");
    const f = (field || []).map((h) => ({ number: parseInt(h.number, 10), name: String(h.name || "").trim(), scratched: !!h.scratched }));
    if (f.length < 2) bad("出走馬を2頭以上登録してください。");
    const nums = new Set(f.map((h) => h.number));
    if (nums.size !== f.length || f.some((h) => !(h.number >= 1 && h.number <= 18) || !h.name)) bad("馬番（1〜18、重複なし）と馬名を確認してください。");
    id = id || `${round_id}-r${this.all("SELECT id FROM races WHERE round_id = ?", round_id).length + 1}`;
    const ex = this.one("SELECT round_id FROM races WHERE id = ?", id);
    if (!ex && this.all("SELECT id FROM races WHERE round_id = ?", round_id).length >= 3) bad("1節の対象レースは3本までです。");
    this.run(`INSERT INTO races (id, round_id, label, post, aptitude, site_race_id, article_url, field) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET round_id = excluded.round_id, label = excluded.label, post = excluded.post, aptitude = excluded.aptitude,
        site_race_id = excluded.site_race_id, article_url = excluded.article_url, field = excluded.field`,
      id, round_id, label, post, aptitude, site_race_id || null, article_url || null, JSON.stringify(f));
    return this.race(id);
  }
  race(id) {
    const r = this.one("SELECT * FROM races WHERE id = ?", id);
    if (!r) return null;
    return { ...r, field: JSON.parse(r.field), result: r.result ? JSON.parse(r.result) : null };
  }
  /** 節の締切：管理者が決めた値。無ければ対象レースのうち最初の発走時刻。 */
  deadlineOf(round_id) {
    const rd = this.one("SELECT deadline FROM rounds WHERE id = ?", round_id);
    if (rd && rd.deadline) return rd.deadline;
    const r = this.one("SELECT MIN(post) AS p FROM races WHERE round_id = ?", round_id);
    return r && r.p ? r.p : null;
  }
  isClosed(round_id) {
    const d = this.deadlineOf(round_id);
    return !d || this.now() >= jstMs(d);
  }
  round(id) {
    const rd = this.one("SELECT * FROM rounds WHERE id = ?", id);
    if (!rd) return null;
    const races = this.all("SELECT id FROM races WHERE round_id = ? ORDER BY post, id", id).map((r) => this.race(r.id));
    return { ...rd, deadline: this.deadlineOf(id), closed: this.isClosed(id), races };
  }
  /** 今週の節：締切前のうち最も締切が近いもの。無ければ直近に締め切った節。 */
  currentRound() {
    const rs = this.all("SELECT id FROM rounds").map((r) => ({ id: r.id, d: this.deadlineOf(r.id) })).filter((r) => r.d);
    const now = this.now();
    const open = rs.filter((r) => jstMs(r.d) > now).sort((a, b) => jstMs(a.d) - jstMs(b.d));
    if (open.length) return this.round(open[0].id);
    const past = rs.sort((a, b) => jstMs(b.d) - jstMs(a.d));
    return past.length ? this.round(past[0].id) : null;
  }

  // ---------------- 調教と出走（読者） ----------------
  levels(uid, ym, uptoIdx = ROUNDS_PER_MONTH) {
    // その月の調教回数＝レベル。月が替わると数え直す（競技用の調教値のリセット）
    const lv = { speed: 0, stamina: 0, power: 0 };
    for (const t of this.all("SELECT stat FROM trainings WHERE user_id = ? AND ym = ? AND idx <= ?", uid, ym, uptoIdx)) lv[t.stat]++;
    return lv;
  }
  train(uid, round_id, stat) {
    this.needHorse(uid);
    if (!STATS.includes(stat)) bad("調教はスピード・スタミナ・パワーから選んでください。");
    const rd = this.one("SELECT id, ym, idx FROM rounds WHERE id = ?", round_id);
    if (!rd) bad("節が見つかりません。");
    if (this.isClosed(round_id)) throw new LeagueError(409, "この節は締め切りました。調教は次の節でどうぞ。");
    if (this.one("SELECT stat FROM trainings WHERE user_id = ? AND round_id = ?", uid, round_id)) throw new LeagueError(409, "この節の調教はもう済んでいます（1節1回）。");
    this.run("INSERT INTO trainings (user_id, round_id, ym, idx, stat, created_at) VALUES (?, ?, ?, ?, ?, ?)", uid, round_id, rd.ym, rd.idx, stat, this.nowStr());
    return { stat, levels: this.levels(uid, rd.ym) };
  }
  enter(uid, round_id, race_id, number) {
    this.needHorse(uid);
    const rc = this.race(race_id);
    if (!rc || rc.round_id !== round_id) bad("この節の対象レースから選んでください。");
    if (this.isClosed(round_id)) throw new LeagueError(409, "締切を過ぎたので、出走の登録・変更はできません。");
    if (rc.status === "cancelled") bad("このレースは中止になりました。ほかの対象レースを選んでください。");
    number = parseInt(number, 10);
    const h = rc.field.find((x) => x.number === number);
    if (!h) bad("その馬番の馬はこのレースにいません。");
    if (h.scratched) bad("その馬は出走取消・除外になりました。ほかの馬を選んでください。");
    this.run(`INSERT INTO entries (user_id, round_id, race_id, number, updated_at) VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(user_id, round_id) DO UPDATE SET race_id = excluded.race_id, number = excluded.number, updated_at = excluded.updated_at`,
      uid, round_id, race_id, number, this.nowStr());
    return this.myEntry(uid, round_id);
  }
  myEntry(uid, round_id) {
    const e = this.one("SELECT race_id, number, updated_at FROM entries WHERE user_id = ? AND round_id = ?", uid, round_id);
    if (!e) return null;
    const rc = this.race(e.race_id);
    const h = rc && rc.field.find((x) => x.number === e.number);
    return { ...e, race_label: rc ? rc.label : "", horse_name: h ? h.name : "" };
  }
  /** 節の画面。締切前は自分の指名だけ、締切後は全員の指名（馬名と実在馬）を出す。 */
  roundView(uid, round_id) {
    const rd = round_id ? this.round(round_id) : this.currentRound();
    if (!rd) return { round: null };
    const out = { round: rd, now: this.nowStr() };
    if (uid) {
      out.my_training = this.one("SELECT stat FROM trainings WHERE user_id = ? AND round_id = ?", uid, rd.id);
      out.my_entry = this.myEntry(uid, rd.id);
      out.levels = this.levels(uid, rd.ym, rd.idx);
      out.my_score = this.one("SELECT * FROM scores WHERE user_id = ? AND round_id = ?", uid, rd.id);
    }
    if (rd.closed) {
      out.entries = this.all(`SELECT h.name AS horse, e.race_id, e.number, s.points, s.finish, s.note FROM entries e
        JOIN horses h ON h.user_id = e.user_id LEFT JOIN scores s ON s.user_id = e.user_id AND s.round_id = e.round_id
        WHERE e.round_id = ? ORDER BY COALESCE(s.points, -1) DESC, h.name`, rd.id);
    } else {
      out.entry_count = this.one("SELECT COUNT(*) AS n FROM entries WHERE round_id = ?", rd.id).n;
    }
    return out;
  }

  // ---------------- 結果と得点（管理） ----------------
  scratch(race_id, number, scratched = true) {
    const rc = this.race(race_id);
    if (!rc) bad("レースが見つかりません。");
    const h = rc.field.find((x) => x.number === parseInt(number, 10));
    if (!h) bad("その馬番はいません。");
    h.scratched = !!scratched;
    this.run("UPDATE races SET field = ? WHERE id = ?", JSON.stringify(rc.field), race_id);
    if (rc.status !== "scheduled") this.recomputeRound(rc.round_id);
    return this.race(race_id);
  }
  /** 確定着順の登録・訂正、または中止。何度呼んでもその節の得点は作り直すだけ。 */
  setResult(race_id, { status = "final", finishes = {} } = {}) {
    const rc = this.race(race_id);
    if (!rc) bad("レースが見つかりません。");
    if (!["final", "cancelled", "scheduled"].includes(status)) bad("status は final / cancelled / scheduled です。");
    const res = {};
    if (status === "final") {
      for (const [k, v] of Object.entries(finishes || {})) {
        const n = parseInt(k, 10);
        if (!rc.field.some((x) => x.number === n)) bad(`馬番${k}はこのレースにいません。`);
        const f = String(v).trim();
        if (!/^\d{1,2}$/.test(f) && !["取消", "除外", "中止", "失格"].includes(f)) bad(`馬番${k}の着順「${f}」が読めません。`);
        res[n] = f;
      }
      if (!Object.values(res).some((f) => f === "1")) bad("1着の馬を入れてください。");
    }
    this.run("UPDATE races SET status = ?, result = ?, result_version = result_version + 1 WHERE id = ?",
      status, status === "final" ? JSON.stringify(res) : null, race_id);
    this.recomputeRound(rc.round_id);
    return this.race(race_id);
  }
  recomputeRound(round_id) {
    const rd = this.one("SELECT id, ym, idx FROM rounds WHERE id = ?", round_id);
    if (!rd) return 0;
    this.run("DELETE FROM scores WHERE round_id = ?", round_id);
    let n = 0;
    for (const e of this.all("SELECT * FROM entries WHERE round_id = ?", round_id)) {
      const rc = this.race(e.race_id);
      if (!rc || rc.status === "scheduled") continue;
      const lv = this.levels(e.user_id, rd.ym, rd.idx);
      const stat = APT_STAT[rc.aptitude];
      const bonus = Math.min(lv[stat] * BONUS_PER_LEVEL, BONUS_MAX);
      let finish = null, base = 0, note = "";
      const h = rc.field.find((x) => x.number === e.number);
      if (rc.status === "cancelled") note = "レース中止";
      else if (h && h.scratched) note = "出走取消・除外";
      else {
        finish = rc.result ? rc.result[e.number] || null : null;
        if (finish && /^\d+$/.test(finish)) base = POINTS[parseInt(finish, 10)] || 0;
        else note = finish ? String(finish) : "着順なし";
      }
      const points = Math.round(base * (1 + (base ? bonus : 0)));
      this.run(`INSERT INTO scores (user_id, round_id, ym, race_id, number, finish, base, bonus_pct, points, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        e.user_id, round_id, rd.ym, e.race_id, e.number, finish, base, base ? Math.round(bonus * 100) : 0, points, note || null);
      n++;
    }
    return n;
  }

  // ---------------- 月間ランキング ----------------
  ranking(ym, flags = { prizes_allowed: false }) {
    const mo = this.one("SELECT * FROM months WHERE ym = ?", ym) || { ym, prize_enabled: 0, status: "open", approved: 0 };
    if (mo.status === "finalized") {
      const rows = this.all(`SELECT m.*, h.name AS horse, h.silks FROM month_results m JOIN horses h ON h.user_id = m.user_id
        WHERE m.ym = ? ORDER BY m.rank, h.name`, ym).map((r) => ({ ...r, best: JSON.parse(r.best), silks: JSON.parse(r.silks) }));
      return { ym, status: mo.status, approved: !!mo.approved, prizes: this.prizesOn(mo, flags), rows };
    }
    return { ym, status: mo.status, approved: false, prizes: this.prizesOn(mo, flags), rows: this.computeRanking(ym, this.prizesOn(mo, flags)) };
  }
  prizesOn(mo, flags) { return !!(flags && flags.prizes_allowed && mo.prize_enabled); }
  computeRanking(ym, withPrizes) {
    const by = {};
    for (const s of this.all("SELECT s.user_id, s.round_id, s.points, r.idx FROM scores s JOIN rounds r ON r.id = s.round_id WHERE s.ym = ?", ym)) {
      (by[s.user_id] = by[s.user_id] || []).push({ round_id: s.round_id, idx: s.idx, points: s.points });
    }
    const rows = Object.entries(by).map(([uid, list]) => {
      const best = [...list].sort((a, b) => b.points - a.points || a.idx - b.idx).slice(0, BEST_OF);
      const h = this.horse(uid);
      return { user_id: uid, horse: h ? h.name : "?", silks: h ? h.silks : null, total: best.reduce((a, b) => a + b.points, 0), best, rounds: list.length };
    }).sort((a, b) => b.total - a.total || a.horse.localeCompare(b.horse, "ja"));
    // 同点は同順位（1,1,3…）
    rows.forEach((r, i) => { r.rank = i && r.total === rows[i - 1].total ? rows[i - 1].rank : i + 1; });
    const prizes = splitPrizes(rows.map((r) => ({ rank: r.rank, total: r.total })));
    rows.forEach((r, i) => {
      r.title = r.total > 0 && r.rank <= 3 ? ["月間チャンピオン", "月間2位", "月間3位"][r.rank - 1] : null;
      r.prize_yen = withPrizes ? prizes[i] : 0;
    });
    return rows;
  }
  finalizeMonth(ym, flags) {
    const mo = this.one("SELECT * FROM months WHERE ym = ?", ym);
    if (!mo) bad("その月はありません。");
    const open = this.all("SELECT id FROM races r WHERE r.status = 'scheduled' AND r.round_id IN (SELECT id FROM rounds WHERE ym = ?)", ym);
    if (open.length) bad(`結果が入っていないレースがあります（${open.map((r) => r.id).join("、")}）。`);
    const rows = this.computeRanking(ym, this.prizesOn(mo, flags));
    this.run("DELETE FROM month_results WHERE ym = ?", ym);
    for (const r of rows) {
      this.run("INSERT INTO month_results (ym, user_id, rank, total, best, title, prize_yen) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ym, r.user_id, r.rank, r.total, JSON.stringify(r.best), r.title, r.prize_yen);
    }
    this.run("UPDATE months SET status = 'finalized', finalized_at = ?, approved = 0, approved_at = NULL WHERE ym = ?", this.nowStr(), ym);
    return this.ranking(ym, flags);
  }
  reopenMonth(ym) {
    this.run("UPDATE months SET status = 'open', approved = 0, approved_at = NULL WHERE ym = ?", ym);
    this.run("DELETE FROM month_results WHERE ym = ?", ym);
  }
  approveMonth(ym) {
    const mo = this.one("SELECT status FROM months WHERE ym = ?", ym);
    if (!mo || mo.status !== "finalized") bad("先に月を確定してください。");
    this.run("UPDATE months SET approved = 1, approved_at = ? WHERE ym = ?", this.nowStr(), ym);
  }
  setMonthPrize(ym, on) {
    this.run("INSERT INTO months (ym, prize_enabled) VALUES (?, ?) ON CONFLICT(ym) DO UPDATE SET prize_enabled = excluded.prize_enabled", ym, on ? 1 : 0);
  }
  months() {
    return this.all("SELECT ym, status, approved, prize_enabled FROM months ORDER BY ym DESC");
  }
  /** 自分の戦績：全節の得点と、過去月の順位。馬と戦績は月をまたいで残る。 */
  career(uid) {
    return {
      rounds: this.all(`SELECT s.*, r.title, r.ym, r.idx, rc.label AS race_label FROM scores s JOIN rounds r ON r.id = s.round_id
        LEFT JOIN races rc ON rc.id = s.race_id WHERE s.user_id = ? ORDER BY r.ym DESC, r.idx DESC`, uid),
      months: this.all("SELECT ym, rank, total, title, prize_yen FROM month_results WHERE user_id = ? ORDER BY ym DESC", uid),
    };
  }
}

/**
 * 賞品の按分：同点で同順位になった人たちは、その人たちが占める順位枠（例：1位タイ2人なら1位と2位の枠）の
 * 賞品の合計を人数で等分する（1円未満は切り捨て）。得点0の人は賞品の対象外。
 * rows は得点の高い順で、rank は同点同順位（1,1,3…）。戻り値は rows と同じ順の金額。
 */
export function splitPrizes(rows, prizes = PRIZES) {
  const out = rows.map(() => 0);
  let i = 0;
  while (i < rows.length) {
    let j = i;
    while (j + 1 < rows.length && rows[j + 1].total === rows[i].total) j++;
    if (rows[i].total > 0) {
      let pool = 0;
      for (let p = i; p <= j; p++) pool += prizes[p] || 0;
      const each = Math.floor(pool / (j - i + 1));
      for (let p = i; p <= j; p++) out[p] = each;
    }
    i = j + 1;
  }
  return out;
}
