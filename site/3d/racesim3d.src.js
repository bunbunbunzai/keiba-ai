/* レースシミュレーションの3D表示（重賞のページだけ）。
   着順・実況・集計は racesim.js が行い、ここは毎フレーム渡される位置を3Dで描くだけ。
   コースの形は 2D と同じ計算（api.geom / api.pt）を 1200×600 の固定の大きさで使い、
   その座標をそのまま地面（x, z）に置く。馬・騎手・背景はすべてプログラムで形を作る（外部の素材は使わない）。

   ビルド（three.js から使う部分だけを1ファイルにまとめる）:
     cd site/3d && npm ci && npm run build   → site/racesim3d.js
*/
import {
  WebGLRenderer, Scene, PerspectiveCamera, Color, Fog, HemisphereLight, DirectionalLight,
  Mesh, MeshStandardMaterial, MeshBasicMaterial, Shape, Path, ShapeGeometry, BoxGeometry,
  CylinderGeometry, SphereGeometry, CapsuleGeometry, PlaneGeometry, ConeGeometry, IcosahedronGeometry,
  Group, CanvasTexture, Sprite, SpriteMaterial, Vector3, Quaternion, InstancedMesh, Object3D, DoubleSide, BackSide,
  TubeGeometry, CatmullRomCurve3, SRGBColorSpace, BufferGeometry, Float32BufferAttribute, RepeatWrapping,
  PCFShadowMap, ACESFilmicToneMapping
} from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

// 毛色：体・たてがみと尾・脚の先
const COATS = [
  { body: '#6b3a1c', points: '#17110d', legs: '#1d1511' }, // 鹿毛
  { body: '#8a4a22', points: '#7a3f1c', legs: '#7d4420' }, // 栗毛
  { body: '#3d2415', points: '#120d0a', legs: '#140f0c' }, // 黒鹿毛
  { body: '#1f1713', points: '#0c0908', legs: '#0f0b0a' }, // 青鹿毛
  { body: '#5a2f17', points: '#4d2712', legs: '#4f2a14' }, // 栃栗毛
  { body: '#a9a8a3', points: '#d8d7d2', legs: '#6f6e6a' }, // 芦毛
];
const SILKS = [['#1e4fa8', '#f2c200'], ['#c8102e', '#ffffff'], ['#f2c200', '#111111'], ['#1f8f4a', '#ffffff'], ['#7a2c8f', '#f2c200'],
  ['#f08a24', '#1e4fa8'], ['#111111', '#c8102e'], ['#e9e9e9', '#c8102e'], ['#0f8fa6', '#ffffff'], ['#b5651d', '#f2c200'],
  ['#d14f8f', '#ffffff'], ['#2f4f2f', '#f08a24']];
const Y = new Vector3(0, 1, 0);

