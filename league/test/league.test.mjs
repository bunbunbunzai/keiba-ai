// node --test league/test  （架空のレース・馬で、ルールとサーバー側の検証を確かめる）
import { test } from "node:test";
import assert from "node:assert/strict";
import { DatabaseSync } from "node:sqlite";
import { League, LeagueError, splitPrizes, jstMs } from "../src/core.js";

function makeLeague(nowStr) {
  const db = new DatabaseSync(":memory:");
  const sql = { exec(q, ...b) { const st = db.prepare(q); const rows = /^\s*SELECT/i.test(q) ? st.all(...b) : (st.run(...b), []); return { toArray: () => rows }; } };
  const clock = { t: jstMs(nowStr) };
  const lg = new League(sql, () => clock.t);
  lg.at = (s) => { clock.t = jstMs(s); };
  return lg;
}
const SILKS = { body: "#146b45", sleeve: "#ffffff", pattern: "stripes" };
const FIELD = (n = 8) => Array.from({ length: n }, (_, i) => ({ number: i + 1, name: `テストホース${i + 1}` }));
const FLAGS_ON = { prizes_allowed: true };

async function newOwner(lg, name) {
  const { token } = await lg.register();
  const uid = await lg.auth(token);
  lg.saveHorse(uid, { name, silks: SILKS });
  return uid;
}
function setupMonth(lg, ym = "2026-12") {
  // 4節。各節2本（芝短距離とダート）、締切は最初の発走
  for (let i = 1; i <= 4; i++) {
    const day = String(i * 7).padStart(2, "0");
    lg.saveRound({ ym, idx: i });
    lg.saveRace({ id: `${ym}-${i}-a`, round_id: `${ym}-${i}`, label: `架空S${i}`, post: `${ym}-${day}T15:30`, aptitude: "turf_short", field: FIELD() });
    lg.saveRace({ id: `${ym}-${i}-b`, round_id: `${ym}-${i}`, label: `架空ダート${i}`, post: `${ym}-${day}T15:45`, aptitude: "dirt", field: FIELD() });
  }
}
const rejects = async (fn, status, re) => {
  try { await fn(); } catch (e) { assert.ok(e instanceof LeagueError, String(e)); if (status) assert.equal(e.status, status); if (re) assert.match(e.message, re); return; }
  assert.fail("エラーにならなかった");
};

test("登録→調教→出走→結果→得点（適性一致で加点）", async () => {
  const lg = makeLeague("2026-12-01T10:00");
  setupMonth(lg);
  const a = await newOwner(lg, "ゼントウイチバン");
  lg.train(a, "2026-12-1", "speed");
  lg.enter(a, "2026-12-1", "2026-12-1-a", 3);
  lg.at("2026-12-07T16:00");
  lg.setResult("2026-12-1-a", { finishes: { 3: "1", 5: "2", 1: "3" } });
  const s = lg.one("SELECT * FROM scores WHERE user_id = ?", a);
  assert.equal(s.base, 1000);
  assert.equal(s.bonus_pct, 5); // スピード Lv1 × 芝短距離
  assert.equal(s.points, 1050);
});

test("調教レベルは1レベル5%・最大10%、適性が違えば加点なし", async () => {
  const lg = makeLeague("2026-12-01T10:00");
  setupMonth(lg);
  const a = await newOwner(lg, "スピードキング");
  const b = await newOwner(lg, "ダートキング");
  for (const [i, t] of [[1, "2026-12-01T10:00"], [2, "2026-12-08T10:00"], [3, "2026-12-15T10:00"]]) {
    lg.at(t);
    lg.train(a, `2026-12-${i}`, "speed");
    lg.train(b, `2026-12-${i}`, "speed");
    lg.enter(a, `2026-12-${i}`, `2026-12-${i}-a`, 2);
    lg.enter(b, `2026-12-${i}`, `2026-12-${i}-b`, 2);
  }
  lg.at("2026-12-22T00:00");
  for (const i of [1, 2, 3]) { lg.setResult(`2026-12-${i}-a`, { finishes: { 2: "2", 1: "1" } }); lg.setResult(`2026-12-${i}-b`, { finishes: { 2: "2", 1: "1" } }); }
  const pa = lg.all("SELECT round_id, bonus_pct, points FROM scores WHERE user_id = ? ORDER BY round_id", a);
  assert.deepEqual(pa.map((x) => x.bonus_pct), [5, 10, 10]); // Lv1→5%、Lv2→10%、Lv3でも上限10%
  assert.deepEqual(pa.map((x) => x.points), [630, 660, 660]);
  const pb = lg.all("SELECT bonus_pct, points FROM scores WHERE user_id = ?", b);
  assert.ok(pb.every((x) => x.bonus_pct === 0 && x.points === 600)); // スピード調教でダート → 加点なし
});

