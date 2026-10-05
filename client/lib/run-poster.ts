import type { ProjectedRoute, RunRouteDetail } from "./run-routes";

export type PosterStyle = "clinical" | "ink" | "teal";
export const POSTER_ASSETS = ["easy", "tempo", "long", "strength", "recovery", "progress"] as const;

export function escapeXml(value: string): string {
  return value.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "").replace(/[<>&"']/g, character => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;", "'": "&apos;" })[character]!);
}
function time(seconds: number | null, duration = false) {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "–";
  const rounded = Math.round(seconds), minutes = Math.floor(rounded / 60);
  return duration && minutes >= 60 ? `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}:${String(rounded % 60).padStart(2, "0")}` : `${minutes}:${String(rounded % 60).padStart(2, "0")}`;
}

// All metadata is escaped. Embedded illustrations must be local image data;
// GPS is projected to a local contour without latitude/longitude metadata.
export function buildPosterSvg(route: RunRouteDetail, geometry: ProjectedRoute, style: PosterStyle, illustration?: string): string {
  const palettes = {
    clinical: { background: "#fbfcfc", ink: "#14201f", muted: "#4d5b5a", accent: "#0a6e66", line: "#e2e7e8", wash: "#edf7f3" },
    ink: { background: "#14201f", ink: "#fbfcfc", muted: "#b8cfca", accent: "#88d4c6", line: "#35514c", wash: "#203c36" },
    teal: { background: "#e3f1ed", ink: "#163e37", muted: "#496c63", accent: "#0a6e66", line: "#b7d7cd", wash: "#d2e8df" },
  };
  const p = palettes[style];
  const date = route.started_at.match(/^(\d{4})-(\d{2})-(\d{2})/);
  const label = date ? `${date[3]}.${date[2]}.${date[1]}` : "Datum unbekannt";
  const characters = Array.from(route.title || "Deine Runde");
  const title = characters.length > 34 ? `${characters.slice(0, 33).join("")}…` : characters.join("");
  const titleSize = Math.min(43, 860 / Math.max(1, Array.from(title).length));
  const distance = route.distance_km != null && Number.isFinite(route.distance_km) && route.distance_km > 0 ? route.distance_km : null;
  const pace = distance && route.duration_seconds != null ? route.duration_seconds / distance : null;
  const paths = geometry.segments.map(segment => `<path d="${segment.map((point, i) => `${i ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ")}"/>`).join("");
  const image = illustration && /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(illustration)
    ? `<image x="710" y="595" width="190" height="190" href="${illustration}" opacity=".9"${style === "ink" ? ' filter="url(#asset-tint)"' : ""}/>` : "";
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024" role="img" aria-label="Laufposter: ${escapeXml(route.title || "Deine Runde")}">
<rect width="1024" height="1024" fill="${p.background}"/>
<defs><filter id="asset-tint" x="-10%" y="-10%" width="120%" height="120%"><feFlood flood-color="${p.accent}"/><feComposite in2="SourceAlpha" operator="in"/></filter><clipPath id="title-clip"><rect x="72" y="95" width="880" height="65"/></clipPath></defs>
<style>text{font-family:Inter,Arial,sans-serif} .number{font-family:'Inter Tight',Inter,Arial,sans-serif;font-variant-numeric:tabular-nums}</style>
<text x="72" y="77" fill="${p.accent}" font-size="21" font-weight="700" letter-spacing="5">MILON / LAUFEN</text>
<text x="952" y="77" fill="${p.muted}" font-size="19" text-anchor="end">${label}</text>
<text x="72" y="146" fill="${p.ink}" font-size="${titleSize.toFixed(2)}" font-weight="600" clip-path="url(#title-clip)">${escapeXml(title)}</text>
<rect x="72" y="180" width="880" height="570" rx="8" fill="${p.wash}"/>
<g transform="translate(112 205)" fill="none" stroke="${p.accent}" stroke-width="5" stroke-linecap="round" stroke-linejoin="round">${paths}</g>
<circle cx="${(112 + geometry.start.x).toFixed(2)}" cy="${(205 + geometry.start.y).toFixed(2)}" r="6" fill="${p.accent}" stroke="${p.background}" stroke-width="3"/>
<circle cx="${(112 + geometry.end.x).toFixed(2)}" cy="${(205 + geometry.end.y).toFixed(2)}" r="10" fill="none" stroke="${p.ink}" stroke-width="3"/>
${image}
<text x="916" y="215" fill="${p.muted}" font-size="16" text-anchor="middle">N</text>
<path d="M916 245v-17m-5 6 5-6 5 6" fill="none" stroke="${p.muted}" stroke-width="2"/>
<text x="72" y="802" fill="${p.muted}" font-size="18">DISTANZ</text>
<text x="72" y="876" fill="${p.ink}" font-size="67" font-weight="600" class="number">${distance == null ? "–" : distance.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}<tspan font-size="25" font-weight="400"> km</tspan></text>
<text x="520" y="802" fill="${p.muted}" font-size="18">AKTIVE DAUER</text>
<text x="520" y="862" fill="${p.ink}" font-size="37" class="number">${time(route.duration_seconds, true)}</text>
<text x="780" y="802" fill="${p.muted}" font-size="18">Ø PACE</text>
<text x="780" y="862" fill="${p.ink}" font-size="37" class="number">${time(pace)}<tspan font-size="17"> /km</tspan></text>
<line x1="72" x2="952" y1="928" y2="928" stroke="${p.line}"/>
<text x="72" y="969" fill="${p.muted}" font-size="17">Deine Strecke. Dein Fortschritt.</text>
<text x="952" y="969" fill="${p.muted}" font-size="14" text-anchor="end">GARMIN · ${geometry.segments.length > 1 ? "GETRENNTE GPS-ABSCHNITTE" : "GPS-AUFZEICHNUNG"}</text>
</svg>`;
}
