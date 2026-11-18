// node --test league/test  （「AI vs あなた」月間ランキングのルール。架空のレース・馬で確かめる）
import { test } from "node:test";
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { League, LeagueError, jstMs } from "../src/core.js";
import { Versus, judge } from "../src/versus.js";

function make(nowStr) {
  const db = new DatabaseSync(":memory:");
  const sql = { exec(q, ...b) { const st = db.prepare(q); const rows = /^\s*SELECT/i.test(q) ? st.all(...b) : (st.run(...b), []); return { toArray: () => rows }; } };
  const clock = { t: jstMs(nowStr) };
  const days = {};  // {"20261205": {path: {...}}}
  const lg = new League(sql, () => clock.t);
  const vs = new Versus(sql, () => clock.t, async (d) => days[d] || null);
  const at = (s) => { clock.t = jstMs(s); };
  const user = async (name) => { const { token } = await lg.register(); const uid = await lg.auth(token); if (name) vs.saveName(uid, name); return uid; };
  return { vs, days, at, user };
}
const P = (day, n) => `/2026/12/${day}/kakuu/${String(n).padStart(2, "0")}r/`;
const race = (post, ai = 1, n = 8) => ({ post, nums: Array.from({ length: n }, (_, i) => i + 1), ai, label: "架空レース" });
const result = (rc, order, pay, extra = {}) => ({ ...rc, fin: { ...Object.fromEntries(order.map((num, i) => [String(num), String(i + 1)])), ...extra }, win: pay ? [[order[0], pay]] : [] });
const rejects = (fn, status) => assert.rejects(fn, (e) => e instanceof LeagueError && e.status === status);

test("名前：長さ・使えない名前・重複", async () => {
  const { vs, user } = make("2026-12-01T10:00");
  const a = await user(), b = await user();
  assert.throws(() => vs.saveName(a, "あ"), LeagueError);
  assert.throws(() => vs.saveName(a, "全頭くん"), LeagueError);
  assert.throws(() => vs.saveName(a, "<b>うま</b>"), LeagueError);
  assert.equal(vs.saveName(a, "ウマスキー").name, "ウマスキー");
  assert.throws(() => vs.saveName(b, "ｳﾏｽｷｰ"), (e) => e.status === 409);  // 全角・半角の違いは同じ名前
  assert.equal(vs.saveName(a, "ウマスキー2").name, "ウマスキー2");            // 自分の名前は変えられる
});

test("◎を選ぶ：発走前だけ・出走している馬番だけ・対象レースだけ", async () => {
  const { vs, days, at, user } = make("2026-12-05T10:00");
  days["20261205"] = { [P("05", 1)]: race("202612051100") };
  const a = await user("アオゾラ"), noname = await user();
  await rejects(() => vs.pick(noname, P("05", 1), 3), 400);                 // 名前が先
  await rejects(() => vs.pick(a, P("05", 2), 3), 404);                      // 対象外のレース
  await rejects(() => vs.pick(a, "/etc/passwd", 3), 400);
  await rejects(() => vs.pick(a, P("05", 1), 9), 400);                      // いない馬番
  assert.equal((await vs.pick(a, P("05", 1), 3)).number, 3);
  at("2026-12-05T10:59"); assert.equal((await vs.pick(a, P("05", 1), 5)).number, 5);  // 発走前は変えられる
  at("2026-12-05T11:00"); await rejects(() => vs.pick(a, P("05", 1), 6), 409);         // 発走時刻ちょうどから不可
  assert.equal(vs.myPick(a, P("05", 1)).number, 5);
});

test("判定：的中・取消・払戻なし・AIとの勝敗", () => {
  const res = { ai: 2, fin: { 1: "1", 2: "3", 3: "2", 4: "取消", 5: "-" }, win: [[1, 450]] };
  assert.deepEqual({ ...judge(1, res) }, { counted: true, finish: "1", ret: 450, hit: true, vs: "win", ai: 2, ai_finish: "3" });
  assert.equal(judge(3, res).ret, 0); assert.equal(judge(3, res).vs, "win");
  assert.equal(judge(2, res).vs, "draw");
  assert.equal(judge(4, res).counted, false);   // 取消の馬は買わなかった扱い
  assert.equal(judge(5, res).counted, false);   // 着順が付かなかった馬も同じ
  assert.equal(judge(7, res).counted, false);   // 成績に載っていない馬
  assert.equal(judge(1, { ...res, win: [] }).counted, false);  // 払戻の無いレース
  assert.equal(judge(3, { ...res, ai: 4 }).vs, "win");         // AIの◎が取消なら、着順の付いたあなたの勝ち
  assert.equal(judge(1, { ...res, ai: null }).vs, null);
  const dead = { ai: 1, fin: { 1: "1", 2: "1", 3: "3" }, win: [[1, 180], [2, 260]] };  // 1着同着
  assert.equal(judge(2, dead).ret, 260); assert.equal(judge(2, dead).vs, "draw");
});