test("重複：馬名、1節2回目の調教、同じ節の出走は上書き（1枠）", async () => {
  const lg = makeLeague("2026-12-01T10:00");
  setupMonth(lg);
  const a = await newOwner(lg, "オナジナマエ");
  const { token } = await lg.register();
  const b = await lg.auth(token);
  await rejects(() => lg.saveHorse(b, { name: "おなじなまえ".replace("おなじなまえ", "オナジナマエ"), silks: SILKS }), 400, /すでに/);
  lg.train(a, "2026-12-1", "power");
  await rejects(() => lg.train(a, "2026-12-1", "speed"), 409, /1節1回/);
  lg.enter(a, "2026-12-1", "2026-12-1-a", 1);
  lg.enter(a, "2026-12-1", "2026-12-1-b", 4); // 締切前の変更
  const es = lg.all("SELECT * FROM entries WHERE user_id = ?", a);
  assert.equal(es.length, 1);
  assert.equal(es[0].race_id, "2026-12-1-b");
  assert.equal(es[0].number, 4);
});

test("同じ実在馬は複数人が指名できる", async () => {
  const lg = makeLeague("2026-12-01T10:00");
  setupMonth(lg);
  const a = await newOwner(lg, "アオイホシ");
  const b = await newOwner(lg, "アカイホシ");
  lg.enter(a, "2026-12-1", "2026-12-1-a", 5);
  lg.enter(b, "2026-12-1", "2026-12-1-a", 5);
  lg.at("2026-12-07T16:00");
  lg.setResult("2026-12-1-a", { finishes: { 5: "1", 1: "2", 2: "3" } });
  assert.equal(lg.all("SELECT * FROM scores WHERE points = 1000").length, 2);
});

test("締切後は出走・変更・調教ができない（締切は最初の対象レースの発走）", async () => {
  const lg = makeLeague("2026-12-01T10:00");
  setupMonth(lg);
  const a = await newOwner(lg, "ギリギリマン");
  lg.enter(a, "2026-12-1", "2026-12-1-a", 1);
  assert.equal(lg.deadlineOf("2026-12-1"), "2026-12-07T15:30");
  lg.at("2026-12-07T15:29");
  lg.enter(a, "2026-12-1", "2026-12-1-a", 2); // 1分前は変更できる
  lg.at("2026-12-07T15:30");
  await rejects(() => lg.enter(a, "2026-12-1", "2026-12-1-b", 3), 409, /締切/);
  await rejects(() => lg.train(a, "2026-12-1", "power"), 409, /締め切り/);
  assert.equal(lg.myEntry(a, "2026-12-1").number, 2);
  // 管理者が締切を明示した場合はそれに従う
  lg.saveRound({ ym: "2026-12", idx: 2, deadline: "2026-12-14T12:00" });
  lg.at("2026-12-14T12:00");
  await rejects(() => lg.enter(a, "2026-12-2", "2026-12-2-a", 1), 409);
});

test("締切までは本人の指名だけが見え、締切後は全員分が見える", async () => {
  const lg = makeLeague("2026-12-01T10:00");
  setupMonth(lg);
  const a = await newOwner(lg, "ヒミツノウマ");
  const b = await newOwner(lg, "ノゾキミ");
  lg.enter(a, "2026-12-1", "2026-12-1-a", 7);
  const vb = lg.roundView(b, "2026-12-1");
  assert.equal(vb.my_entry, null);
  assert.equal(vb.entries, undefined);
  assert.equal(vb.entry_count, 1);
  assert.ok(!JSON.stringify(vb).includes("ヒミツノウマ"));
  lg.at("2026-12-07T15:30");
  const after = lg.roundView(b, "2026-12-1");
  assert.equal(after.entries.length, 1);
  assert.equal(after.entries[0].horse, "ヒミツノウマ");
  assert.equal(after.entries[0].number, 7);
});

