/**
 * qnScale.ts – Web Bluetooth driver for Chipsea/Yolanda "QN-Scale" body-composition scales
 * (Arboleaf CS20x family, FITINDEX, Renpho ES-30M, GE Fit Plus …).
 *
 * Works in Chrome on Android (secure context: HTTPS or localhost).
 * Must be started from a user gesture (button click) because of requestDevice().
 *
 * Flow:
 *   scale → 0x12 (info, weight factor)   → we send 0x13 (unit config) + 0x02 (time)
 *   scale → 0x14 (ack)                    → we send 0x20 (time sync)
 *   scale → 0x21 (newer firmware)         → we send 2× 0xA0 + 0x22 (history query)
 *   scale → 0x10 (live weight, stable flag + resistances)  → result
 *   scale → 0x23 (stored record)                              → result (fallback)
 *
 * Milon: frame parsing lives in the pure functions parseInfoFrame / parseLiveFrame /
 * parseStoredFrame (unit-tested in tests/qn-scale.test.cjs); behaviour is unchanged.
 */

export interface ScaleReading {
  weightKg: number;
  /** Raw resistance values as sent by the scale (unit depends on firmware, see note). */
  r1: number;
  r2: number;
  source: "live" | "stored";
  protocolType: number;
  timestamp: string; // ISO, measured on the phone
  rawHex: string;
}

export interface QnScaleOptions {
  onLiveWeight?: (kg: number) => void;
  onLog?: (line: string) => void;
  /** If true, the device chooser shows every BLE device (for first-time discovery). */
  acceptAllDevices?: boolean;
  unit?: "kg" | "lb";
  timeoutMs?: number;
}

const u16 = (n: number) => `0000${n.toString(16).padStart(4, "0")}-0000-1000-8000-00805f9b34fb`;

const SVC_T1 = u16(0xffe0);
const CHR_T1_NOTIFY = u16(0xffe1);
const CHR_T1_INDICATE = u16(0xffe2);
const CHR_T1_CONFIG = u16(0xffe3);
const CHR_T1_TIME = u16(0xffe4);
const SVC_T2 = u16(0xfff0);
const CHR_T2_NOTIFY = u16(0xfff1);
const CHR_T2_WRITE = u16(0xfff2);
const SVC_AE00 = u16(0xae00);
const SVC_DEVINFO = u16(0x180a);
const SVC_BATTERY = u16(0x180f);

/** Vendor epoch offset used by QN firmware (seconds, see openScale QNHandler). */
export const QN_EPOCH_OFFSET = 946_702_800;

export const hex = (b: Uint8Array) => Array.from(b, (x) => x.toString(16).padStart(2, "0")).join(" ");
const be16 = (a: number, b: number) => (a << 8) | b;
const le16 = (a: number, b: number) => a | (b << 8);
const le32 = (a: number, b: number, c: number, d: number) => (a | (b << 8) | (c << 16) | (d << 24)) >>> 0;

export function withChecksum(bytes: number[]): Uint8Array {
  const out = Uint8Array.from(bytes);
  let s = 0;
  for (let i = 0; i < out.length - 1; i++) s = (s + out[i]) & 0xff;
  out[out.length - 1] = s;
  return out;
}

function qnNow(): number {
  return Math.floor(Date.now() / 1000) - QN_EPOCH_OFFSET;
}

/** 0x12 scale info: byte[10] == 1 → weight /100, otherwise /10; short frame keeps the current factor. */
export function parseInfoFrame(d: Uint8Array, weightFactor: number): number {
  return d.length > 10 ? (d[10] === 1 ? 100 : 10) : weightFactor;
}

export interface LiveFrame {
  stable: boolean;
  /** kg after the factor and the /10 range correction (not rounded). */
  kg: number;
  r1: number;
  r2: number;
  newLayout: boolean;
}

