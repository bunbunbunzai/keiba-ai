// ローカルの Worker（npx wrangler dev --local）に対して、HTTP 経由で一通り確かめる。
// node test/api.e2e.mjs http://127.0.0.1:8787   （.dev.vars：ADMIN_TOKEN=test-admin-token、PREVIEW_CODE=preview-123）
import assert from "node:assert/strict";

const BASE = process.argv[2] || "http://127.0.0.1:8787";
const PV = "preview-123", ADMIN = "test-admin-token";
const jst = (minutes) => new Date(Date.now() + 9 * 3600e3 + minutes * 60e3).toISOString().slice(0, 16);
const ym = jst(0).slice(0, 7);
async function call(method, path, body, { token, pv = PV } = {}) {
  const h = { "content-type": "application/json" };
  if (token) h.authorization = `Bearer ${token}`;
  if (pv) h["x-league-preview"] = pv;
  const r = await fetch(BASE + path, { method, headers: h, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, j: await r.json() };
}
const ok = async (...a) => { const r = await call(...a); assert.equal(r.j.ok, true, `${a[1]}: ${r.j.error}`); return r.j.data; };
const ng = async (status, ...a) => { const r = await call(...a); assert.equal(r.status, status, `${a[1]} は ${status} のはず（${r.status} ${r.j.error}）`); return r.j.error; };
const log = (s) => console.log("✓", s);

// 公開前の入口と管理者の権限
await ng(403, "GET", "/api/round", null, { pv: "" });
await ng(403, "POST", "/api/admin/round", { ym, idx: 1 }, { token: "wrong" });
await ng(403, "GET", "/api/admin/overview", null, { token: "u-token" });
log("公開前はプレビューコードが必要／管理APIは管理トークンが必要");

// 管理者：節とレースを登録（締切は30分後）
const A = { token: ADMIN, pv: "" };
const rid = `${ym}-1`;
await ok("POST", "/api/admin/round", { ym, idx: 1 }, A);
const field = Array.from({ length: 10 }, (_, i) => ({ number: i + 1, name: `カクウノウマ${i + 1}` }));
await ok("POST", "/api/admin/race", { id: "e2e-a", round_id: rid, label: "架空ステークス（芝1200m）", post: jst(30), aptitude: "turf_short", field, site_race_id: "site123" }, A);
await ok("POST", "/api/admin/race", { id: "e2e-b", round_id: rid, label: "架空ダート1700m", post: jst(45), aptitude: "dirt", field }, A);
log("管理者が対象レースを登録（締切は最初の発走）");

// 読者2人
const u1 = (await ok("POST", "/api/register")).token;
const u2 = (await ok("POST", "/api/register")).token;
await ng(400, "POST", "/api/enter", { round_id: rid, race_id: "e2e-a", number: 1 }, { token: u1 });
await ok("POST", "/api/horse", { name: "イーツーイー", silks: { body: "#c0122d", sleeve: "#ffffff", pattern: "sash" } }, { token: u1 });
await ok("POST", "/api/horse", { name: "テストランナー", silks: { body: "#1d4ed8", sleeve: "#f2c200", pattern: "hoops" } }, { token: u2 });
await ng(400, "POST", "/api/horse", { name: "イーツーイー", silks: { body: "#c0122d", sleeve: "#ffffff", pattern: "sash" } }, { token: u2 });
await ng(401, "GET", "/api/me", null, { token: "nise" });
log("登録・馬名の重複・偽トークン");

await ok("POST", "/api/train", { round_id: rid, stat: "speed" }, { token: u1 });
await ng(409, "POST", "/api/train", { round_id: rid, stat: "power" }, { token: u1 });
await ok("POST", "/api/enter", { round_id: rid, race_id: "e2e-a", number: 3 }, { token: u1 });
await ok("POST", "/api/enter", { round_id: rid, race_id: "e2e-a", number: 7 }, { token: u2 });
await ng(400, "POST", "/api/enter", { round_id: rid, race_id: "e2e-a", number: 11 }, { token: u2 });
log("調教（1節1回）・出走・いない馬番");

let v2 = await ok("GET", "/api/round", null, { token: u2 });
assert.equal(v2.my_entry.number, 7);
assert.equal(v2.entries, undefined);
assert.ok(!JSON.stringify(v2).includes("イーツーイー"));
log("締切前は自分の指名だけが見える");

// 締切を過去にして締め切る
await ok("POST", "/api/admin/round", { ym, idx: 1, deadline: jst(-1) }, A);
await ng(409, "POST", "/api/enter", { round_id: rid, race_id: "e2e-b", number: 1 }, { token: u1 });
await ng(409, "POST", "/api/train", { round_id: rid, stat: "power" }, { token: u2 });
v2 = await ok("GET", "/api/round", null, { token: u2 });
assert.equal(v2.entries.length, 2);
log("締切後は変更不可・全員の指名を公開");

// 結果 → 訂正 → 同じ結果の再登録
await ok("POST", "/api/admin/result", { race_id: "e2e-a", finishes: { 3: "1", 7: "2", 1: "3" } }, A);
await ok("POST", "/api/admin/result", { race_id: "e2e-a", finishes: { 3: "2", 7: "1", 1: "3" } }, A);
await ok("POST", "/api/admin/result", { race_id: "e2e-a", finishes: { 3: "2", 7: "1", 1: "3" } }, A);
await ok("POST", "/api/admin/result", { race_id: "e2e-b", finishes: { 1: "1", 2: "2", 3: "3" } }, A);
const rk = await ok("GET", "/api/ranking", null, { token: u1 });
assert.deepEqual(rk.rows.map((r) => [r.horse, r.total]), [["テストランナー", 1000], ["イーツーイー", 630]]);
log("結果の訂正後も得点は二重にならない（1000 / 600×1.05=630）");

// 月の確定と承認（賞品は大元のスイッチがOFFなので0円）
await ng(403, "POST", "/api/admin/finalize", { ym }, { token: u1 });
await ok("POST", "/api/admin/month_prize", { ym, on: true }, A);
const fin = await ok("POST", "/api/admin/finalize", { ym }, A);
assert.equal(fin.status, "finalized");
assert.ok(fin.rows.every((r) => r.prize_yen === 0));
await ok("POST", "/api/admin/approve", { ym }, A);
const me = await ok("GET", "/api/me", null, { token: u2 });
assert.equal(me.career.months[0].rank, 1);
assert.equal(me.career.months[0].title, "月間チャンピオン");
log("月の確定・承認、戦績に月の順位と称号が残る（賞品は無効のまま）");
console.log("all e2e checks passed");
