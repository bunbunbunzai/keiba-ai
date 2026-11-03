/* 全頭ログ オーナーズリーグの API（Cloudflare Workers + Durable Object の SQLite）。
 * 「全頭くんに質問」の Worker とは別の Worker・別の DB で動く（既存機能に影響しない）。
 *
 * 認証：読者は登録時に発行するトークン（ブラウザに保存）。管理者は ADMIN_TOKEN（wrangler secret）。
 * 一般公開前（LEAGUE_PUBLIC が "1" でない間）は、PREVIEW_CODE を知っている人と管理者だけが使える。
 */
import { League, LeagueError } from "./core.js";

const JSON_HEADERS = { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" };

function cors(env, req) {
  const origin = req.headers.get("Origin") || "";
  const ok = origin === env.SITE_ORIGIN || /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin);
  return {
    "access-control-allow-origin": ok ? origin : env.SITE_ORIGIN,
    "access-control-allow-methods": "GET, POST, OPTIONS",
    "access-control-allow-headers": "content-type, authorization, x-league-preview",
    "vary": "Origin",
  };
}

export class LeagueDO {
  constructor(state, env) {
    this.env = env;
    this.lg = new League(state.storage.sql);
  }
  async fetch(req) {
    const { op, args, token, admin, ip } = await req.json();
    const lg = this.lg;
    const env = this.env;
    try {
      const flags = lg.flags(env);
      const uid = async () => lg.auth(token);
      let out;
      switch (op) {
        // 読者
        case "register": out = await lg.register(ip ? `ip:${ip}` : ""); break;
        case "me": {
          const u = await uid();
          const cur = lg.currentRound();
          out = { user_id: u, horse: lg.horse(u), levels: cur ? lg.levels(u, cur.ym) : null, career: lg.career(u), flags };
          break;
        }
        case "horse": out = lg.saveHorse(await uid(), args); break;
        case "round": out = lg.roundView(token ? await uid().catch(() => null) : null, args.round_id); break;
        case "train": out = lg.train(await uid(), args.round_id, args.stat); break;
        case "enter": out = lg.enter(await uid(), args.round_id, args.race_id, args.number); break;
        case "ranking": {
          const ym = args.ym || (lg.currentRound() || {}).ym || new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 7);
          out = { ...lg.ranking(ym, flags), months: lg.months(), flags };
          if (token) { try { out.me = await uid(); } catch { /* 未登録 */ } }
          break;
        }
        // 管理
        default: {
          if (!admin) throw new LeagueError(403, "管理者のみの操作です。");
          switch (op) {
            case "admin.overview": out = { flags, settings: { public: lg.setting("public"), prizes_allowed: lg.setting("prizes_allowed") }, months: lg.months(),
              rounds: lg.all("SELECT id FROM rounds ORDER BY ym DESC, idx DESC").map((r) => lg.round(r.id)),
              users: lg.one("SELECT COUNT(*) AS n FROM users").n, horses: lg.one("SELECT COUNT(*) AS n FROM horses").n }; break;
            case "admin.round": out = lg.saveRound(args); break;
            case "admin.race": out = lg.saveRace(args); break;
            case "admin.scratch": out = lg.scratch(args.race_id, args.number, args.scratched !== false); break;
            case "admin.result": out = lg.setResult(args.race_id, args); break;
            case "admin.finalize": out = lg.finalizeMonth(args.ym, flags); break;
            case "admin.reopen": lg.reopenMonth(args.ym); out = { ok: true }; break;
            case "admin.approve": lg.approveMonth(args.ym); out = lg.ranking(args.ym, flags); break;
            case "admin.month_prize": lg.setMonthPrize(args.ym, !!args.on); out = lg.months(); break;
            case "admin.settings":
              if (args.public !== undefined) lg.setSetting("public", args.public ? "1" : "0");
              if (args.prizes_allowed !== undefined) lg.setSetting("prizes_allowed", args.prizes_allowed ? "1" : "0");
              out = { flags: lg.flags(env) }; break;
            default: throw new LeagueError(404, "不明な操作です。");
          }
        }
      }
      return new Response(JSON.stringify({ ok: true, data: out }), { headers: JSON_HEADERS });
    } catch (e) {
      const status = e instanceof LeagueError ? e.status : 500;
      if (status === 500) console.log("league error", String(e && e.stack || e));
      return new Response(JSON.stringify({ ok: false, error: status === 500 ? "サーバーでエラーが起きました。時間をおいてからどうぞ。" : e.message }),
        { status, headers: JSON_HEADERS });
    }
  }
}

// API の経路 → DO の操作
const ROUTES = {
  "POST /api/register": "register", "GET /api/me": "me", "POST /api/horse": "horse", "GET /api/round": "round",
  "POST /api/train": "train", "POST /api/enter": "enter", "GET /api/ranking": "ranking",
  "GET /api/admin/overview": "admin.overview", "POST /api/admin/round": "admin.round", "POST /api/admin/race": "admin.race",
  "POST /api/admin/scratch": "admin.scratch", "POST /api/admin/result": "admin.result", "POST /api/admin/finalize": "admin.finalize",
  "POST /api/admin/reopen": "admin.reopen", "POST /api/admin/approve": "admin.approve", "POST /api/admin/month_prize": "admin.month_prize",
  "POST /api/admin/settings": "admin.settings",
};

function safeEqual(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

export default {
  async fetch(req, env) {
    const h = cors(env, req);
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: h });
    const url = new URL(req.url);
    const op = ROUTES[`${req.method} ${url.pathname}`];
    const reply = (status, obj) => new Response(JSON.stringify(obj), { status, headers: { ...JSON_HEADERS, ...h } });
    if (!op) return reply(404, { ok: false, error: "not found" });
    const bearer = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
    const admin = safeEqual(bearer, env.ADMIN_TOKEN || "");
    if (op.startsWith("admin.") && !admin) return reply(403, { ok: false, error: "管理者のみの操作です。" });
    // 一般公開前は、プレビューコードを知っている人と管理者だけ
    const pv = req.headers.get("x-league-preview") || "";
    const isPublic = env.LEAGUE_PUBLIC === "1";
    if (!isPublic && !admin && !safeEqual(pv, env.PREVIEW_CODE || "")) {
      return reply(403, { ok: false, error: "オーナーズリーグは準備中です（関係者プレビューのみ）。", preview_required: true });
    }
    let args = {};
    if (req.method === "POST") {
      const raw = await req.text();
      try { args = raw.trim() ? JSON.parse(raw) : {}; } catch { return reply(400, { ok: false, error: "形式が正しくありません。" }); }
      if (!args || typeof args !== "object" || Array.isArray(args)) return reply(400, { ok: false, error: "形式が正しくありません。" });
    } else {
      args = Object.fromEntries(url.searchParams);
    }
    const token = admin ? "" : bearer;
    const stub = env.LEAGUE.get(env.LEAGUE.idFromName("league"));
    const res = await stub.fetch("https://league/", { method: "POST",
      body: JSON.stringify({ op, args, token, admin, ip: req.headers.get("CF-Connecting-IP") || "" }) });
    return new Response(res.body, { status: res.status, headers: { ...JSON_HEADERS, ...h } });
  },
};