/** 0x10 live weight. Two known layouts. Returns null if the frame is too short to read. */
export function parseLiveFrame(d: Uint8Array, weightFactor: number, protocolType: number): LiveFrame | null {
  // Newer (ES-30M-like): [3]=unit [4]=state [5,6]=weight [7..10]=R
  const newLayout = d[4] <= 0x02 && weightFactor === 10 && d.length >= 11;
  let stable: boolean, raw: number, r1: number, r2: number;
  if (newLayout) {
    stable = d[4] === 0x02 || (d[4] === 0x01 && protocolType !== 0xff);
    raw = be16(d[5], d[6]);
    r1 = be16(d[7], d[8]);
    r2 = be16(d[9], d[10]);
  } else {
    if (d.length < 10) return null;
    stable = d[5] === 1;
    raw = be16(d[3], d[4]);
    r1 = be16(d[6], d[7]);
    r2 = be16(d[8], d[9]);
  }
  let kg = raw / weightFactor;
  if (kg <= 5 || kg >= 250) kg /= 10;
  return { stable, kg, r1, r2, newLayout };
}

export interface StoredFrame {
  kg: number;
  /** Record time in QN epoch seconds. */
  recTime: number;
  r1: number;
  r2: number;
}

/** 0x23 stored record. Returns null if the frame is too short (scale sends a fragment). */
export function parseStoredFrame(d: Uint8Array): StoredFrame | null {
  if (d.length < 17) return null;
  return {
    kg: be16(d[10], d[11]) / 100,
    recTime: le32(d[6], d[7], d[8], d[9]),
    r1: le16(d[13], d[14]),
    r2: le16(d[15], d[16]),
  };
}

