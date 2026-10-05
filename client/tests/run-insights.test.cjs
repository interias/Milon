const assert = require('node:assert/strict');
const { test } = require('node:test');
const { timedRoute, routePosition, comparisonSegments } = require('../lib/run-insights.ts');

const point = (time) => ({ lat: 48, lon: 10, altitude_m: null, time });

test('route cursor aligns exact UTC start across offset timestamps', () => {
  const segments = [[point('2026-10-05T10:00:00+02:00'), point('2026-10-05T08:00:10Z')]];
  const timeline = timedRoute(segments, [[{ x: 0, y: 20 }, { x: 10, y: 40 }]], '2026-10-05T08:00:00Z');
  assert.deepEqual(routePosition(timeline, 5), { x: 5, y: 30 });
  assert.equal(routePosition(timeline, -1), null);
  assert.equal(routePosition(timeline, 11), null);
  assert.deepEqual(timedRoute(segments, [[]], '2026-10-05T10:00:00'), []);
});

test('route cursor never crosses segment boundaries, missing times or recording gaps', () => {
  const segments = [[point('2026-10-05T08:00:00Z'), point(null), point('2026-10-05T08:00:20Z')], [point('2026-10-05T08:00:25Z'), point('2026-10-05T08:02:00Z')]];
  const timeline = timedRoute(segments, [[{ x: 0, y: 0 }, { x: 10, y: 10 }, { x: 20, y: 20 }], [{ x: 25, y: 25 }, { x: 120, y: 120 }]], '2026-10-05T08:00:00Z');
  for (const time of [10, 22, 50]) assert.equal(routePosition(timeline, time), null);
  assert.deepEqual(routePosition(timeline, 25), { x: 25, y: 25 });
});

test('comparison lines break at pauses, invalid sensors and repeated distances', () => {
  const points = [
    { distance_m: 0, hr_bpm: 120 }, { distance_m: 10, hr_bpm: 121 },
    { distance_m: 10, hr_bpm: 130 }, { distance_m: 20, hr_bpm: null },
    { distance_m: 30, hr_bpm: 125 }, { distance_m: 40, hr_bpm: 126, gap: true },
  ];
  assert.deepEqual(comparisonSegments(points, point => point.hr_bpm), [
    [{ distance: 0, value: 120 }, { distance: 10, value: 121 }],
    [{ distance: 10, value: 130 }], [{ distance: 30, value: 125 }], [{ distance: 40, value: 126 }],
  ]);
});
