/* レースシミュレーションの3D表示（重賞のページだけ）。
   着順・実況・集計は racesim.js が行い、ここは毎フレーム渡される位置を3Dで描くだけ。
   コースの形は 2D と同じ計算（api.geom / api.pt）を 1200×600 の固定の大きさで使い、
   その座標をそのまま地面（x, z）に置く。

   ビルド（three.js から使う部分だけを1ファイルにまとめる）:
     cd site/3d && npm ci && npm run build   → site/racesim3d.js
*/
import {
  WebGLRenderer, Scene, PerspectiveCamera, Color, Fog, HemisphereLight, DirectionalLight,
  Mesh, MeshLambertMaterial, MeshBasicMaterial, Shape, Path, ShapeGeometry, BoxGeometry,
  CylinderGeometry, SphereGeometry, CapsuleGeometry, PlaneGeometry, CircleGeometry, ConeGeometry,
  Group, CanvasTexture, Sprite, SpriteMaterial, Vector3, InstancedMesh, Object3D, DoubleSide,
  TubeGeometry, CatmullRomCurve3, SRGBColorSpace
} from 'three';

const COATS = ['#7a4520', '#8f4f1f', '#4a2c17', '#2b1d14', '#5c3218', '#9b9a94']; // 鹿毛・栗毛・黒鹿毛・青鹿毛・栃栗毛・芦毛
const SILKS = ['#1e4fa8', '#c8102e', '#f2c200', '#1f8f4a', '#7a2c8f', '#f08a24', '#111111', '#e6e6e6', '#0f8fa6', '#b5651d', '#d14f8f', '#3d5a1f'];

