// 「AI vs あなた」月間ランキングの画面の通し確認（ローカル）：node test/vs-walkthrough.cjs <_siteのパス> <出力先> <レースページのパス>
// 前提：.dev.vars に ADMIN_TOKEN / PREVIEW_CODE=preview-123 / VS_DATA_ORIGIN=http://127.0.0.1:8780 / VS_MIN_PICKS=1 を書き、
//       wrangler dev が 127.0.0.1:8787 で動いていること。_site は LEAGUE_URL=http://127.0.0.1:8787 で作ったもの。
// レースページは発走前のものを指定する。発走時刻だけを「1分後」に差し替えた対戦データを配り、結果が入るところまで確かめる。
const { chromium, devices } = require("playwright");
const http = require("http"), fs = require("fs"), path = require("path");
const [root, out, racePath] = process.argv.slice(2);
const API = "http://127.0.0.1:8787", S = "http://127.0.0.1:8780";
const key = (m) => new Date(Date.now() + 9 * 3600e3 + m * 60e3).toISOString().slice(0, 16).replace(/[-T:]/g, "");
const date = racePath.split("/").slice(1, 4).join("");
const day = JSON.parse(fs.readFileSync(path.join(root, "vsgame", date + ".json"), "utf8"));
const rc = day[racePath]; if (!rc) throw new Error("対戦データにこのレースが無い: " + racePath);
rc.post = key(1);
const srv = http.createServer((q, r) => { let p = decodeURIComponent(q.url.split("?")[0]);
  if (p === `/vsgame/${date}.json`) { r.writeHead(200, { "content-type": "application/json" }); return r.end(JSON.stringify(day)); }
  let f = path.join(root, p); if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, "index.html");
  if (!fs.existsSync(f)) { r.writeHead(404); return r.end("nf"); }
  r.writeHead(200, { "content-type": ({ ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp" })[path.extname(f)] || "application/octet-stream" });
  fs.createReadStream(f).pipe(r); }).listen(8780);
const user = async (m, p, b, t) => { const h = { "content-type": "application/json", "x-league-preview": "preview-123" }; if (t) h.authorization = "Bearer " + t;
  const r = await fetch(API + p, { method: m, headers: h, body: b ? JSON.stringify(b) : undefined }); const j = await r.json(); if (!j.ok) throw new Error(p + " " + j.error); return j.data; };
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ ...devices["iPhone 13"] });
  await ctx.route(/google|doubleclick|gstatic/, (r) => r.abort());
  const pg = await ctx.newPage(); const errors = [];
  pg.on("pageerror", (e) => errors.push(String(e)));
  const shot = async (n) => { await pg.waitForTimeout(500); await pg.screenshot({ path: `${out}/vs-${n}.png`, fullPage: n !== "2-race" }); };
  const sfx = String(Date.now()).slice(-5);
  // 公開前：コードを入れていない人には、レースページに何も足されない
  await pg.goto(S + racePath); await pg.waitForTimeout(600);
  if (await pg.locator(".vs-sv").count()) throw new Error("コード無しなのにランキングの案内が出ている");
  // 入口 → コード → 名前
  await pg.goto(S + "/vs/"); await pg.waitForSelector("#vs-app input"); await shot("0-gate");
  await pg.fill("#vs-app input", "wrong"); await pg.click("#vs-app button"); await pg.waitForSelector("#vs-app .vs-msg:not(:empty)");
  await pg.fill("#vs-app input", "preview-123"); await pg.click("#vs-app button"); await pg.waitForSelector("#vs-app .vs-rank"); await shot("1-join");
  await pg.fill("#vs-app input[maxlength]", "アオゾラ" + sfx); await pg.click("#vs-app .vs-form button"); await pg.waitForSelector("#vs-app .vs-btn");
  // レースページで◎を選ぶ → 記録される
  await pg.goto(S + racePath); await pg.waitForSelector(".vs .vs-sv");
  const mine = rc.nums.find((n) => n !== rc.ai);
  await pg.selectOption(".vs select", String(mine)); await pg.click(".vs .go"); await pg.waitForFunction(() => /記録しました/.test(document.querySelector(".vs .vs-sv").textContent));
  await pg.locator(".vs").scrollIntoViewIfNeeded(); await shot("2-race");
  // ほかの参加者（API）：AIと同じ◎
  const t = (await user("POST", "/api/register", {})).token; await user("POST", "/api/vs/name", { name: "ミドリ" + sfx }, t); await user("POST", "/api/vs/pick", { path: racePath, number: rc.ai }, t);
  // 結果待ちの表示 → 発走を過ぎたら変更不可 → 結果が入る（あなたの◎が1着・単勝1,280円）
  await pg.goto(S + "/vs/"); await pg.waitForSelector("#vs-app .vs-rank"); await shot("3-pending");
  await new Promise((r) => setTimeout(r, 65000));
  let late = ""; try { await user("POST", "/api/vs/pick", { path: racePath, number: rc.ai }, await pg.evaluate(() => localStorage.getItem("vs_token"))); } catch (e) { late = String(e.message); }
  if (!/発走時刻を過ぎた/.test(late)) throw new Error("発走後なのに変更できた: " + late);
  const order = [mine, rc.ai, ...rc.nums.filter((n) => n !== mine && n !== rc.ai)];
  rc.fin = Object.fromEntries(order.map((n, i) => [String(n), String(i + 1)])); rc.win = [[mine, 1280]];
  await pg.goto(S + "/vs/"); await pg.waitForSelector("#vs-app .vs-rank tbody tr.me"); await shot("4-ranking");
  const rows = await pg.$$eval("#vs-app .vs-rank tbody tr", (trs) => trs.map((tr) => [...tr.children].map((td) => td.textContent)));
  const me = rows.find((r) => r[1].startsWith("アオゾラ")), ot = rows.find((r) => r[1].startsWith("ミドリ"));
  console.log(JSON.stringify(rows));
  if (!me || me[2] !== "1280.0%" || me[3] !== "1／1" || me[4] !== "1勝0敗") throw new Error("自分の行が想定と違う");
  if (!ot || ot[2] !== "0.0%" || ot[4] !== "0勝0敗1分") throw new Error("相手の行が想定と違う");
  console.log("page errors:", errors.length ? errors : "none");
  await b.close(); srv.close();
  if (errors.length) process.exit(1);
})().catch((e) => { console.error(e); process.exit(1); });
