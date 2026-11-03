// ローカル確認用：架空の1節（3レース）を入れる。node test/seed-demo.mjs http://127.0.0.1:8787 test-admin-token
const B = process.argv[2] || "http://127.0.0.1:8787";
const H = { "content-type": "application/json", authorization: `Bearer ${process.argv[3] || "test-admin-token"}` };
const jst = (m) => new Date(Date.now() + 9 * 3600e3 + m * 60e3).toISOString().slice(0, 16);
const ym = jst(0).slice(0, 7);
const p = async (path, b) => {
  const r = await fetch(B + path, { method: "POST", headers: H, body: JSON.stringify(b) });
  const j = await r.json();
  if (!j.ok) throw new Error(path + " " + j.error);
  return j.data;
};
const names = ["サンプルスター", "ミライノカゼ", "アオゾラダッシュ", "ハヤテマル", "シロイツバサ", "ゴールドリボン", "ナナイロビーム", "ヨゾラノウタ", "ハルカゼライン", "ユウヒノオカ", "ミドリノキセキ", "ホシフルヨル"];
const field = (n, o = 0) => Array.from({ length: n }, (_, i) => ({ number: i + 1, name: names[(i + o) % names.length] }));
await p("/api/admin/round", { ym, idx: 1 });
await p("/api/admin/race", { id: "demo-a", round_id: `${ym}-1`, label: "架空S（芝1200m・重賞）", post: jst(120), aptitude: "turf_short", field: field(12), site_race_id: "demo-site-1" });
await p("/api/admin/race", { id: "demo-b", round_id: `${ym}-1`, label: "架空記念（芝2400m）", post: jst(150), aptitude: "turf_long", field: field(10, 3) });
await p("/api/admin/race", { id: "demo-c", round_id: `${ym}-1`, label: "架空カップ（ダート1800m）", post: jst(180), aptitude: "dirt", field: field(11, 6) });
await p("/api/admin/scratch", { race_id: "demo-a", number: 6 });
console.log("seeded", ym);
