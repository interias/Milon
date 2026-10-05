const assert = require('node:assert/strict');
const { test } = require('node:test');
const { addedSyncItems, syncFeedbackText, readSyncFeedback, captureSyncInventory, finishManualSync, FEEDBACK_LIFETIME } = require('../lib/sync-feedback.ts');
const empty = () => ({ runs: [], nights: [], workouts: [], weights: [], nutrition: [] });
const item = (id, date = '2026-10-04', href = '/laufen') => ({ id, date, href });

test('sync delta counts stable identities once, ignoring rewrites and removals', () => {
  const before = { ...empty(), runs: [item('existing'), item('deleted')] };
  const after = { ...empty(), runs: [item('new'), item('existing', '2026-10-05', '/laufen/123'), item('new')] };
  const result = addedSyncItems(before, after, 123);
  assert.deepEqual(result.runs, [item('new')]);
  assert.equal(result.createdAt, 123);
  assert.equal(syncFeedbackText(result), '1 Lauf ergänzt');
  assert.equal(syncFeedbackText(addedSyncItems(after, after)), 'Daten aktualisiert · keine neuen Einträge');
});

test('new data is ordered newest first and represented by actual calendar days', () => {
  const result = addedSyncItems(empty(), { ...empty(), nights: [item('a'), item('b', '2026-10-05')], weights: [item('weight')] });
  assert.equal(result.nights[0].id, 'b');
  assert.equal(syncFeedbackText(result), '2 Nächte · 1 Wiegetag ergänzt');
});

test('stored feedback expires and cannot supply external navigation targets', () => {
  let value = { ...empty(), createdAt: Date.now(), runs: [item('new')] };
  global.window = {};
  global.sessionStorage = { getItem: () => JSON.stringify(value) };
  try {
    assert.equal(readSyncFeedback().runs[0].id, 'new');
    value.createdAt = Date.now() - FEEDBACK_LIFETIME;
    assert.equal(readSyncFeedback(), null);
    value.createdAt = Date.now() + FEEDBACK_LIFETIME;
    assert.equal(readSyncFeedback(), null);
    value.createdAt = Date.now();
    value.runs[0].href = '//external.example';
    assert.equal(readSyncFeedback(), null);
  } finally { delete global.window; delete global.sessionStorage; }
});

test('unavailable or incompatible inventory never blocks refresh notifications', async () => {
  const original = global.fetch;
  const events = [];
  global.fetch = async () => new Response(JSON.stringify({ runs: null }), { status: 200 });
  global.window = { dispatchEvent: event => events.push(event) };
  global.sessionStorage = { removeItem: () => {} };
  try {
    assert.equal(await captureSyncInventory(), null);
    assert.equal(await finishManualSync(empty()), 'Daten aktualisiert.');
    assert.deepEqual(events.map(event => event.type), ['milon:sync-feedback', 'milon:data-refresh']);
    assert.equal(events[0].detail, null);
    assert.equal(events[1].detail.source, 'manual-sync');
  } finally { global.fetch = original; delete global.window; delete global.sessionStorage; }
});
