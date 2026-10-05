const assert = require('node:assert/strict');
const { test } = require('node:test');
const { buildMonthlySvg } = require('../lib/monthly-recap.ts');
const data = { month: '2026-09', to_date: '2026-09-30', partial: false, running_km: 41.3, runs: 4, strength_sessions: 12, training_days: 15, weight_delta_kg: -1.2, route_count: 1, routes: [{ activity_id: '1', contour: [[[0,0],[100,50]],[[110,60],[200,200]]] }] };
test('recap preserves separate GPS segments and static export', () => {
  const svg = buildMonthlySvg(data, '', false);
  assert.ok(svg.includes('September 2026') && svg.includes('41,3'));
  assert.ok(svg.includes('M110.00,60.00') && !svg.includes('L110.00,60.00'));
  assert.ok(!svg.includes('@keyframes') && !svg.includes('Gewichtsverlauf'));
  assert.ok(svg.includes('15 erfasste Trainingstage'));
});
test('animation is preview-only and respects reduced motion', () => {
  const svg = buildMonthlySvg(data, '', true, true);
  assert.ok(svg.includes('220ms') && svg.includes('prefers-reduced-motion:reduce'));
  assert.ok(svg.includes('-1,2 kg · Gewichtsverlauf'));
});
test('recap clearly marks partial months and bounds visible contours without changing totals', () => {
  const svg = buildMonthlySvg({ ...data, partial: true, routes: Array(20).fill(data.routes[0]), route_count: 20 }, 'https://remote.example/image.png', false);
  assert.ok(svg.includes('Zwischenstand') && svg.includes('12 von 20 GPS-Aufzeichnungen'));
  assert.ok(!svg.includes('<image') && svg.includes('41,3'));
});
