// site/racesim.js の計算部分のテスト。実行: node --test tests/racesim.test.js
const test = require('node:test');
const assert = require('node:assert');
const S = require('../site/racesim.js');

function field(n, dist) {
  const horses = [];
  for (let i = 0; i < n; i++) horses.push({ n: i + 1, name: 'H' + (i + 1), f: 1, m: '', p: 100 / n, s: i / Math.max(1, n - 1) });
  return { id: 'x', dist, surface: 'ダ', dir: 'R', straight: false, lap: 1600, home: 300, horses, result: [] };
}

test('rng は同じ seed で同じ列を返す', () => {
  const a = S.rng(42), b = S.rng(42);
  for (let i = 0; i < 5; i++) assert.strictEqual(a(), b());
});

test('plOrder は全頭を1回ずつ並べる', () => {
  const o = S.plOrder([5, 1, 1, 3], S.rng(1));
  assert.deepStrictEqual([...o].sort(), [0, 1, 2, 3]);
  assert.strictEqual(S.plOrder([5, 1, 1, 3], S.rng(1), 2).length, 2);
});

test('tally の1着回数は勝率×1000に近く、同じ seed で同じ', () => {
  const ws = [50, 30, 15, 5];
  const t1 = S.tally(ws, 1000, S.hashStr('race-1'));
  const t2 = S.tally(ws, 1000, S.hashStr('race-1'));
  assert.deepStrictEqual(t1, t2);
  ws.forEach((w, i) => assert.ok(Math.abs(t1[i].win - w * 10) <= 40, `馬${i}: ${t1[i].win}`));
  assert.strictEqual(t1.reduce((s, x) => s + x.win, 0), 1000);
  assert.strictEqual(t1.reduce((s, x) => s + x.top3, 0), 3000);
  t1.forEach((x) => assert.ok(x.top3 >= x.win));
});

test('2頭立てでも tally が壊れない', () => {
  const t = S.tally([60, 40], 1000, 7);
  assert.strictEqual(t[0].top3 + t[1].top3, 2000);
});

for (const [n, dist] of [[18, 3600], [10, 1200], [2, 1000]]) {
  test(`plan：${n}頭・${dist}m で t<1 に誰もゴールせず、決めた着順どおりにゴールする`, () => {
    const d = field(n, dist);
    const P = S.plan(d, S.rng(3));
    assert.strictEqual(P.order.length, n);
    for (let t = 0; t < 1; t += 0.01) {
      P.h.forEach((h) => assert.ok(S.gapAt(h, t, P) >= 0));
    }
    // t>=1 では差は最終の差に固定。差の小さい順＝ゴール順
    const fin = P.h.map((h, i) => ({ i, g: S.gapAt(h, 1, P) }));
    assert.strictEqual(fin[P.order[0]].g, 0);
    const byGap = fin.slice().sort((a, b) => a.g - b.g).map((x) => x.i);
    assert.deepStrictEqual(byGap, P.order);
    P.h.forEach((h) => assert.strictEqual(S.gapAt(h, 1.05, P), S.gapAt(h, 1, P)));
  });
}

test('plan の序盤は脚質の前の馬ほど前にいる（おおむね）', () => {
  const d = field(12, 2000);
  let ok = 0;
  for (let s = 0; s < 50; s++) {
    const P = S.plan(d, S.rng(100 + s));
    const t = P.r0 + 0.05;
    if (S.gapAt(P.h[0], t, P) < S.gapAt(P.h[11], t, P)) ok++;
  }
  assert.ok(ok >= 45, `${ok}/50`);
});
