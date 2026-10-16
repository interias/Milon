"use client";

import { useMemo, useState } from "react";
import type { Hero } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { dm } from "@/lib/format";

const TIP_YELLOW = "#ffd100";
const SECTOR_ORDER = ["Diersfordter Forst", "Blumenkamp", "Schepersfeld", "Fusternberg", "Lippe-Mündung", "Büdericher Insel", "Rheinauen", "Flüren"];

// --- Weltkarte: echte GPS-Routen decken den Nebel auf ---------------------------------------
export function HeroWorld({ data }: { data: Hero }) {
  const w = data.world;
  const [full, setFull] = useState(false);
  const view = useMemo(() => {
    if (!w?.available) return null;
    if (full) return { x: -w.radius_m, y: -w.radius_m, s: 2 * w.radius_m };
    const xs = w.cells.map(([i]) => i * w.cell_m), ys = w.cells.map(([, j]) => -j * w.cell_m);
    const pad = 1500;
    const minX = Math.min(0, ...xs) - pad, maxX = Math.max(0, ...xs) + w.cell_m + pad;
    const minY = Math.min(0, ...ys) - w.cell_m - pad, maxY = Math.max(0, ...ys) + pad;
    const s = Math.max(4000, maxX - minX, maxY - minY);
    return { x: (minX + maxX) / 2 - s / 2, y: (minY + maxY) / 2 - s / 2, s };
  }, [w, full]);
  if (!w?.available || !view) {
    return <Card><CardTitle title="Weltkarte" sub="Erscheint, sobald GPS-Routen deiner Läufe vorliegen (Garmin)." /></Card>;
  }
  const regions = Object.fromEntries(w.regions.map((r) => [r.name, r]));
  const label = (name: string, idx: number) => {
    const a = (idx * 45) * Math.PI / 180;
    const rad = Math.min(w.radius_m * 0.62, view.s * 0.38);
    return { x: Math.sin(a) * rad, y: -Math.cos(a) * rad };
  };
  const font = view.s / 27;
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <CardTitle title="Weltkarte" sub={`Deine GPS-Routen lichten den Nebel · ${String(w.explored_pct).replace(".", ",")} % der Welt erkundet · ${String(w.km2).replace(".", ",")} km²`} />
        <button type="button" onClick={() => setFull((v) => !v)} className="shrink-0 rounded border border-[#4b3a22] px-2 py-1 text-[11px] text-muted hover:text-[#ffd100]">
          {full ? "Erkundetes zeigen" : "Ganze Welt"}
        </button>
      </div>
      <div className="grid gap-4 @3xl:grid-cols-[minmax(0,1fr)_240px]">
        <svg viewBox={`${view.x} ${view.y} ${view.s} ${view.s}`} className="aspect-square w-full rounded-md border border-[#3a2d1a]" role="img"
             aria-label={`Weltkarte: ${w.regions.filter((r) => r.discovered).length} von ${w.regions.length} Gebieten entdeckt`}>
          <defs>
            <radialGradient id="world-fog" cx="50%" cy="50%" r="70%">
              <stop offset="0" stopColor="#1b1610" /><stop offset="1" stopColor="#070605" />
            </radialGradient>
            <filter id="world-soft" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation={w.cell_m * 0.35} /></filter>
          </defs>
          <rect x={view.x} y={view.y} width={view.s} height={view.s} fill="url(#world-fog)" />
          <circle cx="0" cy="0" r={w.radius_m} fill="none" stroke="#3a2d1a" strokeWidth={view.s / 300} strokeDasharray={`${view.s / 60} ${view.s / 80}`} />
          <circle cx="0" cy="0" r={w.core_m} fill="none" stroke="#5b4526" strokeWidth={view.s / 350} />
          {SECTOR_ORDER.map((_, i) => {
            const a = (i * 45 + 22.5) * Math.PI / 180;
            return <line key={i} x1={Math.sin(a) * w.core_m} y1={-Math.cos(a) * w.core_m} x2={Math.sin(a) * w.radius_m} y2={-Math.cos(a) * w.radius_m}
                         stroke="#2c2216" strokeWidth={view.s / 400} />;
          })}
          <g filter="url(#world-soft)">
            {w.cells.map(([i, j]) => (
              <rect key={`${i}:${j}`} x={i * w.cell_m - w.cell_m * 0.15} y={-(j + 1) * w.cell_m - w.cell_m * 0.15}
                    width={w.cell_m * 1.3} height={w.cell_m * 1.3} fill="#d9c08a" opacity=".55" />
            ))}
          </g>
          {w.routes.map((r) => (
            <polyline key={r.date + r.points.length} points={r.points.map(([x, y]) => `${x},${-y}`).join(" ")}
                      fill="none" stroke="#e3b64f" strokeOpacity=".75" strokeWidth={view.s / 260} strokeLinejoin="round" strokeLinecap="round" />
          ))}
          {SECTOR_ORDER.map((name, i) => {
            const p = label(name, i), r = regions[name];
            return <text key={name} x={p.x} y={p.y} textAnchor="middle" fontSize={font} fontFamily="var(--font-cinzel), serif"
                         fill={r?.discovered ? TIP_YELLOW : "#5b4526"} style={{ paintOrder: "stroke" }} stroke="#000" strokeWidth={font / 6}>
              {r?.discovered ? name : "???"}
            </text>;
          })}
          <g>
            <circle cx="0" cy="0" r={view.s / 70} fill="#ff8000" stroke="#000" strokeWidth={view.s / 400} />
            <text x="0" y={view.s / 25} textAnchor="middle" fontSize={font * 0.8} fill="#efe3c8" stroke="#000" strokeWidth={font / 7} style={{ paintOrder: "stroke" }}>Zitadelle · Heimat</text>
          </g>
        </svg>
        <ul className="space-y-1.5 text-[12px]">
          {w.regions.map((r) => (
            <li key={r.name}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate font-semibold" style={{ color: r.discovered ? TIP_YELLOW : "#6b5a40" }}>{r.discovered ? r.name : "??? (unentdeckt)"}</span>
                <span className="shrink-0 tabular-nums text-muted">{String(r.pct).replace(".", ",")} %</span>
              </div>
              <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-[#0a0807]">
                <div className="h-full rounded-full" style={{ width: `${Math.min(100, r.pct * 4)}%`, background: r.discovered ? "#d9c08a" : "transparent" }} />
              </div>
              {r.discovered && r.discovered_on && <p className="text-[10px] text-muted">entdeckt am {dm(r.discovered_on)}</p>}
            </li>
          ))}
        </ul>
      </div>
      <p className="mt-2 text-[10px] text-muted">Je Gebiet 50 EP und 2 Gold beim ersten Betreten · Kartenmitte = dein häufigster Startpunkt · keine absoluten Koordinaten.</p>
    </Card>
  );
}
