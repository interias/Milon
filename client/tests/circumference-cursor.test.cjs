const assert = require('node:assert/strict');
const { test } = require('node:test');
const { measurementCursorDate, measurementStamp, measurementStats } = require('../lib/circumferences.ts');

test('shared date cursor snaps to real dates and clamps at recording boundaries', () => {
  const dates = ['2026-09-27', '2026-10-04', '2026-10-11'];
  assert.equal(measurementCursorDate(dates, measurementStamp('2026-10-02')), '2026-10-04');
  assert.equal(measurementCursorDate(dates, measurementStamp('2026-01-01')), dates[0]);
  assert.equal(measurementCursorDate(dates, measurementStamp('2027-01-01')), dates[2]);
  assert.equal(measurementCursorDate([], 0), null);
  assert.equal(measurementCursorDate(dates, NaN), null);
});

test('a shared date does not invent missing values or include unknown measurement sites', () => {
  const definitions = [{ key: 'waist' }, { key: 'arm' }];
  const stats = measurementStats(definitions, [
    { date: '2026-10-01', protocol: 'standard', values: { waist: 80, arm: 36 } },
    { date: '2026-10-04', protocol: 'standard', values: { waist: 79 } },
    { date: '2026-10-05', protocol: 'unknown', values: { arm: 39 } },
  ], { start: '2026-10-01', end: '2026-10-05' });
  const dates = [...new Set(stats.flatMap(stat => stat.points.map(point => point.date)))].sort();
  const date = measurementCursorDate(dates, measurementStamp('2026-10-05'));
  assert.equal(date, '2026-10-04');
  assert.equal(stats[1].points.find(point => point.date === date), undefined);
});
