import type { MonthlyRecapData } from "./overview-history";

const escapeXml = (value: string) => value.replace(/[<>&"']/g, character => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;" })[character]!);

const number = (value: number, digits = 0) => value.toLocaleString("de-DE", { maximumFractionDigits: digits });
export function buildMonthlySvg(data: MonthlyRecapData, illustration: string, showWeight: boolean, animate = false): string {
  const title = new Date(`${data.month}-15T12:00:00`).toLocaleDateString("de-DE", { month: "long", year: "numeric" });
  const routes = data.routes.filter(route => route.contour.some(segment => segment.length > 1)).slice(0, 12);
  const columns = Math.max(1, Math.min(4, Math.ceil(Math.sqrt(routes.length))));
  const rows = Math.max(1, Math.ceil(routes.length / columns));
  const width = 850 / columns, height = 395 / rows, scale = Math.min(width, height) / 220;
  const paths = routes.map((route, index) => {
    const x = 87 + width * (index % columns) + (width - 200 * scale) / 2;
    const y = 360 + height * Math.floor(index / columns) + (height - 200 * scale) / 2;
    return `<g transform="translate(${x.toFixed(2)} ${y.toFixed(2)}) scale(${scale.toFixed(4)})">${route.contour.map(segment => `<path pathLength="1" d="${segment.filter(point => point.length === 2 && point.every(Number.isFinite)).map((point, i) => `${i ? "L" : "M"}${point[0].toFixed(2)},${point[1].toFixed(2)}`).join(" ")}"/>`).join("")}</g>`;
  }).join("");
  const image = /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(illustration) ? `<image x="774" y="125" width="180" height="180" href="${illustration}" opacity=".9"/>` : "";
  const weight = showWeight && data.weight_delta_kg != null ? `${data.weight_delta_kg > 0 ? "+" : ""}${number(data.weight_delta_kg, 1)} kg · Gewichtsverlauf` : `${data.training_days} erfasste Trainingstage`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024" role="img" aria-label="Monatsrückblick ${escapeXml(title)}">
<style>text{font-family:Inter,Arial,sans-serif}.number{font-family:'Inter Tight',Inter,Arial,sans-serif;font-variant-numeric:tabular-nums}${animate ? ".routes path{animation:draw 220ms ease-out both}@keyframes draw{from{stroke-dasharray:1;stroke-dashoffset:1}to{stroke-dasharray:1;stroke-dashoffset:0}}@media(prefers-reduced-motion:reduce){.routes path{animation:none}}" : ""}</style>
<rect width="1024" height="1024" fill="#fbfcfc"/>
<text x="72" y="79" fill="#0a6e66" font-size="22" letter-spacing="5" font-weight="700">MILON / DEIN MONAT</text>
<text x="72" y="165" fill="#14201f" font-size="53" font-weight="600">${escapeXml(title)}</text>
<text x="74" y="208" fill="#4d5b5a" font-size="19">${data.partial ? `Zwischenstand bis ${escapeXml(data.to_date.split("-").reverse().join("."))}` : "Deine erfassten Einheiten im Rückblick"}</text>
${image}
<line x1="72" x2="952" y1="266" y2="266" stroke="#e2e7e8"/>
<text x="72" y="315" fill="#4d5b5a" font-size="18">DEINE STRECKEN</text>
<text x="952" y="315" fill="#4d5b5a" font-size="17" text-anchor="end">${routes.length}${data.route_count > routes.length ? ` von ${data.route_count}` : ""} GPS-Aufzeichnungen</text>
<rect x="72" y="342" width="880" height="430" rx="8" fill="#edf6f3"/>
<g class="routes" stroke="#0a6e66" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round">${paths}</g>
${routes.length ? "" : '<text x="512" y="565" text-anchor="middle" font-size="24" fill="#4d5b5a">Keine GPS-Konturen in diesem Monat</text>'}
<text x="72" y="822" fill="#4d5b5a" font-size="18">LAUFEN</text><text class="number" x="72" y="888" font-size="56" fill="#14201f" font-weight="600">${number(data.running_km, 1)}<tspan font-size="25"> km</tspan></text>
<text x="445" y="822" fill="#4d5b5a" font-size="18">LÄUFE</text><text class="number" x="445" y="888" font-size="56" fill="#14201f" font-weight="600">${data.runs}</text>
<text x="737" y="822" fill="#4d5b5a" font-size="18">GYM-EINHEITEN</text><text class="number" x="737" y="888" font-size="56" fill="#14201f" font-weight="600">${data.strength_sessions}</text>
<line x1="72" x2="952" y1="931" y2="931" stroke="#e2e7e8"/>
<text x="72" y="972" font-size="19" fill="#0a6e66">${escapeXml(weight)}</text>
<text x="952" y="972" font-size="15" fill="#4d5b5a" text-anchor="end">KÖRPER · LAUFEN · KRAFT</text></svg>`;
}
