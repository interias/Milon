// Stellt die generierten Silhouetten frei: Magenta-Hintergrund -> transparent.
// Liest alle PNGs aus design/assets/.raw/silhouette/ und schreibt sie nach
// design/assets/silhouette/ (Alpha aus "magentaness" = (r+b)/2 - g).
// Start (aus Repo-Root):  node design/tools/key-silhouette.mjs
import sharp from "sharp";
import { readdirSync, mkdirSync } from "node:fs";

const SRC = "design/assets/.raw/silhouette";
const OUT = "design/assets/silhouette";
const HI = 80; // magentaness >= HI -> transparent (Hintergrund)
const LO = 35; // magentaness <= LO -> deckend (Figur)
mkdirSync(OUT, { recursive: true });

for (const f of readdirSync(SRC).filter((f) => f.endsWith(".png"))) {
  const { data, info } = await sharp(`${SRC}/${f}`).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const ch = info.channels;
  for (let i = 0; i < data.length; i += ch) {
    const r = data[i], g = data[i + 1], b = data[i + 2];
    const m = (r + b) / 2 - g;
    let a;
    if (m >= HI) a = 0;
    else if (m <= LO) a = 255;
    else a = Math.round(((HI - m) / (HI - LO)) * 255);
    if (a > 0 && a < 255) {
      if (r > g) data[i] = Math.max(g, r - Math.min(r - g, 28));
      if (b > g) data[i + 2] = Math.max(g, b - Math.min(b - g, 28));
    }
    data[i + 3] = a;
  }
  await sharp(data, { raw: { width: info.width, height: info.height, channels: ch } }).png().toFile(`${OUT}/${f}`);
  console.log("freigestellt ->", `${OUT}/${f}`);
}
