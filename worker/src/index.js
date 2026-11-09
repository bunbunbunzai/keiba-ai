/* 「AIに質問」の裏側（Cloudflare Workers）。
 *
 * POST /ask  {page: "/2026/11/03/funabashi/01r/", q: "◎を軽視した理由は？"}
 *   → サイトが公開している /askdata/<date>/<venue>-<NN>.json（出馬表・近走・AIの予想）を読み、
 *     その情報だけを根拠に Anthropic API（Haiku）で短く答える。
 * 制限：質問200字まで、発走20分前以降は受けない、IPごとに1分5回・1日30回、サイト全体で1日600回。
 * 鍵は wrangler secret（ANTHROPIC_API_KEY）。サイトのHTMLには出ない。
 */

const JSON_HEADERS = { "content-type": "application/json; charset=utf-8" };

function cors(env, req) {
  const origin = req.headers.get("Origin") || "";
  const allow = origin === env.SITE_ORIGIN || /^http:\/\/localhost(:\d+)?$/.test(origin) ? origin : env.SITE_ORIGIN;
  return { "access-control-allow-origin": allow, "access-control-allow-methods": "POST, OPTIONS", "access-control-allow-headers": "content-type", "vary": "Origin" };
}

function reply(env, req, status, obj) {
  return new Response(JSON.stringify(obj), { status, headers: { ...JSON_HEADERS, ...cors(env, req) } });
}

function jstNow() {
  return new Date(Date.now() + 9 * 3600 * 1000); // UTC+9 を UTC として扱う
}

function ymd(d) {
  return d.toISOString().slice(0, 10).replace(/-/g, "");
}

export class Limits {
  constructor(state) {
    this.state = state;
    this.sql = state.storage.sql;
    this.sql.exec("CREATE TABLE IF NOT EXISTS c (k TEXT PRIMARY KEY, n INTEGER NOT NULL, exp INTEGER NOT NULL)");
  }
  async fetch(req) {
    const body = await req.json(); // {checks:[{k, limit, ttl}]} または {peek:k} または {add:{k, n, ttl}}
    const now = Math.floor(Date.now() / 1000);
    this.sql.exec("DELETE FROM c WHERE exp < ?", now);
    if (body.peek) {
      const row = this.sql.exec("SELECT n FROM c WHERE k = ?", body.peek).toArray()[0];
      return new Response(JSON.stringify({ n: row ? row.n : 0 }), { headers: JSON_HEADERS });
    }
    if (body.add) {
      const a = body.add;
      this.sql.exec("INSERT INTO c (k, n, exp) VALUES (?, ?, ?) ON CONFLICT(k) DO UPDATE SET n = n + ?", a.k, a.n, now + a.ttl, a.n);
      return new Response(JSON.stringify({ ok: true }), { headers: JSON_HEADERS });
    }
    const { checks } = body;
    for (const c of checks) {
      const row = this.sql.exec("SELECT n FROM c WHERE k = ?", c.k).toArray()[0];
      if (row && row.n >= c.limit) return new Response(JSON.stringify({ ok: false, k: c.k }), { headers: JSON_HEADERS });
    }
    for (const c of checks) {
      this.sql.exec("INSERT INTO c (k, n, exp) VALUES (?, 1, ?) ON CONFLICT(k) DO UPDATE SET n = n + 1", c.k, now + c.ttl);
    }
    return new Response(JSON.stringify({ ok: true }), { headers: JSON_HEADERS });
  }
}

