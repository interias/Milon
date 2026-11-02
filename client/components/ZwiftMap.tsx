"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, zwiftMapUrl, type CycSegments, type CycWorlds, type CycWorldTracks } from "@/lib/api";
import { de, dm } from "@/lib/format";

// Spuren liegen als Positionen 0..1 auf dem Kartenbild; das SVG rechnet in 1000 × 1000/aspect.
export type MapTrack = { id: string; segments: CycSegments; highlight?: boolean };

const BOX = 4 / 3;          // Seitenverhältnis des Kartenausschnitts
const PAD = 0.12;           // Rand um die Spuren (Anteil der Ausdehnung)
const MIN_SPAN = 0.12;      // kleinster Ausschnitt (Anteil der Kartenbreite)
const HIGHLIGHT = "#d4247a";

function viewBox(tracks: MapTrack[], width: number, height: number, whole: boolean): string {
  const pts = tracks.filter((t) => t.highlight || !tracks.some((x) => x.highlight)).flatMap((t) => t.segments.flat());
  if (whole || !pts.length) return `0 0 ${width} ${height}`;
  const xs = pts.map((p) => p[0] * width), ys = pts.map((p) => p[1] * height);
  let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  let w = Math.max(x1 - x0, MIN_SPAN * width) * (1 + 2 * PAD), h = Math.max(y1 - y0, MIN_SPAN * width) * (1 + 2 * PAD);
  if (w / h < BOX) w = h * BOX; else h = w / BOX;
  w = Math.min(w, width); h = Math.min(h, height);
  const cx = Math.min(Math.max((x0 + x1) / 2, w / 2), width - w / 2), cy = Math.min(Math.max((y0 + y1) / 2, h / 2), height - h / 2);
  x0 = cx - w / 2; y0 = cy - h / 2;
  return `${x0.toFixed(1)} ${y0.toFixed(1)} ${w.toFixed(1)} ${h.toFixed(1)}`;
}

const path = (segments: CycSegments, width: number, height: number) =>
  segments.map((s) => s.map((p, i) => `${i ? "L" : "M"}${(p[0] * width).toFixed(1)} ${(p[1] * height).toFixed(1)}`).join("")).join("");

export function ZwiftMap({ world, name, aspect, tracks }: { world: string; name: string; aspect: number; tracks: MapTrack[] }) {
  const [whole, setWhole] = useState(false);
  const [broken, setBroken] = useState(false);
  const width = 1000, height = 1000 / aspect;
  const lit = tracks.filter((t) => t.highlight);
  const first = lit[0]?.segments[0]?.[0], last = lit.at(-1)?.segments.at(-1)?.at(-1);
  return (
    <div>
      <div className="relative overflow-hidden rounded-card border border-line bg-[#2fa3c9]">
        <svg viewBox={viewBox(tracks, width, height, whole)} className="block aspect-[4/3] w-full" role="img"
          aria-label={`Zwift-Karte ${name} mit ${tracks.length} ${tracks.length === 1 ? "Fahrt" : "Fahrten"}`}>
          {!broken && <image href={zwiftMapUrl(world)} x={0} y={0} width={width} height={height} preserveAspectRatio="none" onError={() => setBroken(true)} />}
          {tracks.filter((t) => !t.highlight).map((t) => (
            <path key={t.id} d={path(t.segments, width, height)} fill="none" stroke={HIGHLIGHT} strokeOpacity={0.45} strokeWidth={2.2}
              strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          ))}
          {lit.map((t) => <g key={t.id}>
            <path d={path(t.segments, width, height)} fill="none" stroke="#fff" strokeWidth={6.5} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
            <path d={path(t.segments, width, height)} fill="none" stroke={HIGHLIGHT} strokeWidth={3.5} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
          </g>)}
          {first && <circle cx={first[0] * width} cy={first[1] * height} r={4} fill="#1f9d55" stroke="#fff" strokeWidth={2} vectorEffect="non-scaling-stroke"><title>Start</title></circle>}
          {last && <circle cx={last[0] * width} cy={last[1] * height} r={4} fill="#14201f" stroke="#fff" strokeWidth={2} vectorEffect="non-scaling-stroke"><title>Ziel</title></circle>}
        </svg>
        {broken && <p className="absolute inset-x-0 top-2 text-center text-[11px] text-white drop-shadow">Kartenbild nicht erreichbar — nur die Spur</p>}
        <button type="button" onClick={() => setWhole(!whole)}
          className="absolute right-2 top-2 rounded-md border border-line bg-surface/90 px-2 py-1 text-xs font-semibold shadow-sm hover:bg-surface">
          {whole ? "Gefahrene Gegend" : `Ganz ${name}`}
        </button>
      </div>
      <p className="mt-1 text-[10px] text-muted">Kartenbild © Zwift · Weltgrenzen aus zwift-data (MIT)</p>
    </div>
  );
}

