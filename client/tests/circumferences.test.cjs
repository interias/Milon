const assert = require('node:assert/strict');
const { test } = require('node:test');
const {
  measurementBounds, measurementStats, measurementSegments, measurementMonths,
} = require('../lib/circumferences.ts');

const definitions = [{ key: 'abdomen_navel', name: 'Bauch' }, { key: 'upper_arm_right', name: 'Oberarm' }];
const entry = (id, date, values, protocol = 'standard') => ({ id, date, values, protocol });

test('calendar windows clamp month ends and use today only without comparable records', () => {
  assert.deepEqual(measurementBounds([], '1m', '2026-03-31'), { start: '2026-02-28', end: '2026-03-31' });
  assert.deepEqual(measurementBounds([], '12m', '2024-02-29'), { start: '2023-02-28', end: '2024-02-29' });
  const entries = [entry(1, '2025-11-30', { abdomen_navel: 90 }), entry(2, '2026-03-31', { abdomen_navel: 88 }, 'unknown')];
  assert.deepEqual(measurementBounds(entries, '3m', '2026-04-01'), { start: '2025-08-30', end: '2025-11-30' });
});

test('all-history bounds exclude unknown protocols', () => {
  const entries = [entry(1, '2026-06-01', { abdomen_navel: 86 }), entry(2, '2020-01-01', { abdomen_navel: 97 }, 'unknown'), entry(3, '2026-01-01', { abdomen_navel: 90 })];
  assert.deepEqual(measurementBounds(entries, 'all', '2026-07-01'), { start: '2026-01-01', end: '2026-06-01' });
});

test('differences use actual first and last observations per measure within the window', () => {
  const entries = [
    entry(1, '2026-04-01', { abdomen_navel: 86, upper_arm_right: 37 }),
    entry(2, '2026-02-01', { abdomen_navel: 90 }),
    entry(3, '2026-03-01', { upper_arm_right: 36 }),
    entry(4, '2026-03-15', { abdomen_navel: 140 }, 'unknown'),
    entry(5, '2025-01-01', { abdomen_navel: 99 }),
  ];
  const [belly, arm] = measurementStats(definitions, entries, { start: '2026-01-01', end: '2026-04-01' });
  assert.equal(belly.count, 2);
  assert.equal(belly.delta, -4);
  assert.equal(belly.first.date, '2026-02-01');
  assert.equal(arm.delta, 1);
  assert.equal(arm.first.date, '2026-03-01');
  assert.ok(Math.abs(arm.percent - 100 / 36) < 1e-10);
});

test('empty and single observations do not create differences', () => {
  const [belly, arm] = measurementStats(definitions, [entry(1, '2026-04-01', { abdomen_navel: 86 })], { start: '2026-01-01', end: '2026-04-01' });
  assert.equal(belly.delta, null);
  assert.equal(belly.percent, null);
  assert.equal(arm.first, null);
  assert.equal(arm.last, null);
  assert.equal(arm.delta, null);
});

test('chart gaps beyond two weeks stay disconnected', () => {
  const points = ['2026-01-01', '2026-01-15', '2026-01-30', '2026-02-06'].map(date => ({ date, value: 90 }));
  assert.deepEqual(measurementSegments(points).map(segment => segment.length), [2, 2]);
  assert.deepEqual(measurementSegments([]), []);
});

test('month journal uses the last real measurement without filling missing months', () => {
  const bounds = { start: '2026-01-01', end: '2026-03-31' };
  const stats = measurementStats(definitions, [
    entry(1, '2026-01-03', { abdomen_navel: 91 }),
    entry(2, '2026-01-28', { abdomen_navel: 90 }),
    entry(3, '2026-03-04', { abdomen_navel: 88 }),
  ], bounds);
  const months = measurementMonths(stats, bounds);
  assert.equal(months.length, 3);
  assert.equal(months[0].values[0].point.date, '2026-01-28');
  assert.equal(months[0].values[0].delta, -1);
  assert.equal(months[1].values[0].point, null);
  assert.equal(months[2].values[0].delta, -3);
  assert.equal(months[2].values[1].point, null);
});