test("月間ランキング：回収率順・最少レース数・同順位・確定前は数えない", async () => {
  const { vs, days, at, user } = make("2026-12-05T09:00");
  const day = {};
  for (let i = 1; i <= 4; i++) day[P("05", i)] = race(`2026120510${i}0`, 1);
  days["20261205"] = day;
  const a = await user("アオゾラ"), b = await user("ミドリ"), c = await user("シロ"), d = await user("クロ");
  for (let i = 1; i <= 4; i++) { await vs.pick(a, P("05", i), 2); await vs.pick(b, P("05", i), 1); await vs.pick(c, P("05", i), 1); }
  await vs.pick(d, P("05", 1), 2);
  at("2026-12-05T12:00");
  let r = await vs.ranking("2026-12", a, 3);
  assert.equal(r.ranked.length, 0); assert.equal(r.me.pending, 4);            // まだ結果が無い
  // 1Rは2番が勝って600円、2〜4Rは1番（AIの◎）が勝って150円。4Rは3番が取消
  day[P("05", 1)] = result(day[P("05", 1)], [2, 1, 3, 4, 5, 6, 7, 8], 600);
  for (let i = 2; i <= 4; i++) day[P("05", i)] = result(day[P("05", i)], [1, 2, 4, 5, 6, 7, 8], 150, { 3: "取消" });
  at("2026-12-05T12:10");                                                      // 同じ日の読み直しは5分に1回
  r = await vs.ranking("2026-12", a, 3);
  const row = (n) => r.ranked.find((x) => x.name === n);
  assert.deepEqual([row("アオゾラ").roi, row("アオゾラ").hits, row("アオゾラ").n], [150, 1, 4]);       // 600/400
  assert.deepEqual([row("ミドリ").roi, row("ミドリ").hits], [112.5, 3]);                            // 450/400
  assert.deepEqual([row("アオゾラ").rank, row("ミドリ").rank, row("シロ").rank], [1, 2, 2]);         // 同じ成績は同順位
  assert.equal(row("クロ"), undefined);                                                           // 1レースだけは対象外
  assert.deepEqual([row("アオゾラ").win, row("アオゾラ").lose, row("アオゾラ").draw], [1, 3, 0]);
  assert.deepEqual([row("ミドリ").win, row("ミドリ").lose, row("ミドリ").draw], [0, 0, 4]);
  assert.equal(r.me.stats.roi, 150); assert.equal(r.me.pending, 0); assert.equal(r.beat_ai, 1);    // クロ（1勝0敗）だけがAIに勝ち越し
  assert.equal((await vs.ranking("2026-12", d, 3)).me.stats.rank, null);                           // 対象外でも自分の成績は見える
  assert.equal((await vs.ranking("2026-11", a, 3)).ranked.length, 0);                              // 別の月には入らない
  const h = vs.history(a);
  assert.equal(h.length, 4); assert.equal(h.filter((x) => x.hit).length, 1);
});

test("結果の訂正は上書きされ、二重に数えない", async () => {
  const { vs, days, at, user } = make("2026-12-06T09:00");
  days["20261206"] = { [P("06", 1)]: race("202612061000", 1) };
  const a = await user("アオゾラ");
  await vs.pick(a, P("06", 1), 2);
  at("2026-12-06T10:30");
  days["20261206"][P("06", 1)] = result(race("202612061000", 1), [2, 1, 3], 300);
  assert.equal((await vs.ranking("2026-12", a, 1)).me.stats.ret, 300);
  // 降着で1着が入れ替わった（訂正）。次に未確定の◎がある日を読み直したときではなく、同じ日のデータを読み直せば直る
  days["20261206"][P("06", 2)] = race("202612061100", 1);
  at("2026-12-06T10:40"); await vs.pick(a, P("06", 2), 1);
  days["20261206"][P("06", 1)] = result(race("202612061000", 1), [1, 2, 3], 150);
  at("2026-12-06T11:10");
  const r = await vs.ranking("2026-12", a, 1);
  assert.equal(r.me.stats.n, 1); assert.equal(r.me.stats.ret, 0); assert.equal(r.me.pending, 1);
});
