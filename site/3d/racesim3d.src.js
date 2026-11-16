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
import { AnimationMixer } from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { clone as cloneSkinned } from 'three/addons/utils/SkeletonUtils.js';

// 毛色：体・たてがみと尾・脚の先
const COATS = [
  { body: '#9a5a30', points: '#1d1612', legs: '#241a15' }, // 鹿毛
  { body: '#b8703c', points: '#a05e30', legs: '#a86434' }, // 栗毛
  { body: '#5e3a26', points: '#16100d', legs: '#1a1310' }, // 黒鹿毛
  { body: '#3a2c26', points: '#120e0c', legs: '#16110f' }, // 青鹿毛
  { body: '#86482a', points: '#733c22', legs: '#783f24' }, // 栃栗毛
  { body: '#c9c8c3', points: '#e3e2dd', legs: '#8d8b86' }, // 芦毛
];
const SILKS = [['#1e4fa8', '#f2c200'], ['#c8102e', '#ffffff'], ['#f2c200', '#111111'], ['#1f8f4a', '#ffffff'], ['#7a2c8f', '#f2c200'],
  ['#f08a24', '#1e4fa8'], ['#111111', '#c8102e'], ['#e9e9e9', '#c8102e'], ['#0f8fa6', '#ffffff'], ['#b5651d', '#f2c200'],
  ['#d14f8f', '#ffffff'], ['#2f4f2f', '#f08a24']];
const Y = new Vector3(0, 1, 0);