export async function measureOnce(opts: QnScaleOptions = {}): Promise<ScaleReading> {
  const log = (s: string) => opts.onLog?.(`${new Date().toISOString().slice(11, 23)} ${s}`);
  if (!("bluetooth" in navigator)) throw new Error("Web Bluetooth nicht verfügbar – Chrome auf Android nutzen.");

  const optionalServices = [SVC_T1, SVC_T2, SVC_AE00, SVC_DEVINFO, SVC_BATTERY];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const device = await (navigator as any).bluetooth.requestDevice(
    opts.acceptAllDevices
      ? { acceptAllDevices: true, optionalServices }
      : {
          filters: [{ namePrefix: "QN" }, { services: [SVC_T2] }, { services: [SVC_T1] }],
          optionalServices,
        },
  );
  log(`Gerät: "${device.name}" id=${device.id}`);

  const server = await device.gatt.connect();
  log("GATT verbunden");

  // --- discover characteristics of both layouts ----------------------------
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chars: Record<string, any> = {};
  for (const svcUuid of [SVC_T1, SVC_T2]) {
    try {
      const svc = await server.getPrimaryService(svcUuid);
      for (const c of await svc.getCharacteristics()) {
        chars[c.uuid] = c;
        log(`  char ${c.uuid.slice(4, 8)} props=${Object.entries(c.properties).filter(([, v]) => v).map(([k]) => k).join(",")}`);
      }
    } catch {
      /* layout not present */
    }
  }
  try {
    const bat = await (await server.getPrimaryService(SVC_BATTERY)).getCharacteristic(u16(0x2a19));
    log(`Batterie: ${(await bat.readValue()).getUint8(0)} %`);
  } catch {}

  const writeChar = chars[CHR_T2_WRITE] ?? chars[CHR_T1_CONFIG];
  const timeChar = chars[CHR_T2_WRITE] ?? chars[CHR_T1_TIME];
  if (!writeChar) throw new Error("Keine QN-Schreib-Characteristic (FFF2/FFE3) gefunden – andere Protokollfamilie?");

  // Writes must be serialized, Web Bluetooth rejects parallel GATT operations.
  let queue = Promise.resolve();
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const write = (c: any, data: Uint8Array, label: string) => {
    queue = queue
      .then(async () => {
        log(`→ ${label}: ${hex(data)}`);
        if (c.properties.writeWithoutResponse && !c.properties.write) await c.writeValueWithoutResponse(data);
        else await c.writeValueWithResponse(data);
      })
      .catch((e) => log(`! write ${label} fehlgeschlagen: ${e}`));
    return queue;
  };

  let protocolType = -1;
  let weightFactor = 100;
  let configSent = false;
  let historyAttempts = 0;
  const sessionStart = qnNow();
  const unitByte = opts.unit === "lb" ? 0x02 : 0x01;

  const sendHistoryQuery = () => {
    if (historyAttempts++ >= 5) return;
    write(writeChar, withChecksum([0x22, 0x06, protocolType, 0x00, 0x03, 0x00]), "0x22 history query");
  };

  return new Promise<ScaleReading>((resolve, reject) => {
    let done = false;
    const finish = (r: ScaleReading | Error) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      // ack a stable reading (vendor SDK always does this), then disconnect
      if (!(r instanceof Error)) {
        write(writeChar, withChecksum([0x1f, 0x05, protocolType, 0x10, 0x00]), "0x1F ack");
      }
      queue.finally(() => setTimeout(() => device.gatt.connected && device.gatt.disconnect(), 300));
      if (r instanceof Error) reject(r);
      else resolve(r);
    };
    const timer = setTimeout(() => finish(new Error("Timeout – keine stabile Messung empfangen")), opts.timeoutMs ?? 60_000);
    device.addEventListener("gattserverdisconnected", () => {
      log("Verbindung getrennt");
      finish(new Error("Waage hat die Verbindung getrennt, bevor eine stabile Messung kam"));
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const onPacket = (ev: any) => {
      const d = new Uint8Array(ev.target.value.buffer);
      log(`← ${hex(d)}`);
      if (d.length < 3) return;
      if (protocolType < 0) protocolType = d[2];

      switch (d[0]) {
        case 0x12: {
          weightFactor = parseInfoFrame(d, weightFactor);
          log(`  info: protocolType=0x${protocolType.toString(16)} weightFactor=/${weightFactor}`);
          if (!configSent) {
            configSent = true;
            write(writeChar, withChecksum([0x13, 0x09, protocolType, unitByte, 0x10, 0, 0, 0, 0]), "0x13 config");
            const t = qnNow();
            write(timeChar, Uint8Array.from([0x02, t & 0xff, (t >>> 8) & 0xff, (t >>> 16) & 0xff, (t >>> 24) & 0xff]), "0x02 time");
          }
          break;
        }
        case 0x14: {
          const t = qnNow();
          write(writeChar, withChecksum([0x20, 0x08, protocolType, t & 0xff, (t >>> 8) & 0xff, (t >>> 16) & 0xff, (t >>> 24) & 0xff, 0]), "0x20 time sync");
          break;
        }
        case 0x21: {
          write(writeChar, withChecksum([0xa0, 0x0d, 0x04, 0xfe, 0, 0, 0, 0, 0, 0, 0, 0, 0]), "0xA0 #1");
          write(writeChar, withChecksum([0xa0, 0x0d, 0x02, 0x01, 0x00, 0x08, 0x00, 0x21, 0x06, 0xb8, 0x04, 0x02, 0]), "0xA0 #2");
          sendHistoryQuery();
          break;
        }
        case 0x10: {
          const f = parseLiveFrame(d, weightFactor, protocolType);
          if (!f) return;
          opts.onLiveWeight?.(Math.round(f.kg * 100) / 100);
          if (f.stable && f.kg > 5) {
            log(`  STABIL: ${f.kg.toFixed(2)} kg  r1=${f.r1} r2=${f.r2} layout=${f.newLayout ? "neu" : "alt"}`);
            finish({ weightKg: +f.kg.toFixed(2), r1: f.r1, r2: f.r2, source: "live", protocolType, timestamp: new Date().toISOString(), rawHex: hex(d) });
          }
          break;
        }
        case 0x23: {
          const f = parseStoredFrame(d);
          if (!f) return void setTimeout(sendHistoryQuery, 3000);
          log(`  gespeichert: ${f.kg} kg r1=${f.r1} r2=${f.r2} alter=${sessionStart - f.recTime}s`);
          if (f.kg > 5 && f.kg < 300 && f.recTime + 90 >= sessionStart) {
            finish({ weightKg: f.kg, r1: f.r1, r2: f.r2, source: "stored", protocolType, timestamp: new Date().toISOString(), rawHex: hex(d) });
          } else setTimeout(sendHistoryQuery, 3000);
          break;
        }
        default:
          log(`  (opcode 0x${d[0].toString(16)} nicht ausgewertet)`);
      }
    };

    (async () => {
      for (const uuid of [CHR_T2_NOTIFY, CHR_T1_NOTIFY, CHR_T1_INDICATE]) {
        const c = chars[uuid];
        if (!c) continue;
        c.addEventListener("characteristicvaluechanged", onPacket);
        await c.startNotifications();
        log(`Notifications an: ${uuid.slice(4, 8)}`);
      }
      log("Bereit – jetzt barfuß auf die Waage steigen");
    })().catch((e) => finish(e instanceof Error ? e : new Error(String(e))));
  });
}