export function create(stage, data, api) {
  const H = data.horses;
  const G = data.straight ? api.geom(1200, 320, data) : api.geom(1200, 600, data);
  const base = G.straight ? 0 : G.us;
  const W2 = G.W / 2, H2 = G.H / 2;
  const tmp = new Vector3(), tmp2 = new Vector3();
  function P3(u, lane, out) {
    const p = api.pt(G, base + u, lane);
    return (out || new Vector3()).set(p[0] - W2, 0, p[1] - H2);
  }
  const small = (stage.clientWidth || 600) < 600;

  // ---------- 描画の土台 ----------
  const canvas = document.createElement('canvas');
  canvas.className = 'rsim-3d';
  const renderer = new WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.toneMapping = ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = PCFShadowMap;
  const maxAniso = Math.min(8, renderer.capabilities.getMaxAnisotropy());
  const scene = new Scene();
  scene.fog = new Fog('#c3dcf0', 1100, 5200);
  const camera = new PerspectiveCamera(30, 16 / 9, 3, 12000);
  scene.add(new HemisphereLight('#e6f1ff', '#6d8650', 1.9));
  const sun = new DirectionalLight('#fff3dc', 3.0);
  sun.castShadow = true;
  sun.shadow.mapSize.set(small ? 1024 : 2048, small ? 1024 : 2048);
  sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.5;
  sun.shadow.camera.near = 10; sun.shadow.camera.far = 3000;
  scene.add(sun, sun.target);
  const SUN_DIR = new Vector3(0.4, 0.85, -0.3).normalize(); // 内馬場の側から照らす（中継カメラから見て順光）

  const hud = document.createElement('div');
  hud.className = 'rsim-hud';
  hud.innerHTML = '<span class="i"></span><span class="l"></span>';
  const hudI = hud.querySelector('.i'), hudL = hud.querySelector('.l');
  stage.appendChild(canvas);
  stage.appendChild(hud);

  const std = (c, o) => new MeshStandardMaterial(Object.assign({ color: new Color(c), roughness: 0.85, metalness: 0 }, o || {}));
  const flat = (geo) => { geo.rotateX(-Math.PI / 2); return geo; };
  const texRand = api.rng(api.hashStr('tex'));

  // ---------- 質感（キャンバスに描いて貼る） ----------
  function tex(c, rx, ry) {
    const t = new CanvasTexture(c);
    t.colorSpace = SRGBColorSpace; t.wrapS = t.wrapT = RepeatWrapping; t.anisotropy = maxAniso;
    if (rx) t.repeat.set(rx, ry == null ? rx : ry);
    return t;
  }
  function noiseCanvas(baseCol, lightCol, darkCol, stripes) {
    const c = document.createElement('canvas'); c.width = c.height = 256;
    const x = c.getContext('2d');
    x.fillStyle = baseCol; x.fillRect(0, 0, 256, 256);
    if (stripes) { x.fillStyle = stripes; x.fillRect(0, 0, 128, 256); }
    for (let k = 0; k < 5200; k++) {
      x.fillStyle = texRand() < 0.5 ? lightCol : darkCol;
      x.globalAlpha = 0.10 + texRand() * 0.22;
      const s = 1 + texRand() * 2.4;
      x.fillRect(texRand() * 256, texRand() * 256, s, s * (1 + texRand()));
    }
    x.globalAlpha = 1;
    return c;
  }
  const turf = data.surface === '芝';
  const grassOut = noiseCanvas('#5f9a4a', '#7fb963', '#3f7a35');
  const grassIn = noiseCanvas('#6fae55', '#8cc66e', '#4d8a3f', '#66a54e');
  const trackC = turf ? noiseCanvas('#3f8f3d', '#5cab52', '#2c7030') : noiseCanvas('#b88a5a', '#d2a878', '#93693f');

  // ---------- 空・雲・遠くの山 ----------
  {
    const c = document.createElement('canvas'); c.width = 4; c.height = 256;
    const x = c.getContext('2d'), g = x.createLinearGradient(0, 0, 0, 256);
    g.addColorStop(0, '#2b6cc0'); g.addColorStop(0.3, '#5e9fdc'); g.addColorStop(0.44, '#93c3ea'); g.addColorStop(0.5, '#c3dcf0'); g.addColorStop(1, '#c3dcf0');
    x.fillStyle = g; x.fillRect(0, 0, 4, 256);
    const t = new CanvasTexture(c); t.colorSpace = SRGBColorSpace;
    scene.add(new Mesh(new SphereGeometry(9000, 24, 16), new MeshBasicMaterial({ map: t, side: BackSide, fog: false, depthWrite: false })));
    const cc = document.createElement('canvas'); cc.width = 256; cc.height = 128;
    const cx = cc.getContext('2d');
    for (let k = 0; k < 9; k++) {
      const px = 50 + texRand() * 156, py = 50 + texRand() * 36, r = 26 + texRand() * 26;
      const rg = cx.createRadialGradient(px, py, 0, px, py, r);
      rg.addColorStop(0, 'rgba(255,255,255,.85)'); rg.addColorStop(1, 'rgba(255,255,255,0)');
      cx.fillStyle = rg; cx.fillRect(0, 0, 256, 128);
    }
    const ct = new CanvasTexture(cc); ct.colorSpace = SRGBColorSpace;
    for (let k = 0; k < 12; k++) {
      const sp = new Sprite(new SpriteMaterial({ map: ct, fog: false, transparent: true, opacity: 0.9, depthWrite: false }));
      const a = k / 12 * Math.PI * 2 + texRand(), s = 1100 + texRand() * 900;
      sp.position.set(Math.cos(a) * 5200, 900 + texRand() * 900, Math.sin(a) * 5200); sp.scale.set(s, s * 0.45, 1);
      scene.add(sp);
    }
    const hills = new InstancedMesh(new IcosahedronGeometry(1, 2), std('#6f9480', { flatShading: true }), 22);
    const o = new Object3D();
    for (let k = 0; k < 22; k++) {
      const a = k / 22 * Math.PI * 2 + texRand() * 0.2, r = 3000 + texRand() * 500;
      o.position.set(Math.cos(a) * r, -30, Math.sin(a) * r);
      o.scale.set(520 + texRand() * 380, 170 + texRand() * 190, 520 + texRand() * 300);
      o.rotation.y = texRand() * 3; o.updateMatrix(); hills.setMatrixAt(k, o.matrix);
    }
    scene.add(hills);
  }

  // ---------- 地面・コース ----------
  const ground = new Mesh(flat(new PlaneGeometry(9000, 9000)), std('#ffffff', { map: tex(grassOut, 110) }));
  ground.position.y = -0.5; ground.receiveShadow = true;
  scene.add(ground);
  const trackMat = std('#ffffff', { map: tex(trackC, 1 / 55), side: DoubleSide, roughness: turf ? 0.9 : 1 });
  const infieldMat = std('#ffffff', { map: tex(grassIn, 1 / 90), side: DoubleSide });
  const railMat = std('#ffffff', { roughness: 0.5 });

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
  function tubeAlong(pts, y, radius, mat, closed) {
    const curve = new CatmullRomCurve3(pts.map(([x, z]) => new Vector3(x, y, z)), closed, 'catmullrom', 0.05);
    scene.add(new Mesh(new TubeGeometry(curve, Math.min(700, pts.length * 3), radius, 6, closed), mat));
    return curve;
  }
  function posts(curve, every) {
    const len = curve.getLength(), cnt = Math.floor(len / every);
    const im = new InstancedMesh(new CylinderGeometry(0.3, 0.3, 3.4, 6), railMat, cnt);
    const o = new Object3D();
    for (let k = 0; k < cnt; k++) {
      const p = curve.getPointAt(k / cnt);
      o.position.set(p.x, 1.7, p.z); o.updateMatrix(); im.setMatrixAt(k, o.matrix);
    }
    scene.add(im);
  }
  const hedgeMat = std('#3f8a3d');

  if (G.straight) {
    const x0 = G.x0 - W2 - 30, x1 = G.x1 - W2 + 60, z0 = G.top - H2, z1 = G.bot - H2;
    const tm = trackMat.clone(); tm.map = tex(trackC, (x1 - x0) / 55, (z1 - z0) / 55);
    const t = new Mesh(flat(new PlaneGeometry(x1 - x0, z1 - z0)), tm);
    t.position.set((x0 + x1) / 2, 0.2, (z0 + z1) / 2); t.receiveShadow = true;
    scene.add(t);
    for (const z of [z0 - 0.5, z1 + 0.5]) {
      const pts = [];
      for (let x = x0; x <= x1; x += 40) pts.push([x, z]);
      posts(tubeAlong(pts, 3.4, 0.45, railMat, false), 22);
    }
  } else {
    const outer = stadiumPts(G.Ro, 56), inner = stadiumPts(G.Ri, 56);
    const tr = new Mesh(shapeOf(outer, inner), trackMat); tr.position.y = 0.2; tr.receiveShadow = true; scene.add(tr);
    const inf = new Mesh(shapeOf(inner), infieldMat); inf.position.y = 0.1; inf.receiveShadow = true; scene.add(inf);
    posts(tubeAlong(stadiumPts(G.Ri - 0.5, 56), 3.4, 0.45, railMat, true), 22);
    posts(tubeAlong(stadiumPts(G.Ro + 0.5, 56), 3.4, 0.45, railMat, true), 22);
    tubeAlong(stadiumPts(G.Ri - 4.5, 56), 0.9, 1.5, hedgeMat, true); // 内柵の内側の生け垣
    // スタンド（最後の直線の外側）：観客席・屋根・柱・ガラス
    const zs = G.cy + G.Ro - H2, len = G.Ls * 0.9;
    const cc = document.createElement('canvas'); cc.width = 256; cc.height = 128;
    const cx = cc.getContext('2d');
    cx.fillStyle = '#3b4250'; cx.fillRect(0, 0, 256, 128);
    const cols = ['#e8e8e8', '#d6453d', '#3f6fd1', '#f2c94c', '#2b2b2b', '#e9a23b', '#6ab04c', '#f7f1e3', '#c56cf0'];
    for (let r = 0; r < 16; r++) for (let k = 0; k < 64; k++) {
      if (texRand() < 0.12) continue;
      cx.fillStyle = cols[Math.floor(texRand() * cols.length)];
      cx.fillRect(k * 4 + (r % 2) * 2, r * 8 + 2, 3, 4);
      cx.fillStyle = '#e6b99a'; cx.fillRect(k * 4 + (r % 2) * 2 + 0.5, r * 8, 2, 2);
    }
    const crowd = new Mesh(new PlaneGeometry(len, 46), std('#ffffff', { map: tex(cc, len / 110, 1), roughness: 1, side: DoubleSide }));
    crowd.rotation.set(0.95, Math.PI, 0); crowd.position.set(0, 21, zs + 42); scene.add(crowd); // コースの側を向いた斜面
    const wall = new Mesh(new BoxGeometry(len, 6, 2), std('#f1f1ee')); wall.position.set(0, 3, zs + 22); scene.add(wall);
    const back = new Mesh(new BoxGeometry(len, 62, 16), std('#dfe3e6')); back.position.set(0, 31, zs + 66); scene.add(back);
    const glass = new Mesh(new BoxGeometry(len * 0.98, 9, 1), std('#5d8fb5', { roughness: 0.15, metalness: 0.6 }));
    glass.position.set(0, 46, zs + 57.6); scene.add(glass);
    const roof = new Mesh(new BoxGeometry(len * 1.03, 1.6, 58), std('#e9ecee')); roof.position.set(0, 66, zs + 44); roof.rotation.x = -0.1; scene.add(roof);
    const roofEdge = new Mesh(new BoxGeometry(len * 1.03, 2.4, 2), std('#c8102e')); roofEdge.position.set(0, 68.6, zs + 15.6); scene.add(roofEdge);
    for (let k = 0; k <= 8; k++) {
      const p = new Mesh(new CylinderGeometry(0.9, 0.9, 62, 8), std('#b9c0c6'));
      p.position.set(-len / 2 + len * k / 8, 31, zs + 57); scene.add(p);
    }
    // 内馬場の大型ビジョン
    const vc = document.createElement('canvas'); vc.width = 512; vc.height = 160;
    const vx = vc.getContext('2d');
    const vg = vx.createLinearGradient(0, 0, 0, 160); vg.addColorStop(0, '#0d3b2a'); vg.addColorStop(1, '#06120d');
    vx.fillStyle = vg; vx.fillRect(0, 0, 512, 160);
    vx.fillStyle = '#ffffff'; vx.textAlign = 'center'; vx.textBaseline = 'middle';
    vx.font = '700 58px sans-serif'; vx.fillText('競馬全頭ログ', 256, 62);
    vx.fillStyle = '#9fe0bd'; vx.font = '700 30px sans-serif';
    vx.fillText(data.dist + 'm ' + (turf ? '芝' : 'ダート') + '  ' + H.length + '頭', 256, 122);
    const vt = new CanvasTexture(vc); vt.colorSpace = SRGBColorSpace; vt.anisotropy = maxAniso;
    const frame = std('#20262b'), scr = new MeshBasicMaterial({ map: vt });
    const vis = new Mesh(new BoxGeometry(120, 38, 4), [frame, frame, frame, frame, scr, scr]);
    vis.position.set(0, 30, G.cy - G.Ri * 0.15 - H2); scene.add(vis);
    for (const s of [-1, 1]) { const leg = new Mesh(new BoxGeometry(5, 12, 4), std('#59616a')); leg.position.set(s * 40, 6, vis.position.z); scene.add(leg); }
  }

  // ゴール板とゴールの線（ゴールは走った長さが G.Dpx の地点）
  {
    const a = P3(G.Dpx, -0.6), b = P3(G.Dpx, G.lanes - 0.3);
    const line = new Mesh(new BoxGeometry(a.distanceTo(b), 0.1, 1.2), new MeshBasicMaterial({ color: '#ffffff' }));
    line.position.copy(a).add(b).multiplyScalar(0.5); line.position.y = 0.32;
    line.rotation.y = -Math.atan2(b.z - a.z, b.x - a.x);
    scene.add(line);
    const side = P3(G.Dpx, -1.3), out = P3(G.Dpx, G.lanes + 4);
    const pole = new Mesh(new CylinderGeometry(0.6, 0.6, 26, 10), std('#c8102e', { roughness: 0.4 }));
    pole.position.set(side.x, 13, side.z); pole.castShadow = true; scene.add(pole);
    const board = new Group();
    board.add(new Mesh(new CylinderGeometry(5.6, 5.6, 0.8, 28).rotateX(Math.PI / 2), std('#c8102e', { roughness: 0.4 })));
    const face = new Mesh(new CylinderGeometry(4.6, 4.6, 1.0, 28).rotateX(Math.PI / 2), std('#f4f6f7', { roughness: 0.1, metalness: 0.7 }));
    board.add(face);
    board.position.set(side.x, 28, side.z); board.lookAt(out.x, 28, out.z); scene.add(board);
  }
  // 200mごとの標識（ハロン棒）
  if (!G.straight) {
    for (let k = 1; k * 200 < data.dist && k <= 16; k++) {
      const p = P3(G.Dpx * (1 - k * 200 / data.dist), -1.3);
      const post = new Mesh(new CylinderGeometry(0.45, 0.45, 9, 8), std('#ffffff')); post.position.set(p.x, 4.5, p.z); scene.add(post);
      const cap = new Mesh(new CylinderGeometry(0.75, 0.75, 2.2, 8), std(k % 2 ? '#c8102e' : '#1e4fa8')); cap.position.set(p.x, 9.6, p.z); scene.add(cap);
    }
  }
  // スタートのゲート（スタートとゴールが同じ場所でなければ）
  if (G.straight || Math.abs(((G.us - G.uf) % G.P + G.P) % G.P) > 20) {
    const a = P3(0, -0.6), b = P3(0, G.lanes - 0.3), len = a.distanceTo(b);
    const gate = new Group(), gm = std('#e9edf0', { roughness: 0.4, metalness: 0.3 }), gg = std('#1f8f4a');
    const beam = new Mesh(new BoxGeometry(5, 2.4, len), gg); beam.position.y = 15; gate.add(beam);
    const cnt = Math.max(3, Math.round(len / 9));
    for (let k = 0; k <= cnt; k++) { const tw = new Mesh(new BoxGeometry(4.4, 15, 0.7), gm); tw.position.set(0, 7.5, -len / 2 + len * k / cnt); tw.castShadow = true; gate.add(tw); }
    const fwd = P3(0, G.lanes / 2).sub(P3(-6, G.lanes / 2)).normalize().multiplyScalar(7); // ゲートは馬の少し前
    gate.position.copy(a).add(b).multiplyScalar(0.5).add(fwd);
    gate.lookAt(b.x + fwd.x, 0, b.z + fwd.z);
    scene.add(gate);
  }
  // 木（コースの外に散らす。葉は丸いかたまりを2つ重ねる）
  {
    const rand = api.rng(api.hashStr((data.id || '') + 'trees'));
    const cnt = 110, trunk = new InstancedMesh(new CylinderGeometry(1.1, 1.7, 12, 6), std('#5d4330'), cnt);
    const leaf = new InstancedMesh(new IcosahedronGeometry(1, 1), std('#ffffff', { flatShading: true }), cnt * 2);
    trunk.castShadow = leaf.castShadow = true;
    const o = new Object3D(), col = new Color();
    let k = 0, guard = 0;
    while (k < cnt && guard++ < 4000) {
      const x = (rand() - 0.5) * 2300, z = (rand() - 0.5) * 1500;
      const nx = Math.abs(x) - G.Ls / 2, inside = G.straight
        ? Math.abs(z - ((G.top + G.bot) / 2 - H2)) < (G.bot - G.top) / 2 + 60
        : Math.hypot(Math.max(0, nx), z - (G.cy - H2)) < G.Ro + 45;
      const stand = !G.straight && Math.abs(x) < G.Ls * 0.55 && z > G.cy + G.Ro - H2 && z < G.cy + G.Ro - H2 + 110;
      if (inside || stand) continue;
      const s = 0.8 + rand() * 0.9;
      o.rotation.set(0, rand() * 6, 0);
      o.position.set(x, 6 * s, z); o.scale.set(s, s, s); o.updateMatrix(); trunk.setMatrixAt(k, o.matrix);
      col.setHSL(0.27 + rand() * 0.07, 0.42 + rand() * 0.15, 0.24 + rand() * 0.1);
      o.position.set(x, 20 * s, z); o.scale.set(11 * s, 11 * s, 11 * s); o.updateMatrix(); leaf.setMatrixAt(k * 2, o.matrix); leaf.setColorAt(k * 2, col);
      o.position.set(x + 4 * s, 28 * s, z + 2 * s); o.scale.set(7.5 * s, 7.5 * s, 7.5 * s); o.updateMatrix(); leaf.setMatrixAt(k * 2 + 1, o.matrix);
      col.offsetHSL(0, 0, 0.05); leaf.setColorAt(k * 2 + 1, col);
      k++;
    }
    trunk.count = k; leaf.count = k * 2;
    scene.add(trunk, leaf);
  }

  // ---------- 馬と騎手の形 ----------
  // 色つきの部品にする（あとで1つにまとめるため、uv を外して頂点に色を持たせる）
  function paint(geo, color) {
    const g = geo.index ? geo.toNonIndexed() : geo;
    g.deleteAttribute('uv');
    const c = new Color(color), n = g.getAttribute('position').count, arr = new Float32Array(n * 3);
    for (let k = 0; k < n; k++) { arr[k * 3] = c.r; arr[k * 3 + 1] = c.g; arr[k * 3 + 2] = c.b; }
    g.setAttribute('color', new Float32BufferAttribute(arr, 3));
    return g;
  }
  // 断面（だ円）を背骨に沿って並べてつなぎ、なめらかな体を作る。rings: [x, y, 縦の半径, 横の半径]
  function loft(rings, seg, color) {
    const pos = [], idx = [], n = rings.length;
    for (let i = 0; i < n; i++) {
      const a = rings[Math.max(0, i - 1)], b = rings[Math.min(n - 1, i + 1)];
      let tx = b[0] - a[0], ty = b[1] - a[1]; const l = Math.hypot(tx, ty) || 1; tx /= l; ty /= l;
      const [cx, cy, ry, rz] = rings[i];
      for (let k = 0; k < seg; k++) {
        const an = k / seg * Math.PI * 2, c = Math.cos(an) * ry, s = Math.sin(an) * rz;
        pos.push(cx - ty * c, cy + tx * c, s);
      }
    }
    for (let i = 0; i < n - 1; i++) for (let k = 0; k < seg; k++) {
      const A = i * seg + k, B = (i + 1) * seg + k, C = (i + 1) * seg + (k + 1) % seg, D = i * seg + (k + 1) % seg;
      idx.push(A, C, B, A, D, C);
    }
    const c0 = pos.length / 3; pos.push(rings[0][0], rings[0][1], 0);
    const c1 = c0 + 1; pos.push(rings[n - 1][0], rings[n - 1][1], 0);
    for (let k = 0; k < seg; k++) { idx.push(c0, (k + 1) % seg, k); idx.push(c1, (n - 1) * seg + k, (n - 1) * seg + (k + 1) % seg); }
    const g = new BufferGeometry();
    g.setAttribute('position', new Float32BufferAttribute(pos, 3));
    g.setIndex(idx); g.computeVertexNormals();
    return paint(g, color);
  }
  const q = new Quaternion();
  function limb(a, b, r, color) {
    const d = new Vector3(b[0] - a[0], b[1] - a[1], b[2] - a[2]), len = d.length();
    const g = new CapsuleGeometry(r, len, 3, 8);
    g.applyQuaternion(q.setFromUnitVectors(Y, d.normalize()));
    g.translate((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2);
    return paint(g, color);
  }
  const at = (g, x, y, z) => { g.translate(x, y, z); return g; };

  const coatParts = COATS.map((c) => {
    const body = loft([
      [-7.3, 11.3, 0.5, 0.5], [-6.7, 11.5, 2.1, 1.9], [-5.0, 11.5, 3.0, 2.6], [-2.6, 11.0, 2.9, 2.6], [0, 10.7, 2.8, 2.5],
      [2.2, 10.7, 3.0, 2.6], [4.2, 11.1, 3.1, 2.4], [5.6, 12.2, 2.6, 1.8], [7.0, 13.6, 2.0, 1.3], [8.5, 15.0, 1.6, 1.05],
      [9.7, 16.0, 1.45, 1.0], [10.8, 16.3, 1.35, 1.0], [12.0, 15.6, 1.15, 0.9], [13.3, 14.5, 0.85, 0.72], [14.0, 13.9, 0.45, 0.45]], 14, c.body);
    const mane = loft([[5.2, 14.6, 0.5, 0.2], [6.4, 15.5, 0.95, 0.24], [7.8, 16.6, 1.0, 0.24], [9.2, 17.4, 0.9, 0.22], [10.4, 17.6, 0.45, 0.18]], 6, c.points);
    const ears = [-1, 1].map((s) => { const e = new ConeGeometry(0.34, 1.3, 6); e.rotateZ(-0.35); e.rotateX(s * 0.25); return at(paint(e, c.body), 10.3, 17.9, s * 0.55); });
    const eyes = [-1, 1].map((s) => at(paint(new SphereGeometry(0.17, 6, 5), '#0b0908'), 11.3, 16.6, s * 0.88));
    const nose = at(paint(new SphereGeometry(0.5, 8, 6), c.points === c.body ? '#2a1a12' : c.points), 13.75, 14.0, 0);
    const lowerLeg = (len) => mergeGeometries([
      at(paint(new CylinderGeometry(0.5, 0.4, len, 8), c.legs), 0, -len / 2, 0),
      at(paint(new SphereGeometry(0.5, 8, 6), c.legs), 0, 0, 0),
      at(paint(new CylinderGeometry(0.5, 0.68, 0.8, 8), '#161210'), 0, -len - 0.4, 0)]);
    return {
      fixed: [body, mane, nose, ...ears, ...eyes],
      fU: at(paint(new CylinderGeometry(1.0, 0.55, 4.9, 8), c.body), 0, -2.45, 0),
      fL: lowerLeg(3.7),
      hU: at(paint(new CylinderGeometry(1.55, 0.62, 5.3, 8), c.body), 0, -2.65, 0),
      hL: lowerLeg(4.1),
      tail: loft([[0, 0, 0.4, 0.4], [-1.2, -0.5, 0.62, 0.55], [-2.6, -2.0, 0.75, 0.62], [-3.7, -4.2, 0.62, 0.5], [-4.3, -6.3, 0.2, 0.18]], 7, c.points),
    };
  });
  const horseMat = new MeshStandardMaterial({ vertexColors: true, roughness: 0.55, metalness: 0.05 });
  const whiteMat = std('#f6f6f3', { roughness: 0.8 });
  const clothGeo = new BoxGeometry(4.4, 2.9, 5.5);
  const rnd = api.rng(api.hashStr((data.id || '') + 'horses'));

  function clothTex(h) {
    const c = document.createElement('canvas'); c.width = 128; c.height = 84;
    const x = c.getContext('2d');
    x.fillStyle = '#f6f6f3'; x.fillRect(0, 0, 128, 84);
    x.strokeStyle = '#1c1c1c'; x.lineWidth = 4; x.strokeRect(3, 3, 122, 78);
    x.fillStyle = '#111111'; x.font = '700 60px sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle';
    x.fillText(String(h.n), 64, 46);
    const t = new CanvasTexture(c); t.colorSpace = SRGBColorSpace; t.anisotropy = maxAniso; return t;
  }
  function badgeTex(h, honme) {
    const c = document.createElement('canvas'); c.width = 128; c.height = 176;
    const x = c.getContext('2d'), col = api.FR[h.f] || api.FR[1];
    if (h.m && '◎〇▲'.indexOf(h.m) >= 0) {
      x.fillStyle = '#ffffff'; x.font = '700 50px sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle';
      x.lineWidth = 8; x.strokeStyle = 'rgba(0,0,0,.65)'; x.strokeText(h.m, 64, 26); x.fillText(h.m, 64, 26);
    }
    x.beginPath(); x.arc(64, 112, 50, 0, Math.PI * 2);
    x.fillStyle = col[0]; x.fill();
    x.lineWidth = honme ? 12 : 6; x.strokeStyle = honme ? '#2fbf71' : '#ffffff'; x.stroke();
    x.fillStyle = col[1]; x.font = '700 ' + (h.n > 9 ? 54 : 64) + 'px sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle';
    x.fillText(String(h.n), 64, 116);
    const t = new CanvasTexture(c); t.colorSpace = SRGBColorSpace; return t;
  }
  function jockey(silk, cap) {
    const skin = '#e3b08c', br = '#f4f4f0', boot = '#151515', parts = [];
    parts.push(limb([-0.6, 15.5, 0], [3.3, 16.9, 0], 1.0, silk[0]));                        // 胴（前かがみ）
    for (const s of [-1, 1]) {
      parts.push(limb([-0.4, 15.2, s * 0.9], [2.0, 14.3, s * 2.1], 0.6, br));               // もも
      parts.push(limb([2.0, 14.3, s * 2.1], [0.7, 12.3, s * 2.75], 0.48, boot));            // すね・ブーツ
      parts.push(limb([3.0, 16.7, s * 1.0], [4.6, 15.6, s * 1.3], 0.42, silk[1]));          // 上腕
      parts.push(limb([4.6, 15.6, s * 1.3], [6.4, 15.2, s * 0.7], 0.36, silk[1]));          // 前腕
      parts.push(at(paint(new SphereGeometry(0.4, 6, 5), '#f4f4f0'), 6.5, 15.2, s * 0.7));  // 手袋
    }
    parts.push(at(paint(new SphereGeometry(0.78, 10, 8), skin), 4.25, 17.75, 0));           // 頭
    parts.push(at(paint(new SphereGeometry(0.95, 12, 8, 0, Math.PI * 2, 0, Math.PI * 0.6), cap), 4.25, 17.95, 0)); // 帽子（枠の色）
    const brim = new CylinderGeometry(0.55, 0.55, 0.12, 10); brim.scale(1.3, 1, 1);
    parts.push(at(paint(brim, cap), 5.15, 17.75, 0));
    parts.push(at(paint(new BoxGeometry(0.5, 0.45, 1.5), '#1b1b1b'), 4.9, 17.8, 0));        // ゴーグル
    return parts;
  }

  const horses = H.map((h) => {
    const ci = Math.floor(rnd() * COATS.length), cp = coatParts[ci];
    const g = new Group(), body = new Group();
    const silk = SILKS[(h.n * 5 + Math.floor(rnd() * 4)) % SILKS.length], cap = (api.FR[h.f] || api.FR[1])[0];
    const fixed = new Mesh(mergeGeometries(cp.fixed.concat(jockey(silk, cap))), horseMat);
    fixed.castShadow = true; body.add(fixed);
    const cm = new MeshStandardMaterial({ map: clothTex(h), roughness: 0.8 });
    const cloth = new Mesh(clothGeo, [whiteMat, whiteMat, whiteMat, whiteMat, cm, cm]);
    cloth.position.set(0.4, 11.8, 0); body.add(cloth);
    // 脚：付け根（up）とひざ・飛節（lo）の2関節
    const legs = [[4.3, 9.4, 1.3, 1], [4.3, 9.4, -1.3, 1], [-4.7, 9.8, 1.45, 0], [-4.7, 9.8, -1.45, 0]].map(([x, y, z, front]) => {
      const up = new Group(), lo = new Group();
      up.position.set(x, y, z);
      const um = new Mesh(front ? cp.fU : cp.hU, horseMat), lm = new Mesh(front ? cp.fL : cp.hL, horseMat);
      um.castShadow = lm.castShadow = true;
      lo.position.y = front ? -4.9 : -5.3;
      up.add(um); lo.add(lm); up.add(lo); body.add(up);
      return { up, lo, front };
    });
    const tail = new Group(); tail.position.set(-7.0, 11.9, 0);
    const tm = new Mesh(cp.tail, horseMat); tm.castShadow = true; tail.add(tm); body.add(tail);
    g.add(body);
    const sp = new Sprite(new SpriteMaterial({ map: badgeTex(h, h.m === '◎'), depthTest: false, transparent: true }));
    sp.scale.set(6.4, 8.8, 1); sp.position.y = 27; sp.renderOrder = 10; g.add(sp);
    scene.add(g);
    return { g, body, legs, tail, sp, phase: rnd() * Math.PI * 2, prev: null, amp: 0 };
  });
  const LEG_PH = [0, 0.55, 3.3, 3.85]; // 襲歩（ギャロップ）の脚の順番

  // ---------- カメラ ----------
  let view = 'tv', snap = true, lastNow = 0, shadowHalf = 0;
  let slowN = 0, slowSum = 0, lite = false, lastW = 0, lastH = 0; // 動きが重い端末では影をやめて軽くする
  const camPos = new Vector3(), camLook = new Vector3();
  function topView() {
    const vf = camera.fov * Math.PI / 180, hf = 2 * Math.atan(Math.tan(vf / 2) * camera.aspect);
    const half = (G.straight ? G.W * 0.5 : G.W * 0.55) + 20;
    const d = Math.max(half / Math.tan(hf / 2), (G.H * 0.62) / Math.tan(vf / 2)) * 1.05;
    const el = G.straight ? 0.9 : 0.95;
    camPos.set(0, d * Math.sin(el), d * Math.cos(el));
    camLook.set(0, 0, G.straight ? (G.top + G.bot) / 2 - H2 : 10);
  }

  function resize() {
    const w = Math.max(280, Math.round(stage.clientWidth || 600));
    const h = Math.round(w < 600 ? Math.max(240, w * 0.66) : Math.max(220, Math.min(460, w * 0.56))); // スマホは少し縦長に
    lastW = w; lastH = h;
    renderer.setPixelRatio(lite ? 1 : Math.min(window.devicePixelRatio || 1, w < 600 ? 1.5 : 2));
    renderer.setSize(w, h, false);
    canvas.style.width = '100%'; canvas.style.height = h + 'px';
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    snap = true;
  }

  function draw(f) {
    const now = performance.now(), raw = lastNow ? (now - lastNow) / 1000 : 0, dt = Math.min(0.05, raw);
    lastNow = now;
    if (f.running && !lite && raw > 0 && raw < 0.5) {
      slowSum += raw; slowN++;
      if (slowN >= 20) {
        if (slowSum / slowN > 0.04) { // 平均25コマ/秒を下回ったら軽い設定へ
          lite = true; sun.castShadow = false; renderer.shadowMap.enabled = false;
          scene.traverse((o) => { if (o.material) [].concat(o.material).forEach((m) => { m.needsUpdate = true; }); });
          renderer.setPixelRatio(1); renderer.setSize(lastW, lastH, false);
        }
        slowSum = 0; slowN = 0;
      }
    }
    // 馬（上からの視点では、見分けやすいように馬と番号を大きくする）
    const big = view === 'top', hs = big ? 1.7 : 1, bs = big ? 2.6 : 1;
    const pack = new Vector3(); let pc = 0, leadU = 0;
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
      hz.legs.forEach((L, j) => {
        const s = Math.sin(ph + LEG_PH[j]), c = Math.max(0, Math.cos(ph + LEG_PH[j])); // c>0 は脚を前へ運んでいる間
        if (L.front) { L.up.rotation.z = a * (0.12 + 0.85 * s); L.lo.rotation.z = -a * 1.35 * c; }
        else { L.up.rotation.z = -0.3 + a * (0.12 + 0.75 * s); L.lo.rotation.z = 0.55 + a * 0.95 * c - a * 0.25; }
      });
      hz.tail.rotation.z = -a * (0.55 + 0.12 * Math.sin(ph * 2)); // 走るほど後ろに流れる
      hz.body.position.y = 0.75 * a * Math.abs(Math.sin(ph));
      hz.body.rotation.z = 0.055 * a * Math.sin(ph + 1.2);
      hz.g.position.copy(tmp);
      hz.g.scale.setScalar(hs);
      hz.sp.scale.set(6.4 * bs, 8.8 * bs, 1);
      hz.g.rotation.y = -Math.atan2(tmp2.z - tmp.z, tmp2.x - tmp.x);
      if (k === 0) leadU = u;
      if (k < 3) { pack.add(tmp); pc++; }
    });
    pack.multiplyScalar(1 / Math.max(1, pc));
    // カメラ
    if (view === 'top') topView();
    else {
      // 中継カメラ：内馬場の側から先頭集団を望遠で追う（外側だとスタンドに隠れるため）。背景にスタンドが映る
      const lane = G.lanes / 2;
      const p = P3(leadU, lane), inward = p.clone().sub(P3(leadU, lane + 1)).normalize(), tan = P3(leadU + 3, lane).sub(p).normalize();
      const dist = camera.aspect < 1.4 ? 172 : 148;
      camPos.copy(pack).addScaledVector(inward, dist).addScaledVector(tan, 16); camPos.y = 30;
      camLook.copy(pack).addScaledVector(tan, -15); camLook.y = 12;
    }
    if (snap || !f.running) { camera.position.copy(camPos); camera.userData.look = camLook.clone(); snap = false; }
    else {
      const k = 1 - Math.exp(-dt * 3.2);
      camera.position.lerp(camPos, k);
      camera.userData.look.lerp(camLook, k);
    }
    camera.lookAt(camera.userData.look);
    // 影：見えている範囲にだけ影の地図を当てる
    const half = big ? 820 : 210, center = big ? tmp.set(0, 0, 0) : camera.userData.look;
    sun.target.position.copy(center);
    sun.position.copy(center).addScaledVector(SUN_DIR, 1200);
    if (half !== shadowHalf) {
      shadowHalf = half;
      const sc = sun.shadow.camera; sc.left = -half; sc.right = half; sc.top = half; sc.bottom = -half; sc.updateProjectionMatrix();
    }
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
