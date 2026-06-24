// Magenta-Chroma-Keyer fuer Motive, die selbst neon-GRUEN sind (der gruene
// Standard-Keyer der transparent-images-Skill wuerde sie ausstanzen).
// Liest die Roh-Greenscreen-... pardon: Roh-MAGENTA-Originale aus assets/.raw/
// und stellt sie frei (Magenta-Hintergrund -> transparent).
//
// Start (aus dem Repo-Root):  node design/tools/key-magenta.mjs
import sharp from "sharp";

const JOBS = [
  ["design/assets/.raw/dark-athletic.png", "design/assets/dark-athletic.png"],
  ["design/assets/.raw/terminal-local-first.png", "design/assets/terminal-local-first.png"],
];

const HI = 80; // magentaness >= HI  -> voll transparent (Hintergrund)
const LO = 35; // magentaness <= LO  -> voll deckend (Motiv)

for (const [inP, outP] of JOBS) {
  const { data, info } = await sharp(inP).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const ch = info.channels;
  for (let i = 0; i < data.length; i += ch) {
    const r = data[i], g = data[i + 1], b = data[i + 2];
    const magentaness = (r + b) / 2 - g; // hoch = Magenta (r,b hoch, g niedrig)
    let a;
    if (magentaness >= HI) a = 0;
    else if (magentaness <= LO) a = 255;
    else a = Math.round(((HI - magentaness) / (HI - LO)) * 255);
    // Despill nur an den weichen Kanten (Teiltransparenz), damit Cyan/Gruen im
    // Motivinneren unangetastet bleibt:
    if (a > 0 && a < 255) {
      if (r > g) data[i] = Math.max(g, r - Math.min(r - g, 28));
      if (b > g) data[i + 2] = Math.max(g, b - Math.min(b - g, 28));
    }
    data[i + 3] = a;
  }
  await sharp(data, { raw: { width: info.width, height: info.height, channels: ch } }).png().toFile(outP);
  console.log("freigestellt ->", outP);
}