const SYSTEM = `あなたは「競馬全頭ログ」（AIが中央・地方の全レースを予想し、外れも含めた成績を公開するサイト）の公式キャラクター「全頭くん」。レースページで読者の質問に答える。
根拠にしてよいのは、与えられた【レース情報】（出馬表・各馬の近走・AIの予想と短評）、【過去の公式レース結果】、【このサイトの過去の記録】、それに馬券の種類やルールなど競馬の一般的な知識。
使い分け：コースの傾向・人気・配当など「競馬そのもの」の質問は、レース数の多い【過去の公式レース結果】を主な根拠にする。AIの印（◎〇▲△）がどれくらい来るかなど「このサイトの予想」の質問は【このサイトの過去の記録】を使う。両方あるときは、どちらの数字かが分かるように書く。
日本語のです・ます調で、やさしく4文以内（250字以内）で答える。絵文字なし。競馬を始めたばかりの人にも分かる言葉を使い、「想定勝率×単勝」「妙味」「過剰人気」などサイト内の用語は「人気の割に勝ち目がある」「人気ほどの勝ち目はない」のように言い換える。
このサイトの◎（本命）と自信度は「補正勝率」（単勝オッズとAIの評価点を合わせて計算した勝つ確率。自信度Aは50%以上）で決めている。「AIの想定勝率」はオッズを見ないAI自身の見積もりで、◎と違う馬が1位のことがある。聞かれたら、この違いを説明する。
【過去の記録】の見出しの意味：［A］その着順の馬が何の印だったか（レース単位の割合）、［B］その印の馬1頭あたりの着順の割合、［C］券種ごとの払戻（中央値・平均・最高・1万円以上の割合）、［D］1番人気の成績、［E］勝ち馬の位置取りと枠、［F］このサイトの買い目の的中率と回収率。［A］と［B］は意味が違うので混ぜて比べない。全体・競馬場・コースの数字があるときは、レース数の多いものを中心にし、少ないものは「参考程度」と添える。
買い方の相談（例：「3連単で△を2着まで入れるべき？」「3連単の配当はどれくらい？」「このコースは前に行く馬が有利？」）には、これらの数字を示して、どちらの考え方にどんな根拠があるかを答える。フォーメーションや流しの点数は計算して示してよい。ただし「買うべき」とは言わず、決めるのは読者だと分かる言い方にする。
情報に無いことは「このレースのデータには載っていません」と答え、推測で数字や事実を作らない。
馬券の購入を勧めない、的中や利益を約束しない。競馬と無関係の質問には「このレースについての質問にお答えしています」とだけ返す。`;

// 期間限定の格上げ（BOOST_UNTIL の日まで。過ぎると自動で通常のモデル・上限に戻る）
function boosted(env) {
  return !!env.BOOST_UNTIL && new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10) <= env.BOOST_UNTIL;
}

async function askClaude(env, context, q, allowSearch) {
  const body = {
    model: boosted(env) && env.MODEL_BOOST ? env.MODEL_BOOST : (env.MODEL || "claude-haiku-5-5"),
    max_tokens: 4000,
    system: SYSTEM + (allowSearch ? SEARCH_NOTE : NO_SEARCH_NOTE),
    messages: [{ role: "user", content: `【レース情報】\n${context}\n\n【質問】${q}` }],
  };
  if (allowSearch) {
    body.tools = [{ type: "web_search_20250305", name: "web_search", max_uses: 1,
      user_location: { type: "approximate", country: "JP", timezone: "Asia/Tokyo" } }];
  }
  let j, content = [], searches = 0;
  for (let turn = 0; turn < 3; turn++) {  // サーバー側ツール（Web検索）は pause_turn で途中返しになることがある
    const r = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`api ${r.status} ${(await r.text()).slice(0, 200)}`);
    j = await r.json();
    content = content.concat(j.content || []);
    searches += (j.usage && j.usage.server_tool_use && j.usage.server_tool_use.web_search_requests) || 0;
    if (j.stop_reason !== "pause_turn") break;
    body.messages = body.messages.concat([{ role: "assistant", content: j.content }]);
  }
  const texts = content.filter((c) => c.type === "text");
  const seen = new Set();
  const sources = [];
  for (const t of texts) {
    for (const c of t.citations || []) {
      if (c.url && !seen.has(c.url) && sources.length < 3) { seen.add(c.url); sources.push({ url: c.url, title: (c.title || c.url).slice(0, 80) }); }
    }
  }
  const text = texts.map((c) => c.text).join("").trim();
  if (!text) console.log("empty answer", j.stop_reason, JSON.stringify(j.usage), content.map((c) => c.type).join(","));
  return { text, sources, searches, stop: j.stop_reason, types: content.map((c) => c.type).join(",") };
}

const SEARCH_NOTE = `
サイトのデータで答えられない一般的な情報（馬の血統や経歴、重賞の過去の傾向、騎手や馬の最近のニュースなど）が必要なときだけ、web_search を1回まで使ってよい。サイトのデータで答えられる数字は、サイトのデータを優先する。Webで調べたことは「〇〇によると」と出どころが分かるように書き、記事の文章を長く写さない。公式（JRA・地方競馬の主催者）や大手の報道を優先する。`;
const NO_SEARCH_NOTE = `
（今日はWeb検索の上限に達しているので、Webで調べる必要がある質問には「今日はこれ以上Webで調べられません。また明日どうぞ」と答える。）`;