test("検証：別の節のレース、いない馬番、取消馬、中止レース", async () => {
  const lg = makeLeague("2026-12-01T10:00");
  setupMonth(lg);
  const a = await newOwner(lg, "ケンショウ");
  await rejects(() => lg.enter(a, "2026-12-1", "2026-12-2-a", 1), 400, /この節/);
  await rejects(() => lg.enter(a, "2026-12-1", "2026-12-1-a", 15), 400, /馬番/);
  lg.scratch("2026-12-1-a", 3);
  await rejects(() => lg.enter(a, "2026-12-1", "2026-12-1-a", 3), 400, /取消/);
  lg.setResult("2026-12-1-b", { status: "cancelled" });
  await rejects(() => lg.enter(a, "2026-12-1", "2026-12-1-b", 1), 400, /中止/);
  await rejects(() => lg.train(a, "2026-12-1", "magic"), 400);
  const { token } = await lg.register();
  const nohorse = await lg.auth(token);
  await rejects(() => lg.enter(nohorse, "2026-12-1", "2026-12-1-a", 1), 400, /馬を登録/);
  await rejects(() => lg.auth("偽のトークン"), 401);
});

test("取消・中止・結果訂正：何度入れ直しても得点は二重にならない", async () => {
  const lg = makeLeague("2026-12-01T10:00");
  setupMonth(lg);
  const a = await newOwner(lg, "テイセイA");
  const b = await newOwner(lg, "テイセイB");
  const c = await newOwner(lg, "テイセイC");
  lg.enter(a, "2026-12-1", "2026-12-1-a", 1);
  lg.enter(b, "2026-12-1", "2026-12-1-a", 2);
  lg.enter(c, "2026-12-1", "2026-12-1-b", 1);
  lg.at("2026-12-07T16:00");
  lg.setResult("2026-12-1-a", { finishes: { 1: "1", 2: "2", 3: "3" } });
  lg.setResult("2026-12-1-a", { finishes: { 1: "1", 2: "2", 3: "3" } }); // 同じ結果をもう一度
  assert.equal(lg.all("SELECT * FROM scores WHERE round_id = '2026-12-1'").length, 2);
  assert.equal(lg.one("SELECT SUM(points) AS p FROM scores").p, 1600);
  // 訂正（1着と2着の入れ替え：降着など）
  lg.setResult("2026-12-1-a", { finishes: { 1: "2", 2: "1", 3: "3" } });
  assert.equal(lg.one("SELECT points FROM scores WHERE user_id = ?", a).points, 600);
  assert.equal(lg.one("SELECT points FROM scores WHERE user_id = ?", b).points, 1000);
  assert.equal(lg.one("SELECT SUM(points) AS p FROM scores").p, 1600);
  assert.equal(lg.race("2026-12-1-a").result_version, 3);
  // 締切後の出走取消は0点（理由つき）
  lg.scratch("2026-12-1-a", 2);
  assert.equal(lg.one("SELECT points, note FROM scores WHERE user_id = ?", b).points, 0);
  assert.equal(lg.one("SELECT note FROM scores WHERE user_id = ?", b).note, "出走取消・除外");
  // 中止レース
  lg.setResult("2026-12-1-b", { status: "cancelled" });
  const sc = lg.one("SELECT points, note FROM scores WHERE user_id = ?", c);
  assert.equal(sc.points, 0);
  assert.equal(sc.note, "レース中止");
  // 結果を入れる前の誤入力（いない馬番・1着なし）は受け付けない
  await rejects(() => lg.setResult("2026-12-1-a", { finishes: { 99: "1" } }), 400);
  await rejects(() => lg.setResult("2026-12-1-a", { finishes: { 1: "2" } }), 400, /1着/);
});

test("月間ランキングは4節のうち上位3戦の合計", async () => {
  const lg = makeLeague("2026-12-01T10:00");
  setupMonth(lg);
  const a = await newOwner(lg, "ジョウイサンセン");
  const finishes = ["1", "5", "2", "3"]; // 1000, 150, 600, 400 → 上位3戦 2000
  for (let i = 1; i <= 4; i++) {
    lg.at(`2026-12-${String(i * 7 - 1).padStart(2, "0")}T10:00`);
    lg.enter(a, `2026-12-${i}`, `2026-12-${i}-b`, 1);
  }
  lg.at("2026-12-29T00:00");
  for (let i = 1; i <= 4; i++) lg.setResult(`2026-12-${i}-b`, { finishes: { 1: finishes[i - 1], 2: "1" } });
  const rk = lg.ranking("2026-12");
  assert.equal(rk.rows[0].total, 2000);
  assert.equal(rk.rows[0].best.length, 3);
  assert.deepEqual(rk.rows[0].best.map((x) => x.points), [1000, 600, 400]);
  assert.equal(rk.rows[0].rounds, 4);
  await rejects(() => lg.saveRound({ ym: "2026-12", idx: 5 }), 400); // 1か月4節まで
});