export async function create(stage, data, api) {
  const H = data.horses;
  const G = data.straight ? api.geom(1200, 320, data) : api.geom(1200, 600, data);
  G.abreast = true;                 // ゲートでは全頭が横一列に並ぶ
  { // 3Dでは馬1頭ぶんほどの細いレーンにする（コースの幅は変えない）。前があけば次々に内へ寄っていける
    const width = G.lanes * G.laneW;
    G.laneW = 8.6; G.lanes = Math.max(4, Math.floor(width / G.laneW));
  }
  G.coast = G.straight ? 25 : 260;  // ゴール後に流して走る長さ
  const STRIDE = 64;                // 襲歩1完歩で進む長さ（脚の回転を進む速さに合わせて、足が滑って見えないようにする）
  const HQ = /[?&]rsimhq=1/.test(location.search); // 確認用：重くても影を切らない
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
  const finEl = document.createElement('div'); // ゴールした順に 1〜3着 を大きく出す
  finEl.className = 'rsim-fin'; finEl.hidden = true;
  stage.appendChild(finEl);
  let finShown = -1;
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
    const fc = document.createElement('canvas'); fc.width = 32; fc.height = 32;
    const fx = fc.getContext('2d');
    fx.fillStyle = '#ffffff'; fx.fillRect(0, 0, 32, 32); fx.fillStyle = '#111111'; fx.fillRect(0, 0, 16, 16); fx.fillRect(16, 16, 16, 16);
    const wide = a.distanceTo(b);
    const line = new Mesh(new BoxGeometry(wide, 0.1, 5), new MeshBasicMaterial({ map: tex(fc, wide / 5, 1) }));
    line.position.copy(a).add(b).multiplyScalar(0.5); line.position.y = 0.32;
    line.rotation.y = -Math.atan2(b.z - a.z, b.x - a.x);
    // 外側の柱と、コースをまたぐ横断幕
    const o2 = P3(G.Dpx, G.lanes + 0.2), i2 = P3(G.Dpx, -1.3);
    const p2 = new Mesh(new CylinderGeometry(0.6, 0.6, 34, 10), std('#c8102e', { roughness: 0.4 })); p2.position.set(o2.x, 17, o2.z); scene.add(p2);
    const p3 = new Mesh(new CylinderGeometry(0.6, 0.6, 8, 10), std('#c8102e', { roughness: 0.4 })); p3.position.set(i2.x, 30, i2.z); scene.add(p3);
    const bc = document.createElement('canvas'); bc.width = 512; bc.height = 48;
    const bx = bc.getContext('2d');
    bx.fillStyle = '#c8102e'; bx.fillRect(0, 0, 512, 48);
    bx.fillStyle = '#ffffff'; bx.font = '700 34px sans-serif'; bx.textAlign = 'center'; bx.textBaseline = 'middle'; bx.fillText('GOAL', 256, 26);
    const bt = new CanvasTexture(bc); bt.colorSpace = SRGBColorSpace;
    const bm = new MeshBasicMaterial({ map: bt }), red = new MeshBasicMaterial({ color: '#c8102e' });
    const banner = new Mesh(new BoxGeometry(i2.distanceTo(o2), 5, 0.6), [red, red, red, red, bm, bm]);
    banner.position.copy(i2).add(o2).multiplyScalar(0.5); banner.position.y = 31.5;
    banner.rotation.y = -Math.atan2(o2.z - i2.z, o2.x - i2.x);
    scene.add(banner);
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
  // スタートのゲート：1頭ずつの枠（前後の柱）と屋根。馬は枠の中からまっすぐ出る。走り出したら片づける
  const gate = new Group();
  {
    const n = H.length, stepL = n > 1 ? (G.lanes - 0.3) / (n - 1) : 1;
    const gm = std('#e9edf0', { roughness: 0.4, metalness: 0.3 }), gg = std('#1f8f4a');
    const postGeo = new CylinderGeometry(0.45, 0.45, 21.5, 6);
    let first = null, last = null;
    for (let k = 0; k <= n; k++) {
      const lb = -0.35 + (k - 0.5) * stepL;
      for (const u of [-17, 5]) {
        const p = P3(u, lb), post = new Mesh(postGeo, gm);
        post.position.set(p.x, 10.75, p.z); post.castShadow = true; gate.add(post);
      }
      const mid = P3(-6, lb);
      if (k === 0) first = mid; last = mid;
    }
    const roof = new Mesh(new BoxGeometry(first.distanceTo(last) + 2, 1.4, 24), gg);
    roof.position.copy(first).add(last).multiplyScalar(0.5); roof.position.y = 22;
    roof.rotation.y = -Math.atan2(last.z - first.z, last.x - first.x);
    roof.castShadow = true; gate.add(roof);
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

  // ---------- 馬と騎手（racehorse.glb：骨格と走るアニメーション付きのモデルを頭数分だけ複製して色を変える） ----------
  const MODEL_SCALE = 8.2; // モデルはメートル単位。コースの縮尺（1馬身≒17）に合わせる
  const gltf = await new GLTFLoader().loadAsync(new URL('racehorse.glb' + new URL(import.meta.url).search, import.meta.url).href);
  const clip = (name) => gltf.animations.find((a) => a.name === name);
  // ゼッケン：モデルに UV が無いので、左右の面それぞれで数字が正しく読めるように UV を作る
  gltf.scene.traverse((o) => {
    if (!o.isMesh || !o.material || o.material.name !== 'SaddleCloth') return;
    const g = o.geometry, p = g.getAttribute('position');
    g.computeBoundingBox();
    const b = g.boundingBox, w = b.max.x - b.min.x || 1, h = b.max.y - b.min.y || 1, uv = new Float32Array(p.count * 2);
    for (let k = 0; k < p.count; k++) {
      const u = (p.getX(k) - b.min.x) / w;
      uv[k * 2] = p.getZ(k) >= 0 ? u : 1 - u;
      uv[k * 2 + 1] = (p.getY(k) - b.min.y) / h;
    }
    g.setAttribute('uv', new Float32BufferAttribute(uv, 2));
  });
  const rnd = api.rng(api.hashStr((data.id || '') + 'horses'));

  function clothTex(h) {
    const c = document.createElement('canvas'); c.width = 128; c.height = 96;
    const x = c.getContext('2d');
    x.fillStyle = '#f6f6f3'; x.fillRect(0, 0, 128, 96);
    x.strokeStyle = '#1c1c1c'; x.lineWidth = 4; x.strokeRect(3, 3, 122, 90);
    x.fillStyle = '#111111'; x.font = '700 64px sans-serif'; x.textAlign = 'center'; x.textBaseline = 'middle';
    x.fillText(String(h.n), 64, 52);
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

  const horses = H.map((h) => {
    const coat = COATS[Math.floor(rnd() * COATS.length)];
    const silk = SILKS[(h.n * 5 + Math.floor(rnd() * 4)) % SILKS.length], cap = (api.FR[h.f] || api.FR[1])[0];
    const marks = rnd() < 0.5; // 額や脚先の白は半分くらいの馬に
    const paintBy = { Coat: coat.body, Points: coat.legs, ManeTail: coat.points, Silks: silk[0], Sleeves: silk[1], Cap: cap };
    const model = cloneSkinned(gltf.scene);
    model.scale.setScalar(MODEL_SCALE);
    model.traverse((o) => {
      if (!o.isMesh) return;
      o.castShadow = true; o.frustumCulled = false;
      const m = o.material.clone(); o.material = m;
      m.roughness = Math.max(m.roughness, 0.55);
      if (paintBy[m.name]) m.color.set(paintBy[m.name]);
      if (m.name === 'Markings' && !marks) m.color.set(coat.body);
      if (m.name === 'SaddleCloth') { m.color.set('#ffffff'); m.map = clothTex(h); m.roughness = 0.8; }
    });
    const g = new Group(); g.add(model);
    const mixer = new AnimationMixer(model);
    const gallop = mixer.clipAction(clip('Gallop_InPlace')), idle = clip('Idle') ? mixer.clipAction(clip('Idle')) : null;
    const canter = clip('Canter_InPlace') ? mixer.clipAction(clip('Canter_InPlace')) : null;
    gallop.play(); gallop.time = rnd() * gallop.getClip().duration; gallop.setEffectiveWeight(0);
    if (canter) { canter.play(); canter.time = rnd() * canter.getClip().duration; canter.setEffectiveWeight(0); }
    if (idle) { idle.play(); idle.time = rnd() * 2; idle.setEffectiveWeight(1); }
    mixer.update(0);
    const sp = new Sprite(new SpriteMaterial({ map: badgeTex(h, h.m === '◎'), depthTest: false, transparent: true }));
    sp.scale.set(6.4, 8.8, 1); sp.position.y = 26; sp.renderOrder = 10; g.add(sp);
    scene.add(g);
    return { g, sp, model, mixer, gallop, canter, idle, rate: 0.97 + rnd() * 0.06, prev: null, amp: 0, yaw: 0, roll: 0 };
  });

  // ---------- カメラ ----------
  let view = 'tv', snap = true, lastNow = 0, shadowHalf = 0, finClock = -1, wasAtLine = false;
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => '&#' + c.charCodeAt(0) + ';');
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
    if (f.running && !lite && !HQ && raw > 0 && raw < 0.5) {
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
    gate.visible = f.t < 0.1;
    const slow = f.slow || 1;
    f.order.forEach((i, k) => {
      const hz = horses[i], u = f.prog[i], lane = Math.min(f.lane[i], G.lanes - 0.6);
      P3(u, lane, tmp);
      P3(u + 4, lane, tmp2);
      const along = -Math.atan2(tmp2.z - tmp.z, tmp2.x - tmp.x); // コースに沿った向き
      // 実際に動いた向きと速さ（位置が大きく飛んだとき＝走り直しのときは、止まっている扱いにする）
      let speed = 0, heading = along, jumped = !hz.prev;
      if (hz.prev && dt > 0) {
        const dx = tmp.x - hz.prev.x, dz = tmp.z - hz.prev.z, d = Math.hypot(dx, dz);
        if (d > 60) jumped = true;
        else { speed = d / dt; if (speed > f.vref * 0.15) heading = -Math.atan2(dz, dx); }
      }
      hz.prev = (hz.prev || new Vector3()).copy(tmp);
      // 向き：進む方向へなめらかに向ける（進路を変えるときは体ごと斜めに向く）。曲がるときは内側へ体を倒す
      if (jumped) { hz.yaw = along; hz.roll = 0; hz.amp = 0; }
      else {
        let dy = heading - hz.yaw; dy = Math.atan2(Math.sin(dy), Math.cos(dy));
        const turn = dy * (1 - Math.exp(-dt * 7));
        hz.yaw += turn;
        const lean = dt > 0 ? Math.max(-0.16, Math.min(0.16, -0.17 * turn / dt)) : 0;
        hz.roll += (lean - hz.roll) * Math.min(1, dt * 4);
      }
      hz.model.rotation.x = hz.roll;
      // 走り方：速さに応じて 立ち姿 → 駈歩 → 襲歩 をなめらかに混ぜ、脚の回転は進む速さに合わせる
      const a = Math.min(1.2, speed / Math.max(1, f.vref * slow));
      hz.amp += (a - hz.amp) * Math.min(1, dt * 5);
      const wg = api.smooth(0.5, 0.85, hz.amp), wc = hz.canter ? api.smooth(0.1, 0.38, hz.amp) * (1 - wg) : 0;
      hz.gallop.setEffectiveWeight(hz.canter ? wg : api.smooth(0.1, 0.6, hz.amp));
      if (hz.canter) hz.canter.setEffectiveWeight(wc);
      if (hz.idle) hz.idle.setEffectiveWeight(Math.max(0, 1 - wg - wc));
      const v = hz.amp * f.vref;
      hz.gallop.timeScale = hz.rate * Math.max(0.6, Math.min(1.3, v / STRIDE * hz.gallop.getClip().duration));
      if (hz.canter) hz.canter.timeScale = hz.rate * Math.max(0.6, Math.min(1.25, v / (STRIDE * 0.55) * hz.canter.getClip().duration));
      hz.mixer.update(dt * slow);
      hz.g.position.copy(tmp);
      hz.g.scale.setScalar(hs);
      hz.sp.scale.set(6.4 * bs, 8.8 * bs, 1);
      hz.g.rotation.y = hz.yaw;
      if (k === 0) leadU = u;
      if (k < 3) { pack.add(tmp); pc++; }
    });
    pack.multiplyScalar(1 / Math.max(1, pc));
    // カメラ
    // ゴール前（残り約150m）から1着が入って少しの間は、ゴール板の先の内側に据えたカメラで正面から迎える
    if (f.t <= 0) finClock = -1;
    if (f.fin.length && finClock < 0) finClock = f.clock;
    const atLine = f.running && view !== 'top' && leadU > G.Dpx * (1 - 150 / data.dist) && (finClock < 0 || f.clock - finClock < 2.6);
    if (atLine !== wasAtLine) { wasAtLine = atLine; snap = true; }
    if (view === 'top') topView();
    else if (atLine) {
      P3(G.Dpx + 62, -4.5, camPos); camPos.y = 15;
      P3(G.Dpx - 30, G.lanes * 0.32, camLook); camLook.y = 9;
    }
    else {
      // 中継カメラ：内馬場の側から先頭集団を望遠で追う（外側だとスタンドに隠れるため）。背景にスタンドが映る
      const lane = G.lanes / 2;
      const p = P3(leadU, lane), inward = p.clone().sub(P3(leadU, lane + 1)).normalize(), tan = P3(leadU + 3, lane).sub(p).normalize();
      const dist = camera.aspect < 1.4 ? 150 : 124;
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
    const shown = Math.min(3, f.fin.length);
    if (shown !== finShown) {
      finShown = shown;
      finEl.hidden = !shown;
      finEl.innerHTML = shown ? '<b>ゴール！</b>' + f.fin.slice(0, 3).map((i, k) => {
        const h = H[i], c = api.FR[h.f] || api.FR[1];
        return '<span>' + (k + 1) + '着 <i style="background:' + c[0] + ';color:' + c[1] + '">' + h.n + '</i> ' + esc(h.name) + '</span>';
      }).join('') : '';
    }
    if (hudI.textContent !== f.info) hudI.textContent = f.info;
    const l = f.t > 0 ? f.line : '';
    if (hudL.textContent !== l) hudL.textContent = l;
  }

  return {
    kind: '3d',
    geom: () => G,
    resize,
    draw,
    show(on) { canvas.style.display = on ? '' : 'none'; hud.style.display = on ? '' : 'none'; finEl.style.display = on ? '' : 'none'; },
    setView(v) { view = v === 'top' ? 'top' : 'tv'; snap = true; },
  };
}
