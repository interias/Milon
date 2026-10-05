const assert = require('node:assert/strict');
const { test } = require('node:test');
const { buildPosterSvg } = require('../lib/run-poster.ts');

const route = { activity_id: '1', title: 'Run <script>& "test"', started_at: '2026-10-05T10:00:00', distance_km: 10, duration_seconds: 3672 };
const geometry = { segments: [[{ x: 10, y: 20 }, { x: 30, y: 40 }], [{ x: 50, y: 60 }, { x: 70, y: 80 }]], start: { x: 10, y: 20 }, end: { x: 70, y: 80 } };

test('poster escapes imported text and preserves GPS gaps', () => {
  const svg = buildPosterSvg(route, geometry, 'clinical');
  assert.ok(svg.includes('&lt;script&gt;&amp; &quot;test&quot;'));
  assert.ok(!svg.includes('<script>'));
  assert.ok(svg.includes('M10.00,20.00 L30.00,40.00'));
  assert.ok(svg.includes('M50.00,60.00 L70.00,80.00'));
  assert.ok(!svg.includes('L50.00,60.00'));
  assert.ok(svg.includes('10,00'));
  assert.ok(svg.includes('6:07'));
  assert.ok(svg.includes('1:01:12'));
  assert.ok(svg.includes('05.10.2026'));
});

test('poster embeds only image data and never accepts external or executable illustrations', () => {
  for (const source of ['javascript:alert(1)', 'https://example.org/route.png', 'data:image/svg+xml,<svg/>']) {
    assert.ok(!buildPosterSvg(route, geometry, 'ink', source).includes('<image'));
  }
  assert.ok(buildPosterSvg(route, geometry, 'teal', 'data:image/png;base64,aGVsbG8=').includes('<image'));
});

test('poster leaves absent metrics empty instead of manufacturing zeros', () => {
  const svg = buildPosterSvg({ ...route, distance_km: null, duration_seconds: null }, geometry, 'clinical');
  assert.ok(!svg.includes('NaN') && !svg.includes('Infinity'));
  assert.ok(svg.includes('>–<'));
});

test('long and wide titles are scaled, ellipsized and clipped inside the poster', () => {
  const svg = buildPosterSvg({ ...route, title: 'W'.repeat(80) }, geometry, 'clinical');
  assert.ok(svg.includes('font-size="25.29"'));
  assert.ok(svg.includes('clip-path="url(#title-clip)"'));
  assert.ok(svg.includes(`${'W'.repeat(33)}…</text>`));
});
