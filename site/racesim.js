/* レースシミュレーション（演出）。site/racesim.py がページに埋め込んだデータを読んで、
   上から見たコースに馬を走らせる。
   - 着順：AIの勝率を重みにして上の着順から順に抽選（Plackett–Luce）
   - 道中：脚質（0=前〜1=後ろ）で序盤の隊列を作り、直線の手前から最終の着順へ入れ替える
   - 1,000回の集計はレースIDから決まる乱数で計算する（見るたびに同じ数字）
   node からは計算部分だけを require できる（tests/racesim.test.js）。 */
(function () {
  'use strict';

  // ---------- 計算 ----------
  function rng(seed) { // mulberry32
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function hashStr(s) { // FNV-1a
    var h = 2166136261 >>> 0;
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return h;
  }
  // 重み ws で着順を抽選し、上位 k 頭（省略時は全頭）の添字を返す
  function plOrder(ws, rand, k) {
    var idx = ws.map(function (_, i) { return i; }), out = [];
    var lim = Math.min(k == null ? ws.length : k, ws.length);
    while (out.length < lim) {
      var tot = 0, j;
      for (j = 0; j < idx.length; j++) tot += ws[idx[j]];
      var r = rand() * tot;
      for (j = 0; j < idx.length - 1; j++) { r -= ws[idx[j]]; if (r < 0) break; }
      out.push(idx[j]); idx.splice(j, 1);
    }
    return out;
  }
  function tally(ws, n, seed) {
    var rand = rng(seed), out = ws.map(function () { return { win: 0, top3: 0 }; });
    for (var k = 0; k < n; k++) {
      var o = plOrder(ws, rand, 3);
      out[o[0]].win++;
      o.forEach(function (i) { out[i].top3++; });
    }
    return out;
  }
  function smooth(a, b, x) {
    if (x <= a) return 0;
    if (x >= b) return 1;
    var u = (x - a) / (b - a);
    return u * u * (3 - 2 * u);
  }
  // スタートの加速。時間の進み t（0〜1）を走った割合に直す。出だしはゆっくりで、t=1 でちょうど 1 になる
  var EASE_A = 0.03, EASE_K = 1 - EASE_A + EASE_A * Math.exp(-1 / EASE_A);
  function ease(t) { return t <= 0 ? 0 : (t + EASE_A * Math.exp(-t / EASE_A) - EASE_A) / EASE_K; }
  // 1回分のレースの筋書き。差の単位は馬身
  function plan(data, rand) {
    var H = data.horses, n = H.length, D = data.dist;
    var order = plOrder(H.map(function (h) { return Math.max(h.p, 0.05); }), rand);
    var f = new Array(n), g = 0;
    order.forEach(function (i, k) { if (k > 0) g += k < 3 ? 0.1 + rand() * 1.3 : 0.2 + rand() * 1.5; f[i] = g; });
    var early = H.map(function (h, i) { return { i: i, v: h.s + (rand() - 0.5) * 0.4 }; })
      .sort(function (a, b) { return a.v - b.v; });
    var e = new Array(n), eg = 0;
    early.forEach(function (o, k) { if (k > 0) eg += 0.35 + rand() * 1.3; e[o.i] = eg; });
    var home = data.straight ? Math.min(400, D * 0.4) : Math.min(data.home || 300, D * 0.6);
    return {
      order: order, D: D, home: home,
      ts: Math.max(0.3, 1 - (home + 200) / D), // ここから最終の着順へ入れ替わり始める
      r0: Math.min(0.25, 200 / D),             // ここまでに序盤の隊列ができる
      h: H.map(function (_, i) { return { e: e[i], f: f[i], a: 0.1 + rand() * 0.35, fr: 0.8 + rand() * 1.6, ph: rand() }; })
    };
  }
  // 先頭からの差（馬身）。t は先頭がゴールする時点を 1 とした進み具合
  function gapAt(h, t, P) {
    var r = smooth(0, P.rf || P.r0, t), w = smooth(P.ts, 1, t);
    var wob = h.a * Math.sin(2 * Math.PI * (t * h.fr + h.ph)) * r * (1 - w);
    return Math.max(0, (h.e * r + wob) * (1 - w) + h.f * w);
  }

  // geom / pt / sectionName は下で定義（関数宣言なのでここから参照できる）。3D の描き方（racesim3d.js）も使う
  // 序盤の隊列ができあがる時点（P.rf）。後ろの馬が下がって見えないよう、差が開く速さを先頭の速さの半分ほどまでに抑える。
  // 画面上の馬はコースに対して大きく描いているので、隊列の差を開ききるには長めの距離が要る
  function formEnd(P, g) {
    var eMax = 0;
    P.h.forEach(function (h) { if (h.e > eMax) eMax = h.e; });
    return Math.max(P.r0, Math.min(P.ts - 0.03, eMax * g.L * 3.0 / g.Dpx));
  }
  var api = { rng: rng, hashStr: hashStr, plOrder: plOrder, tally: tally, plan: plan, gapAt: gapAt, smooth: smooth, ease: ease, formEnd: formEnd,
    geom: geom, pt: pt, sectionName: sectionName };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;

  // ---------- 描画 ----------
  var FR = [null, ['#fff', '#111'], ['#222', '#fff'], ['#d33', '#fff'], ['#2a5bd7', '#fff'],
    ['#f2c200', '#111'], ['#1f8f4a', '#fff'], ['#f08a24', '#111'], ['#f4a6c6', '#111']];
  api.FR = FR;

  function cssVar(name, dflt) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || dflt;
  }
  function isDark(hex) {
    var m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
    if (!m) return false;
    var n = parseInt(m[1], 16);
    return (((n >> 16) & 255) * 0.299 + ((n >> 8) & 255) * 0.587 + (n & 255) * 0.114) < 110;
  }
  function palette(surface) {
    var panel = cssVar('--panel', '#fff'), dark = isDark(panel);
    return {
      fg: cssVar('--fg', '#17201b'), mut: cssVar('--mut', '#5f6761'), acc: cssVar('--acc', '#146b45'),
      hit: cssVar('--hit', '#c0122d'), panel: panel,
      track: surface === '芝' ? (dark ? '#2f6b3b' : '#5aa368') : (dark ? '#6e5236' : '#c9a072'),
      infield: dark ? '#1f2a21' : '#e4efdf', rail: dark ? '#d5dcd5' : '#ffffff'
    };
  }

  function geom(W, Hh, data) {
    var n = data.horses.length;
    var r = Math.max(5, Math.min(9, W / 75)), laneW = r * 1.7, m = 8;
    if (data.straight) {
      var top = m + 24, lanes = Math.max(4, Math.floor((Hh - top - m - 6) / laneW));
      var x0 = m + 18 + r, x1 = W - m - 44;
      return { straight: true, r: r, laneW: laneW, lanes: lanes, x0: x0, x1: x1, y0: top + 3 + laneW / 2,
        top: top, bot: top + lanes * laneW + 6, Dpx: x1 - x0, L: r * 1.9, W: W, H: Hh };
    }
    var ln = Math.min(6, Math.max(3, Math.ceil(n / 3)));
    var band = ln * laneW + 6, Ro = (Hh - 2 * m) / 2, Ri = Ro - band;
    var cx = W / 2, cy = Hh / 2, Ls = Math.max(40, W - 2 * m - 2 * Ro);
    var Rb = Ri + 3 + laneW / 2, P = 2 * Ls + 2 * Math.PI * Rb, scale = P / data.lap;
    var uf = Math.min(data.home * scale, Ls - 6), Dpx = data.dist * scale;
    return { straight: false, r: r, laneW: laneW, lanes: ln, cx: cx, cy: cy, Ls: Ls, Ro: Ro, Ri: Ri, Rb: Rb, P: P,
      x1: cx - Ls / 2, x2: cx + Ls / 2, uf: uf, us: uf - Dpx, Dpx: Dpx, L: r * 1.9, mir: data.dir === 'L', W: W, H: Hh };
  }
  // 楕円のコース上の点。u は「最後の直線の入口」から走る向きに測った長さ（px）、lane は内から何レーン目か
  function pt(G, u, lane) {
    if (G.straight) return [G.x0 + u, G.y0 + lane * G.laneW];
    var P = G.P, Ls = G.Ls, Rb = G.Rb, arc = Math.PI * Rb, R = Rb + lane * G.laneW, x, y, th;
    u = ((u % P) + P) % P;
    if (u < Ls) { x = G.x2 - u; y = G.cy + R; }
    else if (u < Ls + arc) { th = Math.PI / 2 + (u - Ls) / Rb; x = G.x1 + R * Math.cos(th); y = G.cy + R * Math.sin(th); }
    else if (u < 2 * Ls + arc) { x = G.x1 + (u - Ls - arc); y = G.cy - R; }
    else { th = -Math.PI / 2 + (u - 2 * Ls - arc) / Rb; x = G.x2 + R * Math.cos(th); y = G.cy + R * Math.sin(th); }
    if (G.mir) x = 2 * G.cx - x;
    return [x, y];
  }
  // 先頭の馬がいる区間の名前
  function sectionName(G, P, t, lead) {
    if (t >= 1) return 'ゴール';
    if (t < P.r0 * 0.6) return 'スタート';
    var rem = (1 - t) * P.D;
    if (G.straight) return rem <= 400 ? '残り400m' : '直線コース';
    if (rem <= P.home + 5) return '最後の直線';
    var P2 = G.P, Ls = G.Ls, arc = Math.PI * G.Rb, u = ((lead % P2) + P2) % P2;
    if (u < Ls) return 'スタンド前';
    if (u < Ls + arc) return '1〜2コーナー';
    if (u < 2 * Ls + arc) return '向正面';
    return '3〜4コーナー';
  }

  function stadium(ctx, G, R) {
    ctx.beginPath();
    ctx.moveTo(G.x1, G.cy - R); ctx.lineTo(G.x2, G.cy - R);
    ctx.arc(G.x2, G.cy, R, -Math.PI / 2, Math.PI / 2);
    ctx.lineTo(G.x1, G.cy + R);
    ctx.arc(G.x1, G.cy, R, Math.PI / 2, Math.PI * 1.5);
    ctx.closePath();
  }

  function drawTrack(ctx, G, C, data) {
    ctx.clearRect(0, 0, G.W, G.H);
    ctx.lineWidth = 2;
    if (G.straight) {
      ctx.fillStyle = C.infield; ctx.fillRect(0, 0, G.W, G.H);
      ctx.fillStyle = C.track; ctx.fillRect(G.x0 - G.r - 8, G.top, G.x1 - G.x0 + G.r + 40, G.bot - G.top);
      ctx.strokeStyle = C.rail;
      ctx.beginPath(); ctx.moveTo(G.x0 - G.r - 8, G.top); ctx.lineTo(G.x1 + 32, G.top);
      ctx.moveTo(G.x0 - G.r - 8, G.bot); ctx.lineTo(G.x1 + 32, G.bot); ctx.stroke();
      ctx.strokeStyle = C.hit; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.moveTo(G.x1, G.top); ctx.lineTo(G.x1, G.bot); ctx.stroke();
      label(ctx, 'ゴール', G.x1, G.bot + 12, C.hit, 11, 'center');
      return;
    }
    ctx.fillStyle = C.track; stadium(ctx, G, G.Ro); ctx.fill();
    ctx.fillStyle = C.infield; stadium(ctx, G, G.Ri); ctx.fill();
    ctx.strokeStyle = C.rail; stadium(ctx, G, G.Ro); ctx.stroke(); stadium(ctx, G, G.Ri); ctx.stroke();
    // ゴール板とスタート地点
    var a = pt(G, G.uf, -0.55), b = pt(G, G.uf, G.lanes - 0.45);
    ctx.strokeStyle = C.hit; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
    var gl = pt(G, G.uf, -1.6);
    label(ctx, 'ゴール', gl[0], gl[1], C.hit, 11, 'center');
    if (Math.abs(((G.us - G.uf) % G.P + G.P) % G.P) > 12) {
      var s1 = pt(G, G.us, -0.55), s2 = pt(G, G.us, G.lanes - 0.45);
      ctx.strokeStyle = C.rail; ctx.lineWidth = 2; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(s1[0], s1[1]); ctx.lineTo(s2[0], s2[1]); ctx.stroke(); ctx.setLineDash([]);
      var sl = pt(G, G.us, -1.6);
      label(ctx, 'スタート', sl[0], sl[1], C.mut, 11, 'center');
    }
  }
  function label(ctx, text, x, y, color, size, align) {
    ctx.fillStyle = color; ctx.font = '700 ' + size + 'px "BIZ UDPGothic",sans-serif';
    ctx.textAlign = align || 'left'; ctx.textBaseline = 'middle';
    ctx.fillText(text, x, y);
  }

  // ---------- 2Dの描き方 ----------
  function make2D(canvas, data, hon) {
    var ctx = canvas.getContext('2d'), G = null, dpr = 1, H = data.horses;
    return {
      kind: '2d',
      geom: function () { return G; },
      show: function (on) { canvas.style.display = on ? '' : 'none'; }, // CSS の display:block が hidden 属性より強いので style で切り替える
      resize: function () {
        var W = Math.max(280, Math.round(canvas.parentNode.clientWidth || 600));
        var Hh = data.straight ? Math.round(Math.max(150, Math.min(240, W * 0.3))) : Math.round(Math.max(200, Math.min(380, W * 0.5)));
        dpr = Math.min(2, window.devicePixelRatio || 1);
        canvas.width = Math.round(W * dpr); canvas.height = Math.round(Hh * dpr);
        canvas.style.height = Hh + 'px';
        G = geom(W, Hh, data);
      },
      draw: function (f) {
        var C = palette(data.surface);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        drawTrack(ctx, G, C, data);
        var base = G.straight ? 0 : G.us;
        var pts = f.prog.map(function (u, i) { return pt(G, base + u, Math.min(f.lane[i], G.lanes - 1)); });
        // 後ろの馬から描いて、前の馬を上に重ねる
        f.order.slice().reverse().forEach(function (i) {
          var h = H[i], c = FR[h.f] || FR[1], p = pts[i], r = G.r;
          if (i === hon) { ctx.beginPath(); ctx.arc(p[0], p[1], r + 2.6, 0, Math.PI * 2); ctx.fillStyle = C.acc; ctx.fill(); }
          ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, Math.PI * 2);
          ctx.fillStyle = c[0]; ctx.fill(); ctx.lineWidth = 1; ctx.strokeStyle = '#111'; ctx.stroke();
          ctx.fillStyle = c[1]; ctx.font = '700 ' + Math.round(r * (h.n > 9 ? 1.0 : 1.2)) + 'px sans-serif';
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(String(h.n), p[0], p[1] + 0.5);
        });
        H.forEach(function (h, i) {
          if (h.m === '◎' || h.m === '〇' || h.m === '▲') label(ctx, h.m, pts[i][0], pts[i][1] - G.r - 7, C.acc, Math.round(G.r * 1.25), 'center');
        });
        if (G.straight) {
          label(ctx, f.info, 10, 13, C.fg, 13, 'left');
          if (f.t > 0) label(ctx, f.line, G.W - 10, 13, C.mut, 12, 'right');
        } else {
          var fs = Math.max(12, Math.min(16, G.Ri / 5.5));
          label(ctx, f.info, G.cx, G.cy - fs * 0.7, C.fg, fs, 'center');
          if (f.t > 0) label(ctx, f.line, G.cx, G.cy + fs * 0.8, C.mut, Math.round(fs * 0.8), 'center');
        }
      }
    };
  }

  function webglOK() {
    try {
      var c = document.createElement('canvas');
      return !!(window.WebGLRenderingContext && (c.getContext('webgl2') || c.getContext('webgl')));
    } catch (e) { return false; }
  }

  // ---------- 1ページ分の動き（走らせる・実況・集計）。描き方は 2D/3D を差し替えられる ----------
  function init(card) {
    var data;
    try { data = JSON.parse(card.querySelector('.simdata').textContent); } catch (e) { return; }
    var H = data.horses, n = H.length;
    if (!n) return;
    var stage = card.querySelector('.rsim-stage'), canvas = stage.querySelector('canvas');
    var callEl = card.querySelector('.rsim-call'), btn = card.querySelector('.rsim-go');
    var voiceBtn = card.querySelector('.rsim-voice'), resEl = card.querySelector('.rsim-res');
    var tallyEl = card.querySelector('.rsim-tally');
    var hon = -1;
    H.forEach(function (h, i) { if (h.m === '◎') hon = i; });
    function nm(i) { return H[i].n + '番' + H[i].name; }
    function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return '&#' + c.charCodeAt(0) + ';'; }); }

    // 1,000回の集計（表は先に出しておく）
    var T = tally(H.map(function (h) { return Math.max(h.p, 0.05); }), 1000, hashStr(data.id || 'race'));
    (function () {
      var rows = H.map(function (h, i) { return { h: h, w: T[i].win, t3: T[i].top3 }; })
        .sort(function (a, b) { return b.w - a.w || b.t3 - a.t3 || a.h.n - b.h.n; });
      var maxW = Math.max(1, rows[0].w);
      function tr(x) {
        return '<tr><td><b class="fr f' + x.h.f + '">' + x.h.n + '</b></td><td class="mark">' + esc(x.h.m) + '</td><td>' + esc(x.h.name) +
          '</td><td class="n">' + x.w + '回<span class="bar" style="width:' + Math.round(x.w / maxW * 48) + 'px"></span></td><td class="n">' + x.t3 + '回</td></tr>';
      }
      var head = '<thead><tr><th>馬番</th><th>印</th><th>馬名</th><th class="n">1着</th><th class="n">3着以内</th></tr></thead>';
      var top = rows.slice(0, 5), rest = rows.slice(5);
      tallyEl.innerHTML = '<h3>1,000回走らせると</h3><p class="meta">同じ条件で1,000回走らせたときに、1着になった回数と3着以内に入った回数（AIの補正勝率をそのまま反映した数字です）。</p>' +
        '<table>' + head + '<tbody>' + top.map(tr).join('') + '</tbody></table>' +
        (rest.length ? '<details><summary>残りの' + rest.length + '頭も見る</summary><table>' + head + '<tbody>' + rest.map(tr).join('') + '</tbody></table></details>' : '');
    })();

    // 音声（ブラウザの読み上げ）
    var voice = false, synth = window.speechSynthesis;
    if (!synth || typeof SpeechSynthesisUtterance === 'undefined') voiceBtn.hidden = true;
    voiceBtn.addEventListener('click', function () {
      voice = !voice;
      voiceBtn.setAttribute('aria-pressed', voice ? 'true' : 'false');
      voiceBtn.textContent = '実況の音声：' + (voice ? 'オン' : 'オフ');
      if (!voice && synth) synth.cancel();
    });
    function say(text, important) {
      callEl.textContent = text;
      if (!voice || !synth) return;
      if (synth.speaking && !important) return;
      synth.cancel();
      var u = new SpeechSynthesisUtterance(text);
      u.lang = 'ja-JP'; u.rate = 1.15;
      synth.speak(u);
    }

    var R2 = make2D(canvas, data, hon), R = R2, R3 = null;
    var P, st = null, raf = 0, last = 0, cool = 0, coolEnd = 0;
    var Tsec = Math.max(12, Math.min(26, 10 + data.dist / 220));
    function G() { return R.geom(); }

    // ゲートの並び：楕円ではレーンの数ごとに列を分け、直線では横一列に広げる（zig は後ろへずらす量、馬の半径の何倍か）
    function fresh(rand) {
      P = plan(data, rand);
      var g = G(), L = g.lanes, straight = g.straight, lane = [], zig = [];
      P.rf = formEnd(P, g);
      H.forEach(function (_, i) {
        if (g.abreast) { lane.push(n > 1 ? -0.35 + i / (n - 1) * (L - 0.3) : 0); zig.push(0); }
        else if (straight) { lane.push(n > 1 ? i / (n - 1) * (L - 1) : 0); zig.push((i % 2) * 1.2); }
        else { lane.push(i % L); zig.push(Math.floor(i / L) * 2.3); }
      });
      return { t: 0, lane: lane, tgt: lane.map(function (v) { return Math.max(0, Math.min(L - 1, Math.round(v))); }), zig: zig,
        hold: H.map(function () { return 0; }), far: H.map(function () { return -1e9; }), fin: [], said: {}, lead: -1, leadAt: 0, clock: 0 };
    }
    function positions() {
      var g = G(), t = st.t, out = [], r = smooth(0, P.r0, t), cap = g.coast || (g.straight ? 30 : g.r * 8), lead = ease(t) * g.Dpx;
      var back = Infinity, i, u;
      for (i = 0; i < n; i++) {
        u = lead - gapAt(P.h[i], t, P) * g.L - st.zig[i] * g.r * (1 - r);
        if (u < st.far[i]) u = st.far[i]; else st.far[i] = u; // 念のため：一度進んだ位置より後ろへは戻さない
        if (u < back) back = u;
        out.push(u);
      }
      if (g.coast) {
        // 3D：最後の1頭がゴールするまでは全頭そのまま走り抜け、そのあと全体で同じだけ速さを落とす（前後の間隔は変えない）
        if (back > g.Dpx) {
          var x = back - g.Dpx, cut = x - cap * Math.log(1 + x / cap);
          for (i = 0; i < n; i++) out[i] -= cut;
        }
      } else {
        // 2D：ゴールした馬は少し先で止まる
        for (i = 0; i < n; i++) if (out[i] > g.Dpx) out[i] = g.Dpx + cap * (1 - Math.exp(-(out[i] - g.Dpx) / cap));
      }
      return out;
    }
    // 並び順：ゴールした馬はゴール順、それ以外は前にいる順
    function orderOf(prog) {
      var rest = prog.map(function (_, i) { return i; }).filter(function (i) { return st.fin.indexOf(i) < 0; })
        .sort(function (a, b) { return prog[b] - prog[a]; });
      return st.fin.concat(rest);
    }
    function assignLanes(prog, dt) {
      var g = G(), idx = prog.map(function (_, i) { return i; }).sort(function (a, b) { return prog[b] - prog[a]; });
      var placed = [], need = g.r * 2.15, maxL = g.lanes - 1;
      idx.forEach(function (i) {
        var busy = {}, wide = {};
        placed.forEach(function (q) {
          var d = Math.abs(q.u - prog[i]);
          if (d < need) busy[q.l] = 1;
          if (d < need * (g.abreast ? 1.2 : 1.7)) wide[q.l] = 1;
        });
        var cur = Math.min(maxL, st.tgt[i]), was = cur;
        st.hold[i] -= dt;
        // 楕円では内が十分に空いていれば内へ（直線は広がったまま）。動いた直後は動かない
        if (!g.straight && cur > 0 && st.hold[i] <= 0 && !wide[cur - 1]) cur -= 1;
        if (busy[cur]) {                                        // ふさがっていれば近い空きレーンへ
          var best = -1;
          for (var d = 1; d <= maxL; d++) {
            if (cur - d >= 0 && !busy[cur - d]) { best = cur - d; break; }
            if (cur + d <= maxL && !busy[cur + d]) { best = cur + d; break; }
          }
          cur = best < 0 ? Math.min(maxL, cur) : best;
        }
        if (cur !== was) st.hold[i] = g.abreast ? 0.3 : 0.9;
        st.tgt[i] = cur;
        placed.push({ u: prog[i], l: cur });
        // ゲートを出てすぐは横一列のまま走り、前後がばらけるにつれて内へ寄っていく
        var rate = g.abreast ? 2.0 * smooth(P.r0 * 0.25, P.r0 * 1.3, st.t) : 3.5;
        st.lane[i] += (cur - st.lane[i]) * Math.min(1, dt * rate);
      });
    }
    // 区間・残り距離・隊列の文字
    function hud(prog, order) {
      var g = G(), t = st.t, lead = order[0];
      var sec = sectionName(g, P, t, (g.straight ? 0 : g.us) + prog[lead]);
      var rem = Math.max(0, Math.ceil((1 - ease(t)) * data.dist / 10) * 10);
      var info = t <= 0 ? data.dist + 'm ' + (data.surface === '芝' ? '芝' : 'ダート') + (data.straight ? '・直線' : data.dir === 'L' ? '・左回り' : '・右回り')
        : sec + (t < 1 ? '　残り' + rem + 'm' : '');
      var line = '隊列 ' + order.slice(0, 8).map(function (i) { return H[i].n; }).join('-') + (n > 8 ? '…' : '');
      return { info: info, line: line, sec: sec };
    }
    function render(prog, order) {
      if (!G()) return;
      if (!st) st = fresh(rng(hashStr(data.id || 'race')));
      prog = prog || positions();
      order = order || orderOf(prog);
      var h = hud(prog, order);
      R.draw({ prog: prog, order: order, lane: st.lane, t: st.t, clock: st.clock, hon: hon, info: h.info, line: h.line,
        running: !!(raf || cool), fin: st.fin, vref: G().Dpx / Tsec, slow: raf ? (st.slow || 1) : 1,
        rem: (1 - ease(st.t)) * data.dist, home: P.home });
      return h;
    }

    function step(now) {
      var dt = Math.min(0.05, Math.max(0, (now - last) / 1000)); // タブが裏に回っても一気に進めない
      last = now;
      st.clock += dt;
      st.slow = ((1 - ease(st.t)) * data.dist < 30 && st.fin.length < Math.min(3, n)) ? 0.4 : 1;
      st.t += dt * st.slow / Tsec;
      var g = G(), prog = positions(), t = st.t, D = data.dist;
      assignLanes(prog, dt);
      // ゴールの判定（同じフレームで複数ならゴール時の差の小さい順）
      var newly = [];
      for (var i = 0; i < n; i++) if (st.fin.indexOf(i) < 0 && prog[i] >= g.Dpx) newly.push(i);
      newly.sort(function (a, b) { return P.h[a].f - P.h[b].f; }).forEach(function (i) { st.fin.push(i); });
      var order = orderOf(prog), lead = order[0];
      // 実況
      var S = st.said, rem = (1 - ease(t)) * D;
      if (!S.start) { S.start = 1; say('ゲートが開いて、' + n + '頭がいっせいにスタート！', true); }
      else if (!S.form && t >= P.r0 + 0.03 && t < P.ts) {
        S.form = 1;
        say('先頭は' + nm(order[0]) + (n > 1 ? '。2番手に' + nm(order[1]) : '') + (n > 2 ? '、3番手' + nm(order[2]) : '') + '。');
      } else if (!S.mid && S.form && t >= Math.max(P.ts - 0.08, P.r0 + 0.2) && t < P.ts + 0.05) {
        S.mid = 1;
        var sec = sectionName(g, P, t, (g.straight ? 0 : g.us) + prog[lead]);
        var hp = hon >= 0 ? order.indexOf(hon) + 1 : 0;
        say((sec === '3〜4コーナー' ? '3〜4コーナー。' : '') + '先頭は' + nm(order[0]) + (hon >= 0 ? '、AIの◎' + H[hon].n + '番は' + hp + '番手' : '') + '。');
      } else if (!S.home && rem <= P.home && t < 1) {
        S.home = 1; st.lead = lead; st.leadAt = st.clock;
        say((g.straight ? '残り400m！' : '最後の直線！') + nm(order[0]) + (n > 1 ? 'が先頭、' + nm(order[1]) + 'が追う！' : 'が先頭！'), true);
      } else if (S.home && t < 1 && lead !== st.lead && st.clock - st.leadAt > 1.3) {
        st.lead = lead; st.leadAt = st.clock;
        say(nm(lead) + 'が先頭に立った！', true);
      }
      if (st.fin.length && !S.win) { S.win = 1; say(nm(st.fin[0]) + '、1着でゴール！', true); }
      render(prog, order);
      if (st.fin.length >= n) {
        finish();
        if (R.kind === '3d') { coolEnd = st.clock + 6; cool = requestAnimationFrame(coast); }
        return;
      }
      raf = requestAnimationFrame(step);
    }

    function coast(now) {
      var dt = Math.min(0.05, Math.max(0, (now - last) / 1000));
      last = now;
      st.clock += dt;
      st.t += dt / Tsec;
      var prog = positions();
      assignLanes(prog, dt);
      cool = st.clock < coolEnd ? requestAnimationFrame(coast) : 0;
      render(prog, orderOf(prog));
    }

    function finish() {
      raf = 0;
      var o = st.fin, top = o.slice(0, 3);
      var hk = hon >= 0 ? o.indexOf(hon) + 1 : 0;
      var tail = (n > 1 ? '2着は' + nm(o[1]) : '') + (n > 2 ? '、3着は' + nm(o[2]) : '') + '。' + (hon >= 0 ? 'AIの◎' + H[hon].n + '番は' + hk + '着でした。' : '');
      setTimeout(function () { say(tail, true); }, 1200);
      var byNum = {};
      H.forEach(function (h) { byNum[h.n] = h; });
      var html = '<p><b>このシミュレーションの結果</b>　' + top.map(function (i, k) {
        return (k + 1) + '着 ' + H[i].n + ' ' + esc(H[i].name) + (H[i].m ? '（' + esc(H[i].m) + '）' : '');
      }).join('、') + '</p>' + (hon >= 0 ? '<p>AIの◎' + H[hon].n + '番は' + hk + '着</p>' : '');
      if (data.result && data.result.length) {
        html += '<p><b>実際のレースの結果</b>　' + data.result.map(function (num, k) {
          var h = byNum[num];
          return (k + 1) + '着 ' + num + (h ? ' ' + esc(h.name) : '');
        }).join('、') + '</p>';
      }
      resEl.innerHTML = html; resEl.hidden = false;
      btn.disabled = false; btn.textContent = 'もう一度走らせる';
      render();
    }

    btn.addEventListener('click', function () {
      if (raf) return;
      if (cool) { cancelAnimationFrame(cool); cool = 0; }
      if (synth) synth.cancel();
      st = fresh(rng((Math.random() * 4294967296) >>> 0));
      resEl.hidden = true;
      btn.disabled = true; btn.textContent = '走行中…';
      last = performance.now();
      raf = requestAnimationFrame(step);
    });

    function onResize() { R.resize(); if (!raf && !cool) render(); }
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(onResize).observe(stage);
    else window.addEventListener('resize', onResize);
    // 表示の明暗を切り替えたら描き直す
    document.addEventListener('click', function (e) { if (e.target && e.target.closest && e.target.closest('.theme')) setTimeout(function () { if (!raf && !cool) render(); }, 0); });
    if (window.matchMedia) {
      var mq = window.matchMedia('(prefers-color-scheme: dark)');
      if (mq.addEventListener) mq.addEventListener('change', function () { if (!raf && !cool) render(); });
    }
    R.resize();
    render();
    btn.disabled = false;

    // ---------- 重賞：3D（カードが画面に近づいたら読み込む。使えない端末は2Dのまま） ----------
    if (data.d3 && webglOK()) {
      var views = document.createElement('div');
      views.className = 'rsim-views'; views.hidden = true; views.setAttribute('role', 'group'); views.setAttribute('aria-label', '見え方');
      views.innerHTML = '<button type="button" data-v="tv">中継</button><button type="button" data-v="chase">並走</button><button type="button" data-v="top">上から</button><button type="button" data-v="2d">2D</button>';
      card.querySelector('.rsim-ctl').appendChild(views);
      var cur = 'tv';
      var use = function (v) {
        var r = v === '2d' ? R2 : R3;
        if (!r) return;
        if (r !== R) {
          R.show(false); R = r; R.show(true); R.resize();
          if (st && st.t === 0 && !raf) st = null; // 走る前ならゲートの並びを作り直す
        }
        if (v !== '2d' && R3.setView) R3.setView(v);
        cur = v;
        views.querySelectorAll('button').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.v === v ? 'true' : 'false'); });
        if (!raf && !cool) render();
      };
      views.addEventListener('click', function (e) {
        var b = e.target.closest && e.target.closest('button');
        if (b) use(b.dataset.v);
      });
      var load = function () {
        stage.classList.add('rsim-loading');
        // 古いブラウザで構文エラーにならないよう、import() は文字列から作る
        (new Function('u', 'return import(u)'))(data.d3).then(function (m) {
          return m.create(stage, data, api); // 馬のモデルの読み込みを待つ
        }).then(function (r3) {
          R3 = r3;
          R3.show(false);
          views.hidden = false;
          use('tv');
        }).catch(function () { views.remove(); }).then(function () { stage.classList.remove('rsim-loading'); });
      };
      if ('IntersectionObserver' in window) {
        var io = new IntersectionObserver(function (es) {
          if (es.some(function (x) { return x.isIntersecting; })) { io.disconnect(); load(); }
        }, { rootMargin: '300px' });
        io.observe(stage);
      } else load();
    }
  }

  function boot() { document.querySelectorAll('.rsim').forEach(init); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
