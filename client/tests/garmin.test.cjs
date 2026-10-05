const assert = require('node:assert/strict');
const { test } = require('node:test');
const { activitySegments, nearestActivityPoint, paceSeconds, paceLabel } = require('../lib/garmin.ts');

const point = (elapsed_seconds, hr_bpm, gap = false) => ({ elapsed_seconds, hr_bpm, gap });

test('missing sensor data and recording gaps never join chart lines', () => {
  const points = [point(0, 120), point(1, 121), point(2, null), point(3, 124), point(12, 132, true), point(13, 133)];
  assert.deepEqual(activitySegments(points, p => p.hr_bpm), [
    [{ time: 0, value: 120 }, { time: 1, value: 121 }],
    [{ time: 3, value: 124 }],
    [{ time: 12, value: 132 }, { time: 13, value: 133 }],
  ]);
});

test('stationary and missing speeds produce gaps, while slow pace remains inspectable', () => {
  assert.equal(paceSeconds(0), null);
  assert.equal(paceSeconds(null), null);
  assert.equal(paceSeconds(-1), null);
  assert.equal(paceSeconds(0.5), 2000);
  assert.equal(paceSeconds(2.5), 400);
  assert.equal(paceLabel(359.8), '6:00');
  assert.equal(paceLabel(null), '–');
});

test('shared cursor resolves uneven recording times and clamps to endpoints', () => {
  const points = [point(0, 120), point(1, 121), point(20, 130), point(21, 129)];
  assert.equal(nearestActivityPoint(points, -50), 0);
  assert.equal(nearestActivityPoint(points, 12), 2);
  assert.equal(nearestActivityPoint(points, 8), 1);
  assert.equal(nearestActivityPoint(points, 200), 3);
  assert.equal(nearestActivityPoint([], 0), null);
});
