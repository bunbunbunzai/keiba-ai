// 画面の通し確認（ローカル）：node test/ui-walkthrough.cjs <_siteのパス> <出力先>
// 前提：wrangler dev が 127.0.0.1:8787 で動いていて、test/seed-demo.mjs で架空の節が入っていること。
const { chromium, devices } = require("playwright");
const http = require("http"), fs = require("fs"), path = require("path");
const root = process.argv[2], out = process.argv[3];
const API = "http://127.0.0.1:8787", H = { "content-type": "application/json", authorization: "Bearer test-admin-token" };
const jst = (m) => new Date(Date.now() + 9 * 3600e3 + m * 60e3).toISOString().slice(0, 16);
const ym = jst(0).slice(0, 7);
const admin = async (p, b) => { const r = await fetch(API + p, { method: "POST", headers: H, body: JSON.stringify(b) }); const j = await r.json(); if (!j.ok) throw new Error(p + " " + j.error); return j.data; };
const user = async (p, b, t) => { const h = { "content-type": "application/json", "x-league-preview": "preview-123" }; if (t) h.authorization = "Bearer " + t;
  const r = await fetch(API + p, { method: b === undefined ? "GET" : "POST", headers: h, body: b === undefined ? undefined : JSON.stringify(b) }); const j = await r.json(); if (!j.ok) throw new Error(p + " " + j.error); return j.data; };
const srv = http.createServer((q, r) => { let p = decodeURIComponent(q.url.split("?")[0]); let f = path.join(root, p); if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, "index.html");
  if (!fs.existsSync(f)) { r.statusCode = 404; return r.end(); } r.setHeader("content-type", { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".png": "image/png", ".jpg": "image/jpeg" }[path.extname(f)] || "application/octet-stream"); fs.createReadStream(f).pipe(r); }).listen(8780);
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ ...devices["iPhone 13"] });
  const pg = await ctx.newPage();
  const errors = [];
  pg.on("pageerror", (e) => errors.push(String(e)));
  pg.on("dialog", (d) => d.accept());
  const shot = async (n) => { await pg.waitForTimeout(400); await pg.screenshot({ path: `${out}/lg-${n}.png`, fullPage: true }); };
  const S = "http://127.0.0.1:8780";

  await pg.goto(S + "/league/"); await pg.waitForSelector("#lg-gate:not([hidden])"); await shot("0-gate");
  await pg.fill("#pv", "preview-123"); await pg.click("#pvb"); await pg.waitForSelector("#hn");
  await pg.fill("#hn", "ゼントウドリーム");
  await pg.click('[data-k=body] button[data-c="#c0122d"]'); await pg.click('[data-k=sleeve] button[data-c="#f2c200"]'); await pg.click('[data-k=accent] button[data-c="#ffffff"]');
  await pg.selectOption("#hp", "sash"); await shot("1-create");
  await pg.click("#hs"); await pg.waitForSelector(".lg-horse .nm"); await shot("2-stable");

  // ほかの参加者（API）：同点と取消の確認用
  const others = [];
  for (const [nm, pick] of [["ライバルホース", ["demo-c", 2]], ["ミンナノアイドル", ["demo-a", 3]], ["トリケシノウマ", ["demo-a", 7]]]) {
    const t = (await user("/api/register", {})).token; await user("/api/horse", { name: nm, silks: { body: "#1d4ed8", sleeve: "#ffffff", pattern: "stripes" } }, t);
    await user("/api/enter", { round_id: `${ym}-1`, race_id: pick[0], number: pick[1] }, t); others.push(t);
  }
  await user("/api/train", { round_id: `${ym}-1`, stat: "power" }, others[0]);

  // 全頭診断からの移動（site_race で対象レースが選ばれた状態）
  await pg.goto(S + "/league/race/?site_race=demo-site-1"); await pg.waitForSelector(".lg-race"); await shot("3-race-open");
  await pg.click('[data-train="speed"]'); await pg.waitForSelector('[data-train="speed"].on');
  await pg.check('input[value="demo-a:3"]'); await pg.click("#enter"); await pg.waitForSelector(".lg-card b");
  await shot("4-entered");

  // 締切→結果（取消・訂正を含む）
  await admin("/api/admin/round", { ym, idx: 1, deadline: jst(-1) });
  await admin("/api/admin/scratch", { race_id: "demo-a", number: 7 });
  await admin("/api/admin/result", { race_id: "demo-a", finishes: { 3: "2", 5: "1", 1: "3" } });
  await admin("/api/admin/result", { race_id: "demo-a", finishes: { 3: "1", 5: "2", 1: "3" } }); // 訂正
  await admin("/api/admin/result", { race_id: "demo-b", finishes: { 1: "1", 2: "2", 3: "3" } });
  await admin("/api/admin/result", { race_id: "demo-c", finishes: { 2: "1", 1: "2", 3: "3" } });
  await pg.goto(S + "/league/race/"); await pg.waitForSelector("table"); await shot("5-race-closed");
  await pg.goto(S + "/league/ranking/"); await pg.waitForSelector(".lg-rank"); await shot("6-ranking");
  await pg.goto(S + "/league/"); await pg.waitForSelector(".lg-horse .nm"); await shot("7-stable-after");
  await pg.goto(S + "/league/rules/"); await shot("8-rules");
  const pc = await b.newContext({ viewport: { width: 1200, height: 900 } }); const ap = await pc.newPage();
  await ap.goto(S + "/league/admin/"); await ap.fill("#ad-token", "test-admin-token"); await ap.click("#ad-login"); await ap.waitForSelector("#ad-ov ul");
  await ap.screenshot({ path: `${out}/lg-9-admin.png`, fullPage: true });
  const rk = await user("/api/ranking", undefined, others[0]);
  console.log(JSON.stringify(rk.rows.map((r) => [r.rank, r.horse, r.total])));
  console.log("page errors:", errors.length ? errors : "none");
  await b.close(); srv.close();
})().catch((e) => { console.error(e); process.exit(1); });
