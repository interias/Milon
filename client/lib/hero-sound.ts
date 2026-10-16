// Klänge der Heldenreise: im Browser synthetisiert (WebAudio), keine Dateien. Standardmäßig aus.
const KEY = "milon.hero.sound";
let ctx: AudioContext | null = null;

export type HeroSound = "levelup" | "loot" | "equip" | "chest" | "click" | "quest";
const RARITY_STEP: Record<string, number> = { grau: 0, weiss: 1, gruen: 2, blau: 3, lila: 4, orange: 5, rot: 6 };

export function soundOn(): boolean {
  try { return localStorage.getItem(KEY) === "1"; } catch { return false; }
}

export function setSoundOn(on: boolean): void {
  try { localStorage.setItem(KEY, on ? "1" : "0"); } catch { /* ohne Speicher bleibt es aus */ }
}

function tone(freq: number, at: number, dur: number, type: OscillatorType = "triangle", gain = 0.1, toFreq?: number) {
  if (!ctx) return;
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, ctx.currentTime + at);
  if (toFreq) osc.frequency.exponentialRampToValueAtTime(toFreq, ctx.currentTime + at + dur);
  g.gain.setValueAtTime(0.0001, ctx.currentTime + at);
  g.gain.exponentialRampToValueAtTime(gain, ctx.currentTime + at + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + dur);
  osc.connect(g).connect(ctx.destination);
  osc.start(ctx.currentTime + at);
  osc.stop(ctx.currentTime + at + dur + 0.05);
}

export function play(kind: HeroSound, rarity?: string): void {
  if (typeof window === "undefined" || !soundOn()) return;
  try {
    ctx ??= new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
  } catch { return; }
  switch (kind) {
    case "levelup": // Fanfare: Dur-Arpeggio + Glanz
      [523, 659, 784, 1047].forEach((f, i) => tone(f, i * 0.11, 0.5, "triangle", 0.12));
      tone(2093, 0.45, 0.8, "sine", 0.04);
      break;
    case "loot": { // Pling — höher je Seltenheit
      const step = RARITY_STEP[rarity ?? "weiss"] ?? 1;
      const base = 660 * Math.pow(2, step / 12 * 2);
      tone(base, 0, 0.25, "sine", 0.1);
      tone(base * 1.5, 0.09, 0.4, "sine", 0.08);
      if (step >= 4) tone(base * 2, 0.2, 0.6, "sine", 0.05);
      break;
    }
    case "chest": // aufsteigendes Rauschen der Truhe
      tone(180, 0, 0.5, "sawtooth", 0.03, 720);
      tone(880, 0.35, 0.4, "sine", 0.06);
      break;
    case "equip": // dumpfes Anlegen
      tone(160, 0, 0.18, "sine", 0.14, 80);
      break;
    case "quest":
      tone(784, 0, 0.2, "triangle", 0.08);
      tone(1175, 0.12, 0.35, "triangle", 0.08);
      break;
    case "click":
      tone(1400, 0, 0.04, "square", 0.02);
      break;
  }
}
