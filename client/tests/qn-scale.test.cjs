const assert = require('node:assert/strict');
const { test } = require('node:test');
const { hex, parseInfoFrame, parseLiveFrame, parseStoredFrame, withChecksum } = require('../lib/scale/qnScale.ts');

const frame = (...bytes) => Uint8Array.from(bytes);

test('checksum is the sum of all previous bytes & 0xff, written into the last byte', () => {
  assert.equal(hex(withChecksum([0x1f, 0x05, 0xff, 0x10, 0x00])), '1f 05 ff 10 33');
  assert.equal(hex(withChecksum([0x22, 0x06, 0x01, 0x00, 0x03, 0x00])), '22 06 01 00 03 2c');
  const big = withChecksum([0xff, 0xff, 0xff, 0]);
  assert.equal(big[3], 0xfd);
});

test('info frame picks the weight factor from byte 10', () => {
  assert.equal(parseInfoFrame(frame(0x12, 0x0b, 0xff, 0, 0, 0, 0, 0, 0, 0, 0x01), 10), 100);
  assert.equal(parseInfoFrame(frame(0x12, 0x0b, 0xff, 0, 0, 0, 0, 0, 0, 0, 0x00), 100), 10);
  assert.equal(parseInfoFrame(frame(0x12, 0x05, 0xff, 0, 0), 10), 10); // too short: keep
});

test('old layout: 10 0b <pt> 1b 58 01 … → 70.00 kg at /100, stable, big-endian resistances', () => {
  const d = withChecksum([0x10, 0x0b, 0xff, 0x1b, 0x58, 0x01, 0x01, 0xf4, 0x01, 0xe0, 0]);
  const f = parseLiveFrame(d, 100, 0xff);
  assert.deepEqual(f, { stable: true, kg: 70, r1: 500, r2: 480, newLayout: false });
  const moving = parseLiveFrame(frame(0x10, 0x0b, 0xff, 0x1b, 0x58, 0x00, 0, 0, 0, 0, 0), 100, 0xff);
  assert.equal(moving.stable, false);
  assert.equal(moving.kg, 70);
});

test('old layout with a too short frame is ignored', () => {
  assert.equal(parseLiveFrame(frame(0x10, 0x09, 0xff, 0x1b, 0x58, 0x01, 0, 0, 0), 100, 0xff), null);
});

test('range correction divides by 10 once when the factor gives > 250 or <= 5 kg', () => {
  // 7000 raw at /10 in the old layout (d[4] > 2) → 700 kg → 70 kg
  const f = parseLiveFrame(frame(0x10, 0x0b, 0x01, 0x1b, 0x58, 0x01, 0, 0, 0, 0, 0), 10, 0x01);
  assert.equal(f.newLayout, false);
  assert.equal(f.kg, 70);
});

test('new layout (ES-30M-like): [4]=state [5,6]=weight /10 [7..10]=resistances', () => {
  const d = withChecksum([0x10, 0x0e, 0x01, 0x01, 0x02, 0x02, 0xbc, 0x01, 0xf4, 0x01, 0xe0, 0, 0, 0]);
  assert.deepEqual(parseLiveFrame(d, 10, 0x01), { stable: true, kg: 70, r1: 500, r2: 480, newLayout: true });
  // state 1 counts as stable except for protocol type 0xff
  const s1 = frame(0x10, 0x0e, 0xff, 0x01, 0x01, 0x02, 0xbc, 0, 0, 0, 0, 0);
  assert.equal(parseLiveFrame(s1, 10, 0x01).stable, true);
  assert.equal(parseLiveFrame(s1, 10, 0xff).stable, false);
  // state 0 = still measuring
  assert.equal(parseLiveFrame(frame(0x10, 0x0e, 0x01, 0x01, 0x00, 0x02, 0xbc, 0, 0, 0, 0, 0), 10, 0x01).stable, false);
});

test('stored record: weight big-endian /100, time and resistances little-endian', () => {
  const t = 849_000_000; // QN epoch seconds
  const d = withChecksum([0x23, 0x13, 0x01, 0, 0, 0,
    t & 0xff, (t >>> 8) & 0xff, (t >>> 16) & 0xff, (t >>> 24) & 0xff,
    0x1c, 0x93, 0x00, 0xf4, 0x01, 0xe0, 0x01, 0, 0]);
  assert.deepEqual(parseStoredFrame(d), { kg: 73.15, recTime: t, r1: 500, r2: 480 });
  assert.equal(parseStoredFrame(frame(0x23, 0x05, 0x01, 0, 0)), null);
});