export default {
  async fetch(req, env) {
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(env, req) });
    const url = new URL(req.url);
    if (req.method !== "POST" || url.pathname !== "/ask") return reply(env, req, 404, { error: "not found" });
    if (!env.ANTHROPIC_API_KEY) return reply(env, req, 503, { error: "この機能は準備中です。" });
    let body;
    try { body = await req.json(); } catch { return reply(env, req, 400, { error: "うまく受け取れませんでした。ページを再読み込みしてから、もう一度どうぞ。" }); }
    const page = String(body.page || "");
    const q = String(body.q || "").trim();
    const m = page.match(/^\/(\d{4})\/(\d{2})\/(\d{2})\/([a-z]+)\/(\d{2})r\/$/);
    if (!m) return reply(env, req, 400, { error: "質問はレースのページから送ってください。" });
    const maxQ = parseInt(env.MAX_Q_CHARS || "200", 10);
    if (!q || q.length > maxQ) return reply(env, req, 400, { error: `質問は${maxQ}字以内で入力してください。` });
    const date = m[1] + m[2] + m[3];
    const key = `${m[4]}-${m[5]}`;
    // レース情報（サイトが公開している静的JSON）。5分キャッシュ（DATA_VER を変えると即座に入れ替わる）
    const dataUrl = `${env.SITE_ORIGIN}/askdata/${date}/${key}.json?v=${env.DATA_VER || "1"}`;
    const cache = caches.default;
    let res = await cache.match(dataUrl);
    if (!res) {
      res = await fetch(dataUrl, { cf: { cacheTtl: 300 } });
      if (res.ok) await cache.put(dataUrl, new Response(await res.clone().text(), { headers: { "content-type": "application/json", "cache-control": "max-age=300" } }));
    }
    if (!res.ok) return reply(env, req, 404, { error: "このレースは、まだ予想が出ていないか、終わったレースのため質問できません。" });
    const data = await res.json();
    // 発走20分前を過ぎたら受け付けない（後出し防止と費用の節約）
    const now = jstNow();
    const nowKey = ymd(now) + now.toISOString().slice(11, 16).replace(":", "");
    if (data.post && nowKey >= String(data.post)) return reply(env, req, 410, { error: "発走20分前を過ぎたので、このレースの質問は受け付けていません。結果が出たら、ページの結果欄で全頭くんの振り返りが読めます。" });
    // 回数制限
    const ip = req.headers.get("CF-Connecting-IP") || "0";
    const day = ymd(now);
    const minute = nowKey;
    const id = env.LIMITS.idFromName("global");
    const lim = env.LIMITS.get(id);
    const chk = await lim.fetch("https://limits/", { method: "POST", body: JSON.stringify({ checks: [
      { k: `site:${day}`, limit: parseInt(env.LIMIT_SITE_DAY || "600", 10), ttl: 86400 },
      { k: `ip:${ip}:${day}`, limit: parseInt(env.LIMIT_IP_DAY || "30", 10), ttl: 86400 },
      { k: `ipm:${ip}:${minute}`, limit: parseInt(env.LIMIT_IP_MIN || "5", 10), ttl: 120 },
    ] }) });
    const cj = await chk.json();
    if (!cj.ok) {
      const msg = cj.k.startsWith("site:") ? "今日は質問が多く、受付を終了しました。また明日どうぞ。" : cj.k.startsWith("ipm:") ? "続けての質問が多いようです。1分ほど待ってからどうぞ。" : "今日の質問は30回までです。また明日どうぞ。";
      return reply(env, req, 429, { error: msg });
    }
    try {
      const sk = `search:${day}`;
      const used = await (await lim.fetch("https://limits/", { method: "POST", body: JSON.stringify({ peek: sk }) })).json();
      const allowSearch = used.n < parseInt((boosted(env) && env.LIMIT_SEARCH_DAY_BOOST) || env.LIMIT_SEARCH_DAY || "20", 10);
      const ans = await askClaude(env, data.context, q, allowSearch);
      if (ans.searches) await lim.fetch("https://limits/", { method: "POST", body: JSON.stringify({ add: { k: sk, n: ans.searches, ttl: 86400 } }) });
      return reply(env, req, 200, { answer: ans.text || "うまく答えられませんでした。聞き方を変えて、もう一度どうぞ。", sources: ans.sources,
        ...(ans.text ? {} : { debug: `${ans.stop}|${ans.types}` }) });
    } catch (e) {
      console.log("ask failed", String(e));
      return reply(env, req, 502, { error: "いまは答えられません。少し待ってから、もう一度どうぞ。" });
    }
  },
};