export function create(stage, data, api) {
  const H = data.horses, n = H.length;
  const G = data.straight ? api.geom(1200, 320, data) : api.geom(1200, 600, data);
  const base = G.straight ? 0 : G.us;
  const W2 = G.W / 2, H2 = G.H / 2;
  const tmp = new Vector3(), tmp2 = new Vector3();
  function P3(u, lane, out) {
    const p = api.pt(G, base + u, lane);
    return (out || new Vector3()).set(p[0] - W2, 0, p[1] - H2);
  }

  // ---------- 描画の土台 ----------
  const canvas = document.createElement('canvas');
  canvas.className = 'rsim-3d';
  const renderer = new WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
  renderer.outputColorSpace = SRGBColorSpace;
  const scene = new Scene();
  const sky = new Color('#a8cbe8');
  scene.background = sky;
  scene.fog = new Fog(sky, 1100, 3200);
  const camera = new PerspectiveCamera(38, 16 / 9, 2, 6000);
  scene.add(new HemisphereLight('#e8f3ff', '#4f6b3a', 1.6));
  const sun = new DirectionalLight('#ffffff', 2.2);
  sun.position.set(400, 700, 300);
  scene.add(sun);

  const hud = document.createElement('div');
  hud.className = 'rsim-hud';
  hud.innerHTML = '<span class="i"></span><span class="l"></span>';
  const hudI = hud.querySelector('.i'), hudL = hud.querySelector('.l');
  stage.appendChild(canvas);
  stage.appendChild(hud);

  const lam = (c, extra) => new MeshLambertMaterial(Object.assign({ color: new Color(c) }, extra || {}));
  const flat = (geo) => { geo.rotateX(-Math.PI / 2); return geo; };

  // ---------- 地面・コース ----------
  const ground = new Mesh(flat(new PlaneGeometry(6000, 6000)), lam('#6f9f5c'));
  ground.position.y = -0.2;
  scene.add(ground);
  const turf = data.surface === '芝';
  const trackMat = lam(turf ? '#4f9a4c' : '#b98957', { side: DoubleSide });
  const infieldMat = lam('#86b56f', { side: DoubleSide });
  const railMat = lam('#ffffff');

  function stadiumPts(R, seg) {
    const pts = [], { x1, x2, cy, Ls } = G;
    const sx = (x) => x - W2, sz = (y) => y - H2;
    const steps = Math.max(2, Math.round(Ls / 40));
    for (let k = 0; k <= steps; k++) pts.push([sx(x2 - Ls * k / steps), sz(cy + R)]);
    for (let k = 1; k < seg; k++) { const th = Math.PI / 2 + Math.PI * k / seg; pts.push([sx(x1 + R * Math.cos(th)), sz(cy + R * Math.sin(th))]); }
    for (let k = 0; k <= steps; k++) pts.push([sx(x1 + Ls * k / steps), sz(cy - R)]);
    for (let k = 1; k < seg; k++) { const th = -Math.PI / 2 + Math.PI * k / seg; pts.push([sx(x2 + R * Math.cos(th)), sz(cy + R * Math.sin(th))]); }
    return pts;
  }
  function shapeOf(pts, holePts) {
    // ShapeGeometry は XY 平面。x→x、y→-z として作り、あとで X 軸まわりに -90° 回して地面に寝かせる
    const s = new Shape(pts.map(([x, z]) => ({ x, y: -z })));
    if (holePts) s.holes.push(new Path(holePts.map(([x, z]) => ({ x, y: -z }))));
    return flat(new ShapeGeometry(s));
  }
  function railAlong(pts, y) {
    const curve = new CatmullRomCurve3(pts.map(([x, z]) => new Vector3(x, y, z)), true, 'catmullrom', 0.05);
    scene.add(new Mesh(new TubeGeometry(curve, Math.min(600, pts.length * 3), 0.5, 5, true), railMat));
    return curve;
  }
  function posts(curve, every) {
    const len = curve.getLength(), cnt = Math.floor(len / every);
    const im = new InstancedMesh(new CylinderGeometry(0.35, 0.35, 3.2, 5), railMat, cnt);
    const o = new Object3D();
    for (let k = 0; k < cnt; k++) {
      const p = curve.getPointAt(k / cnt);
      o.position.set(p.x, 1.6, p.z); o.updateMatrix(); im.setMatrixAt(k, o.matrix);
    }
    scene.add(im);
  }

  if (G.straight) {
    const x0 = G.x0 - W2 - 30, x1 = G.x1 - W2 + 60, z0 = G.top - H2, z1 = G.bot - H2;
    const t = new Mesh(flat(new PlaneGeometry(x1 - x0, z1 - z0)), trackMat);
    t.position.set((x0 + x1) / 2, 0.05, (z0 + z1) / 2);
    scene.add(t);
    for (const z of [z0 - 0.5, z1 + 0.5]) {
      const pts = [];
      for (let x = x0; x <= x1; x += 40) pts.push(new Vector3(x, 3.2, z));
      const curve = new CatmullRomCurve3(pts);
      scene.add(new Mesh(new TubeGeometry(curve, 60, 0.5, 5, false), railMat));
      posts(curve, 25);
    }
  } else {
    const outer = stadiumPts(G.Ro, 48), inner = stadiumPts(G.Ri, 48);
    const tr = new Mesh(shapeOf(outer, inner), trackMat); tr.position.y = 0.05; scene.add(tr);
    const inf = new Mesh(shapeOf(inner), infieldMat); inf.position.y = 0.03; scene.add(inf);
    posts(railAlong(stadiumPts(G.Ri - 0.5, 48), 3.2), 24);
    posts(railAlong(stadiumPts(G.Ro + 0.5, 48), 3.2), 24);
    // スタンド（最後の直線の外側）
    const standMat = lam('#c9cdd2'), roofMat = lam('#7f8790'), seatMat = lam('#5d7fa8');
    const zs = G.cy + G.Ro - H2, len = G.Ls * 0.85;
    [[26, 8, 16], [40, 16, 14], [52, 24, 12]].forEach(([dz, h, d], k) => {
      const b = new Mesh(new BoxGeometry(len, h, d), k === 1 ? seatMat : standMat);
      b.position.set(0, h / 2, zs + dz); scene.add(b);
    });
    const roof = new Mesh(new BoxGeometry(len * 1.02, 1.5, 34), roofMat);
    roof.position.set(0, 38, zs + 44); roof.rotation.x = -0.12; scene.add(roof);
    // 内馬場の大型ビジョン
    const vis = new Mesh(new BoxGeometry(110, 34, 3), lam('#20262b'));
    vis.position.set(0, 26, G.cy - G.Ri * 0.1 - H2); scene.add(vis);
    const visLeg = new Mesh(new BoxGeometry(6, 10, 3), lam('#59616a'));
    visLeg.position.set(0, 5, vis.position.z); scene.add(visLeg);
  }

  // ゴール板とゴールの線（ゴールは走った長さが G.Dpx の地点）
  {
    const a = P3(G.Dpx, -0.6), b = P3(G.Dpx, G.lanes - 0.3);
    const line = new Mesh(new BoxGeometry(a.distanceTo(b), 0.15, 1.4), new MeshBasicMaterial({ color: '#ffffff' }));
    line.position.copy(a).add(b).multiplyScalar(0.5); line.position.y = 0.12;
    line.rotation.y = -Math.atan2(b.z - a.z, b.x - a.x);
    scene.add(line);
    const side = P3(G.Dpx, -1.1), out = P3(G.Dpx, G.lanes + 4);
    const pole = new Mesh(new CylinderGeometry(0.7, 0.7, 24, 8), lam('#d32f2f'));
    pole.position.set(side.x, 12, side.z); scene.add(pole);
    const board = new Mesh(new CylinderGeometry(5, 5, 1, 20).rotateX(Math.PI / 2), lam('#ffffff'));
    board.position.set(side.x, 25, side.z); board.lookAt(out.x, 25, out.z); scene.add(board); // スタンドの側を向ける
  }
  // スタートのゲート（スタートとゴールが同じ場所でなければ）
  if (G.straight || Math.abs(((G.us - G.uf) % G.P + G.P) % G.P) > 20) {
    const a = P3(0, -0.6), b = P3(0, G.lanes - 0.3), len = a.distanceTo(b);
    const gate = new Group(), gm = lam('#d8dde2');
    const beam = new Mesh(new BoxGeometry(2, 2, len), gm); beam.position.y = 13; gate.add(beam);
    for (const s of [-1, 1]) { const tw = new Mesh(new BoxGeometry(3, 14, 3), gm); tw.position.set(0, 7, s * len / 2); gate.add(tw); }
    const fwd = P3(0, G.lanes / 2).sub(P3(-6, G.lanes / 2)).normalize().multiplyScalar(4); // ゲートは馬の少し前
    gate.position.copy(a).add(b).multiplyScalar(0.5).add(fwd);
    gate.lookAt(b.x + fwd.x, 0, b.z + fwd.z); // 梁（ローカルの z 方向）をコースの幅の向きに
    scene.add(gate);
  }
  // 木（コースの外に散らす）
  {
    const rand = api.rng(api.hashStr((data.id || '') + 'trees'));
    const cnt = 70, trunk = new InstancedMesh(new CylinderGeometry(1.2, 1.6, 8, 5), lam('#6b4a2f'), cnt);
    const leaf = new InstancedMesh(new ConeGeometry(9, 26, 7), lam('#3f6f3a'), cnt);
    const o = new Object3D();
    let k = 0, guard = 0;
    while (k < cnt && guard++ < 2000) {
      const x = (rand() - 0.5) * 1700, z = (rand() - 0.5) * 1100;
      const nx = Math.abs(x) - G.Ls / 2, inside = G.straight
        ? Math.abs(z - ((G.top + G.bot) / 2 - H2)) < (G.bot - G.top) / 2 + 60
        : Math.hypot(Math.max(0, nx), z - (G.cy - H2)) < G.Ro + 50;
      const stand = !G.straight && Math.abs(x) < G.Ls * 0.5 && z > G.cy + G.Ro - H2 && z < G.cy + G.Ro - H2 + 90;
      if (inside || stand) continue;
      const s = 0.7 + rand() * 0.7;
      o.position.set(x, 4 * s, z); o.scale.set(s, s, s); o.updateMatrix(); trunk.setMatrixAt(k, o.matrix);
      o.position.set(x, (8 + 13) * s, z); o.updateMatrix(); leaf.setMatrixAt(k, o.matrix);
      k++;
    }
    trunk.count = leaf.count = k;
    scene.add(trunk, leaf);
  }

  // ---------- 馬 ----------
  const geo = {
    body: new CapsuleGeometry(3.0, 8.5, 4, 10).rotateZ(Math.PI / 2),
    neck: new CylinderGeometry(1.3, 2.1, 6.8, 8),
    head: new CapsuleGeometry(1.05, 3.6, 3, 8).rotateZ(Math.PI / 2),
    leg: new CylinderGeometry(0.6, 0.42, 7.6, 6).translate(0, -3.8, 0),
    tail: new CylinderGeometry(0.3, 1.0, 6.5, 6).translate(0, -3.25, 0),
    cloth: new BoxGeometry(5.6, 3.4, 6.3),
    torso: new BoxGeometry(2.6, 3.8, 2.6),
    helmet: new SphereGeometry(1.35, 10, 8),
    shadow: flat(new CircleGeometry(1, 18)),
  };
  const shadowMat = new MeshBasicMaterial({ color: '#000000', transparent: true, opacity: 0.22, depthWrite: false });
  const capMats = api.FR.map((c) => (c ? lam(c[0]) : null));
  const rnd = api.rng(api.hashStr((data.id || '') + 'horses'));

  function clothTex(h) {
    const c = document.createElement('canvas'); c.width = 128; c.height = 80;
    const x = c.getContext('2d');
    x.fillStyle = '#ffffff'; x.fillRect(0, 0, 128, 80);
    x.fillStyle = '#111111'; x.font = '700 56px sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle';
    x.fillText(String(h.n), 64, 44);
    const t = new CanvasTexture(c); t.colorSpace = SRGBColorSpace; return t;
  }
  function badgeTex(h, honme) {
    const c = document.createElement('canvas'); c.width = 128; c.height = 176;
    const x = c.getContext('2d'), col = api.FR[h.f] || api.FR[1];
    if (h.m && '◎〇▲'.indexOf(h.m) >= 0) {
      x.fillStyle = '#ffffff'; x.font = '700 50px sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle';
      x.lineWidth = 8; x.strokeStyle = 'rgba(0,0,0,.6)'; x.strokeText(h.m, 64, 26); x.fillText(h.m, 64, 26);
    }
    x.beginPath(); x.arc(64, 112, 50, 0, Math.PI * 2);
    x.fillStyle = col[0]; x.fill();
    x.lineWidth = honme ? 12 : 6; x.strokeStyle = honme ? '#2fbf71' : '#111111'; x.stroke();
    x.fillStyle = col[1]; x.font = '700 ' + (h.n > 9 ? 54 : 64) + 'px sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle';
    x.fillText(String(h.n), 64, 116);
    const t = new CanvasTexture(c); t.colorSpace = SRGBColorSpace; return t;
  }

  const horses = H.map((h, i) => {
    const g = new Group(), body = new Group();
    const coat = lam(COATS[Math.floor(rnd() * COATS.length)]);
    const silk = lam(SILKS[(h.n * 5 + Math.floor(rnd() * 3)) % SILKS.length]);
    const add = (parent, mesh, x, y, z, rz) => { mesh.position.set(x, y, z || 0); if (rz) mesh.rotation.z = rz; parent.add(mesh); return mesh; };
    add(body, new Mesh(geo.body, coat), 0, 10.2, 0);
    add(body, new Mesh(geo.neck, coat), 6.3, 13.4, 0, -0.95);
    add(body, new Mesh(geo.head, coat), 9.6, 15.2, 0, -0.55);
    const clothMat = new MeshLambertMaterial({ map: clothTex(h) });
    const white = lam('#ffffff');
    add(body, new Mesh(geo.cloth, [white, white, white, white, clothMat, clothMat]), -0.6, 10.9, 0);
    add(body, new Mesh(geo.torso, silk), 1.2, 15.3, 0, -0.75);
    add(body, new Mesh(geo.helmet, capMats[h.f] || capMats[1]), 3.0, 17.3, 0);
    const legs = [[4.7, 1.5], [4.7, -1.5], [-4.6, 1.5], [-4.6, -1.5]].map(([x, z]) => {
      const pv = new Group(); pv.position.set(x, 8.9, z); pv.add(new Mesh(geo.leg, coat)); body.add(pv); return pv;
    });
    const tail = new Group(); tail.position.set(-7.4, 11.6, 0); tail.add(new Mesh(geo.tail, coat)); tail.rotation.z = -0.55; body.add(tail);
    g.add(body);
    const sh = new Mesh(geo.shadow, shadowMat); sh.scale.set(11, 1, 4.5); sh.position.y = 0.1; g.add(sh);
    const sp = new Sprite(new SpriteMaterial({ map: badgeTex(h, h.m === '◎'), depthTest: false, transparent: true }));
    sp.scale.set(7.5, 10.3, 1); sp.position.y = 28; sp.renderOrder = 10; g.add(sp);
    scene.add(g);
    return { g, body, legs, tail, sp, phase: rnd() * Math.PI * 2, prev: null, amp: 0 };
  });

  // ---------- カメラ ----------
  let view = 'tv', snap = true, lastNow = 0;
  const camPos = new Vector3(), camLook = new Vector3();
  function topView() {
    const vf = camera.fov * Math.PI / 180, hf = 2 * Math.atan(Math.tan(vf / 2) * camera.aspect);
    const half = (G.straight ? G.W * 0.5 : G.W * 0.55) + 20;
    const d = Math.max(half / Math.tan(hf / 2), (G.H * 0.62) / Math.tan(vf / 2)) * 1.05;
    const el = G.straight ? 0.95 : 1.0;
    camPos.set(0, d * Math.sin(el), d * Math.cos(el));
    camLook.set(0, 0, G.straight ? (G.top + G.bot) / 2 - H2 : 10);
  }

  function resize() {
    const w = Math.max(280, Math.round(stage.clientWidth || 600));
    const h = Math.round(w < 600 ? Math.max(240, w * 0.66) : Math.max(220, Math.min(460, w * 0.56))); // スマホは少し縦長に
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, w < 600 ? 1.5 : 2));
    renderer.setSize(w, h, false);
    canvas.style.width = '100%'; canvas.style.height = h + 'px';
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    snap = true;
  }

  function draw(f) {
    const now = performance.now(), dt = lastNow ? Math.min(0.05, (now - lastNow) / 1000) : 0;
    lastNow = now;
    // 馬（上からの視点では、見分けやすいように馬と番号を大きくする）
    const big = view === 'top', hs = big ? 1.7 : 1, bs = big ? 2.3 : 1;
    let lead = null, pack = new Vector3(), pc = 0, leadU = 0;
    f.order.forEach((i, k) => {
      const hz = horses[i], u = f.prog[i], lane = Math.min(f.lane[i], G.lanes - 1);
      P3(u, lane, tmp);
      P3(u + 4, lane, tmp2);
      const speed = hz.prev && dt > 0 ? tmp.distanceTo(hz.prev) / dt : 0;
      hz.prev = (hz.prev || new Vector3()).copy(tmp);
      const target = f.running ? Math.min(1, speed / 60) : 0;
      hz.amp += (target - hz.amp) * Math.min(1, dt * 6);
      hz.phase += dt * 2 * Math.PI * 2.3 * hz.amp;
      const a = hz.amp, ph = hz.phase;
      hz.legs[0].rotation.z = 0.7 * a * Math.sin(ph);
      hz.legs[1].rotation.z = 0.7 * a * Math.sin(ph + 0.9);
      hz.legs[2].rotation.z = 0.7 * a * Math.sin(ph + 3.4);
      hz.legs[3].rotation.z = 0.7 * a * Math.sin(ph + 4.2);
      hz.tail.rotation.z = -(0.55 + 0.35 * a + 0.1 * a * Math.sin(ph * 2)); // 走るほど後ろに流れる
      hz.body.position.y = 0.8 * a * Math.abs(Math.sin(ph));
      hz.body.rotation.z = 0.05 * a * Math.sin(ph + 1.2);
      hz.g.position.copy(tmp);
      hz.g.scale.setScalar(hs);
      hz.sp.scale.set(7.5 * bs, 10.3 * bs, 1);
      hz.g.rotation.y = -Math.atan2(tmp2.z - tmp.z, tmp2.x - tmp.x);
      if (k === 0) { lead = tmp.clone(); leadU = u; }
      if (k < 3) { pack.add(tmp); pc++; }
    });
    pack.multiplyScalar(1 / Math.max(1, pc));
    // カメラ
    if (view === 'top') topView();
    else {
      // 中継カメラ：内馬場の側から先頭集団を追う（外側だとスタンドに隠れるため）。背景にスタンドが映る
      const lane = G.lanes / 2;
      const p = P3(leadU, lane), inward = p.clone().sub(P3(leadU, lane + 1)).normalize(), tan = P3(leadU + 3, lane).sub(p).normalize();
      const dist = camera.aspect < 1.4 ? 135 : 115;
      camPos.copy(pack).addScaledVector(inward, dist).addScaledVector(tan, 12); camPos.y = 31;
      camLook.copy(pack).addScaledVector(tan, -16); camLook.y = 13; // 馬が画面のまん中あたりに来る高さ
    }
    if (snap || !f.running) { camera.position.copy(camPos); camera.userData.look = camLook.clone(); snap = false; }
    else {
      const k = 1 - Math.exp(-dt * 3.2);
      camera.position.lerp(camPos, k);
      camera.userData.look.lerp(camLook, k);
    }
    camera.lookAt(camera.userData.look);
    renderer.render(scene, camera);
    if (hudI.textContent !== f.info) hudI.textContent = f.info;
    const l = f.t > 0 ? f.line : '';
    if (hudL.textContent !== l) hudL.textContent = l;
  }

  return {
    kind: '3d',
    geom: () => G,
    resize,
    draw,
    show(on) { canvas.style.display = on ? '' : 'none'; hud.style.display = on ? '' : 'none'; },
    setView(v) { view = v === 'top' ? 'top' : 'tv'; snap = true; },
  };
}