test("同点は同順位、賞品は同順位が占める枠の合計を按分（賞品OFFなら0円）", async () => {
  assert.deepEqual(splitPrizes([{ total: 900 }, { total: 900 }, { total: 500 }]), [750, 750, 500]);
  assert.deepEqual(splitPrizes([{ total: 900 }, { total: 500 }, { total: 500 }, { total: 500 }]), [1000, 333, 333, 333]);
  assert.deepEqual(splitPrizes([{ total: 900 }, { total: 900 }, { total: 900 }, { total: 900 }]), [500, 500, 500, 500]);
  assert.deepEqual(splitPrizes([{ total: 900 }, { total: 0 }, { total: 0 }]), [1000, 0, 0]);
  assert.equal(splitPrizes([{ total: 900 }, { total: 900 }, { total: 500 }, { total: 400 }]).reduce((a, b) => a + b, 0), 2000);

  const lg = makeLeague("2026-12-01T10:00");
  setupMonth(lg);
  const ids = [];
  for (const n of ["ドウテンA", "ドウテンB", "サンイ", "ヨンイ"]) ids.push(await newOwner(lg, n));
  const picks = [1, 1, 2, 3]; // 1着・1着・2着・3着
  ids.forEach((u, i) => lg.enter(u, "2026-12-1", "2026-12-1-a", picks[i]));
  lg.at("2026-12-07T16:00");
  lg.setResult("2026-12-1-a", { finishes: { 1: "1", 2: "2", 3: "3" } });
  lg.setMonthPrize("2026-12", true);
  let rk = lg.ranking("2026-12", FLAGS_ON);
  assert.deepEqual(rk.rows.map((r) => r.rank), [1, 1, 3, 4]);
  assert.deepEqual(rk.rows.map((r) => r.prize_yen), [750, 750, 500, 0]);
  assert.deepEqual(rk.rows.map((r) => r.title), ["月間チャンピオン", "月間チャンピオン", "月間3位", null]);
  rk = lg.ranking("2026-12", { prizes_allowed: false }); // 大元のスイッチがOFF
  assert.ok(rk.rows.every((r) => r.prize_yen === 0));
  assert.equal(rk.prizes, false);
});

test("月の確定と承認、月替わりで調教値リセット、馬と戦績は翌月に残る", async () => {
  const lg = makeLeague("2026-12-01T10:00");
  setupMonth(lg, "2026-12");
  const a = await newOwner(lg, "ツキマタギ");
  lg.train(a, "2026-12-1", "stamina");
  lg.enter(a, "2026-12-1", "2026-12-1-a", 1);
  lg.at("2026-12-29T00:00");
  await rejects(() => lg.finalizeMonth("2026-12", FLAGS_ON), 400, /結果が入っていない/);
  await rejects(() => lg.approveMonth("2026-12"), 400, /先に月を確定/);
  for (let i = 1; i <= 4; i++) for (const s of ["a", "b"]) lg.setResult(`2026-12-${i}-${s}`, { finishes: { 1: "1", 2: "2" } });
  const fin = lg.finalizeMonth("2026-12", FLAGS_ON);
  assert.equal(fin.status, "finalized");
  assert.equal(fin.rows[0].horse, "ツキマタギ");
  assert.equal(fin.approved, false);
  lg.approveMonth("2026-12");
  assert.equal(lg.ranking("2026-12").approved, true);
  // 翌月
  setupMonth(lg, "2027-01");
  lg.at("2027-01-02T10:00");
  assert.deepEqual(lg.levels(a, "2027-01"), { speed: 0, stamina: 0, power: 0 });
  assert.equal(lg.levels(a, "2026-12").stamina, 1);
  assert.equal(lg.horse(a).name, "ツキマタギ");
  const car = lg.career(a);
  assert.equal(car.months[0].ym, "2026-12");
  assert.equal(car.months[0].rank, 1);
  assert.equal(lg.currentRound().id, "2027-01-1");
});

test("1節の対象レースは3本まで、適性は3種類のどれか", async () => {
  const lg = makeLeague("2026-12-01T10:00");
  setupMonth(lg);
  lg.saveRace({ round_id: "2026-12-1", label: "3本目", post: "2026-12-07T16:00", aptitude: "turf_long", field: FIELD() });
  await rejects(() => lg.saveRace({ round_id: "2026-12-1", label: "4本目", post: "2026-12-07T16:10", aptitude: "dirt", field: FIELD() }), 400, /3本/);
  await rejects(() => lg.saveRace({ round_id: "2026-12-2", label: "x", post: "2026-12-14T16:00", aptitude: "mud", field: FIELD() }), 400, /適性/);
});
