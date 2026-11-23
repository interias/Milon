const assert = require('node:assert/strict');
const { test } = require('node:test');
const { watchScale, withChecksum, QN_EPOCH_OFFSET } = require('../lib/scale/qnScale.ts');

globalThis.document = { hidden: false };

class Target {
  constructor() { this.l = {}; }
  addEventListener(t, f) { (this.l[t] ??= []).push(f); }
  removeEventListener(t, f) { this.l[t] = (this.l[t] || []).filter((x) => x !== f); }
  emit(t, e) { (this.l[t] || []).slice().forEach((f) => f(e)); }
  count(t) { return (this.l[t] || []).length; }
}
const uuid = (n) => `0000${n.toString(16)}-0000-1000-8000-00805f9b34fb`;

// Simulated CS20L: asleep for the first connects, then handshake → empty memory → the weighing lands in memory.
function fakeScale({ asleep = 2, weighAfterPolls = 1 } = {}) {
  const device = new Target();
  device.name = 'QN-Scale';
  const notify = new Target();
  Object.assign(notify, { uuid: uuid(0xfff1), properties: { notify: true } });
  const writes = [];
  let attempts = 0, polls = 0;
  const send = (bytes) => setTimeout(() => notify.emit('characteristicvaluechanged',
    { target: { value: { buffer: Uint8Array.from(bytes).buffer } } }), 1);
  const write = {
    uuid: uuid(0xfff2), properties: { write: true },
    async writeValueWithResponse(d) {
      writes.push(d[0]);
      if (d[0] === 0x13) send([0x14, 0x0b, 0xff, 1, 0, 1, 9, 3, 0, 0, 0x2c]);
      if (d[0] === 0x20) send([0x21, 0x05, 0xff, 0x01, 0x26]);
      if (d[0] === 0x22) {
        if (polls++ < weighAfterPolls) send(withChecksum([0x23, 0x14, 0xff, ...new Array(16).fill(0), 0]));
        else {
          const t = Math.floor(Date.now() / 1000) - QN_EPOCH_OFFSET;
          send(withChecksum([0x23, 0x14, 0xff, 1, 1, 0xf0, t & 255, (t >> 8) & 255, (t >> 16) & 255, (t >>> 24) & 255,
            0x1c, 0x93, 0, 0xf4, 0x01, 0xe0, 0x01, 0, 0, 0]));
        }
      }
    },
  };
  notify.startNotifications = async () => { send([0x12, 0x12, 0xff, 0x9f, 0x35, 5, 0, 5, 0xff, 0x12, 7, 0x15, 0, 1, 5, 0x9f, 0x32, 5]); };
  const server = {
    async getPrimaryService(u) {
      if (u !== uuid(0xfff0)) throw new Error('no service');
      return { getCharacteristics: async () => [notify, write] };
    },
  };
  device.gatt = {
    connected: false,
    async connect() {
      attempts++;
      if (attempts <= asleep) throw new Error('Waage schläft');
      this.connected = true; polls = 0;
      return server;
    },
    disconnect() { if (this.connected) { this.connected = false; device.emit('gattserverdisconnected'); } },
  };
  return { device, notify, writes, attempts: () => attempts };
}

test('stand-by reconnects when the scale wakes and saves the weighing from its memory', async () => {
  const scale = fakeScale();
  const readings = [];
  const states = [];
  await new Promise((resolve) => {
    const stop = watchScale(scale.device, {
      retryMs: 5, cooldownMs: 5,
      onState: (s) => states.push(s),
      onReading: (r) => { readings.push(r); if (readings.length === 2) { stop(); resolve(); } },
    });
  });
  await new Promise((r) => setTimeout(r, 400)); // let the delayed disconnect run
  assert.equal(scale.attempts(), 4); // 2× asleep, then two weighings
  assert.deepEqual(readings.map((r) => [r.weightKg, r.source]), [[73.15, 'stored'], [73.15, 'stored']]);
  assert.ok(states.includes('waiting') && states.includes('connecting') && states.includes('measuring'));
  // one config per connection: no handler survives from the first session
  assert.equal(scale.writes.filter((op) => op === 0x13).length, 2);
  assert.equal(scale.notify.count('characteristicvaluechanged'), 0);
  assert.equal(scale.device.count('gattserverdisconnected'), 0);
});
