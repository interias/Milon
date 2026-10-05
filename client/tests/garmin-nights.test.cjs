const assert = require('node:assert/strict');
const { test } = require('node:test');
const { nightClock, nightWallHour, nightValue } = require('../lib/garmin-nights.ts');

test('night clock uses configured timezone instead of the viewing device timezone', () => {
  assert.equal(nightClock('2026-10-04T21:30:00Z', 'Europe/Berlin'), '23:30');
  assert.equal(nightClock('2026-10-25T00:30:00Z', 'Europe/Berlin'), '02:30');
  assert.equal(nightClock('2026-10-25T01:30:00Z', 'Europe/Berlin'), '02:30');
});

test('rhythm bars preserve local start before midnight across leap day and DST', () => {
  assert.equal(nightWallHour('2028-02-28T23:30:00+01:00', '2028-02-29'), -.5);
  assert.equal(nightWallHour('2026-10-24T23:00:00+02:00', '2026-10-25'), -1);
  assert.equal(nightWallHour('2026-10-25T07:00:00+01:00', '2026-10-25'), 7);
});

test('shared cursor returns actual nearby observations and never fills a recording gap', () => {
  const series = { segments: [ [{ seconds: 0, value: 50 }, { seconds: 120, value: 52 }], [{ seconds: 600, value: 60 }] ] };
  assert.equal(nightValue(series, 90), 52);
  assert.equal(nightValue(series, 300), null);
  assert.equal(nightValue(series, -1), null);
  assert.equal(nightValue(series, 601), null);
  assert.equal(nightValue(series, 600), 60);
});