/** Atlas: Welt wählen → alle Fahrten dieser Welt, eine hervorgehoben (Standard: die neueste). */
export function ZwiftAtlas({ worlds }: { worlds: CycWorlds["worlds"] }) {
  const mapped = worlds.filter((w) => w.slug && w.tracks > 0);
  const [world, setWorld] = useState(mapped[0]?.slug ?? null);
  const [data, setData] = useState<CycWorldTracks | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!world) return;
    let live = true;
    setFailed(false);
    api.cycTracks(world).then((d) => { if (live) { setData(d); setPicked(d.rides[0]?.activity_id ?? null); } })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [world]);
  if (!mapped.length) return null;
  const current = data && data.world === world ? data : null;
  return (
    <div className="mb-4">
      {mapped.length > 1 && <div className="mb-2 flex flex-wrap gap-1.5">
        {mapped.map((w) => (
          <button key={w.slug} type="button" onClick={() => setWorld(w.slug)} aria-pressed={w.slug === world}
            className={`rounded-full border px-2.5 py-1 text-xs ${w.slug === world ? "border-accent bg-accent text-white" : "border-line hover:bg-surface-alt"}`}>
            {w.world} <span className="tabular-nums opacity-75">{w.tracks}</span>
          </button>
        ))}
      </div>}
      {failed ? <p className="text-xs text-muted">Spuren nicht verfügbar.</p> : !current ? <div className="aspect-[4/3] animate-pulse rounded-card bg-surface-alt" /> : <>
        <ZwiftMap key={`${current.world}-${picked}`} world={current.world} name={current.name} aspect={current.aspect}
          tracks={current.rides.map((r) => ({ id: r.activity_id, segments: r.segments, highlight: r.activity_id === picked }))} />
        <ul className="mt-2 max-h-48 divide-y divide-line overflow-y-auto text-xs">
          {current.rides.map((r) => (
            <li key={r.activity_id} className="flex items-baseline gap-2 py-1.5">
              <button type="button" onClick={() => setPicked(r.activity_id)} aria-pressed={r.activity_id === picked}
                className={`min-w-0 flex-1 truncate text-left ${r.activity_id === picked ? "font-semibold text-ink" : "text-muted hover:text-ink"}`}>
                <span className="mr-1.5 inline-block size-2 rounded-full align-middle" style={{ background: HIGHLIGHT, opacity: r.activity_id === picked ? 1 : 0.45 }} />
                {r.route || r.title}
              </button>
              <span className="shrink-0 tabular-nums text-muted">{dm(r.date.slice(0, 10))}{r.km != null ? ` · ${de(r.km, 1)} km` : ""}</span>
              <Link href={`/rad/${encodeURIComponent(r.activity_id)}`} className="shrink-0 text-accent underline underline-offset-4">Details</Link>
            </li>
          ))}
        </ul>
      </>}
    </div>
  );
}
