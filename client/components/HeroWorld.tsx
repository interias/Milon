"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Hero, type HeroDungeon, type HeroPlace, type HeroTile } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { dm } from "@/lib/format";

const TIP_YELLOW = "#ffd100";
const DUNGEON = "#c08cff";
const DIRS = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"];
const KIND_COLOR: Record<HeroPlace["kind"], string> = { schrein: "#6fd3e8", schatz: TIP_YELLOW };
const TYPE_ICON: Record<string, string> = { wasser: "🌊", wald: "🌲", aue: "🪶", deich: "🏰", feld: "🌾", dorf: "🏘️" };
const TYPE_ORDER = ["wasser", "wald", "aue", "deich", "feld", "dorf"];
type ViewMode = "erkundet" | "nah" | "welt" | "fokus" | "frei";
// Kartenkacheln im Pergament-Ton der Seite
const TILE_FILTER = "sepia(.65) saturate(.8) brightness(.6) contrast(1.12)";
type Box = { x: number; y: number; s: number };

const num = (v: number) => String(v).replace(".", ",");
const dir = (x: number, y: number) => DIRS[Math.round(((Math.atan2(x, y) * 180 / Math.PI + 360) % 360) / 45) % 8];

// Schwierigkeit wie in WoW: Farbe der Stufe relativ zur eigenen.
export function levelColor(level: number, hero: number) {
  const d = level - hero;
  return d >= 5 ? "#ff3b3b" : d >= 3 ? "#ff8040" : d >= -2 ? "#ffff00" : d >= -10 ? "#40c040" : "#9d9d9d";
}

function boxOf(xs: number[], ys: number[], pad: number, min: number): Box {
  const minX = Math.min(...xs) - pad, maxX = Math.max(...xs) + pad, minY = Math.min(...ys) - pad, maxY = Math.max(...ys) + pad;
  const s = Math.max(min, maxX - minX, maxY - minY);
  return { x: (minX + maxX) / 2 - s / 2, y: (minY + maxY) / 2 - s / 2, s };
}

function status(d: HeroDungeon) {
  const done = d.segments.filter((s) => s.cleared).length;
  if (d.heroic) return { label: "Heroisch bezwungen", color: "#ff8000" };
  if (d.cleared) return { label: "Bezwungen", color: "#40c040" };
  if (done) return { label: `${done}/${d.segments.length} Abschnitte`, color: TIP_YELLOW };
  if (d.discovered) return { label: "Entdeckt", color: DUNGEON };
  return { label: "Im Nebel", color: "#6b5a40" };
}

function PlaceMark({ p, size }: { p: HeroPlace; size: number }) {
  const x = p.x, y = -p.y, c = KIND_COLOR[p.kind];
  return <g><title>{`${p.name} · ${p.kind_label} · Stufe ${p.level}`}</title>
    {p.kind === "schrein" && <path d={`M${x} ${y - size}l${size * 0.75} ${size}l${-size * 0.75} ${size}l${-size * 0.75} ${-size}z`} fill={c} stroke="#000" strokeWidth={size / 8} />}
    {p.kind === "schatz" && <rect x={x - size * 0.7} y={y - size * 0.5} width={size * 1.4} height={size} rx={size / 6} fill={c} stroke="#000" strokeWidth={size / 8} />}
  </g>;
}

function Teaser({ x, y, size, title, color = DUNGEON }: { x: number; y: number; size: number; title: string; color?: string }) {
  return <g opacity=".8"><title>{title}</title>
    <circle cx={x} cy={-y} r={size * 0.9} fill="#000" fillOpacity=".5" stroke={color} strokeOpacity=".7" strokeWidth={size / 8} strokeDasharray={`${size / 4} ${size / 5}`} />
    <text x={x} y={-y + size * 0.38} textAnchor="middle" fontSize={size * 1.1} fill={color} fontWeight="700">?</text>
  </g>;
}

function DungeonTrack({ d, view, active, onPick }: { d: HeroDungeon; view: Box; active: boolean; onPick: () => void }) {
  const w = Math.max(view.s / 220, 18) * (active ? 1.6 : 1);
  const first = d.segments[0]?.points[0];
  return (
    <g onClick={onPick} className="cursor-pointer">
      <title>{`${d.name} · ${d.type_label} · Stufe ${d.level} · ${status(d).label}`}</title>
      {d.segments.map((s, i) => (
        <polyline key={i} points={s.points.map(([x, y]) => `${x},${-y}`).join(" ")} fill="none"
                  stroke={s.cleared ? DUNGEON : "#7a5aa8"} strokeOpacity={s.cleared ? 0.95 : 0.7} strokeWidth={w}
                  strokeDasharray={s.cleared ? undefined : `${w * 2} ${w * 1.6}`} strokeLinecap="round" strokeLinejoin="round" />
      ))}
      {first && <g>
        <circle cx={first[0]} cy={-first[1]} r={w * 2.4} fill="#1a0f24" stroke={d.heroic ? "#ff8000" : DUNGEON} strokeWidth={w / 1.5} />
        <path d={`M${first[0] - w * 1.1} ${-first[1] + w * 1.2}v${-w * 1.2}a${w * 1.1} ${w * 1.1} 0 0 1 ${w * 2.2} 0v${w * 1.2}z`} fill={d.heroic ? "#ff8000" : DUNGEON} />
      </g>}
    </g>
  );
}

// --- Weltkarte: echte GPS-Routen decken den Nebel auf; Verliese sind echte Strecken -----------------
export function HeroWorld({ data }: { data: Hero }) {
  const w = data.world;
  const [mode, setMode] = useState<ViewMode>("erkundet");
  const [picked, setPicked] = useState<string | null>(null);
  const heroLevel = data.hero.level;
  const dungeons = useMemo(() => (w?.available ? w.dungeons ?? [] : []), [w]);
  const targets = useMemo(() => dungeons.filter((d) => !d.cleared).sort((a, b) => a.km - b.km).slice(0, 3), [dungeons]);
  const focus = dungeons.find((d) => d.key === picked) ?? null;
  const preset = useMemo<Box | null>(() => {
    if (!w?.available) return null;
    if (mode === "welt") return { x: -w.radius_m * 1.03, y: -w.radius_m * 1.03, s: 2.06 * w.radius_m };
    if (mode === "nah") { const r = (w.rings?.[0]?.outer_m ?? 6000) * 1.05; return { x: -r, y: -r, s: 2 * r }; }
    if (mode === "fokus" && focus) {
      const pts = focus.segments.flatMap((s) => s.points);
      return pts.length ? boxOf(pts.map((p) => p[0]), pts.map((p) => -p[1]), 500, 2500)
        : boxOf([0, focus.x], [0, -focus.y], 1200, 4000);
    }
    const xs = [0, ...w.cells.map(([i]) => i * w.cell_m), ...targets.map((t) => t.x)];
    const ys = [0, ...w.cells.map(([, j]) => -j * w.cell_m), ...targets.map((t) => -t.y)];
    return boxOf(xs, ys, 1200, 4000);
  }, [w, mode, targets, focus]);
  // Frei verschiebbare Ansicht: Voreinstellungen setzen sie, Ziehen/Zoomen ändert sie.
  const [view, setView] = useState<Box | null>(null);
  useEffect(() => { if (preset && mode !== "frei") setView(preset); }, [preset, mode]);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const viewRef = useRef<Box | null>(null);
  viewRef.current = view;
  const dragged = useRef(false);
  const maxS = (w?.available ? w.radius_m : 30_000) * 2.2;
  const zoomAt = (factor: number, cx?: number, cy?: number) => setView((v) => {
    if (!v) return v;
    const s = Math.min(maxS, Math.max(400, v.s * factor)), k = s / v.s;
    const px = cx ?? v.x + v.s / 2, py = cy ?? v.y + v.s / 2;
    return { x: px - (px - v.x) * k, y: py - (py - v.y) * k, s };
  });
  const toMap = (clientX: number, clientY: number) => {
    const r = svgRef.current!.getBoundingClientRect(), v = viewRef.current!;
    return [v.x + (clientX - r.left) / r.width * v.s, v.y + (clientY - r.top) / r.height * v.s];
  };
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const [cx, cy] = toMap(e.clientX, e.clientY);
      zoomAt(Math.exp(e.deltaY * 0.0015), cx, cy);
      setMode("frei");
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });  // eslint-disable-line react-hooks/exhaustive-deps
  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    const pts = new Map<number, [number, number]>([[e.pointerId, [e.clientX, e.clientY]]]);
    const start: [number, number] = [e.clientX, e.clientY];
    dragged.current = false;
    const move = (ev: PointerEvent) => {
      const prev = pts.get(ev.pointerId);
      if (!prev && pts.size >= 2) return;
      pts.set(ev.pointerId, [ev.clientX, ev.clientY]);
      const r = svgRef.current!.getBoundingClientRect(), v = viewRef.current!;
      if (pts.size === 1 && prev) {
        if (Math.hypot(ev.clientX - start[0], ev.clientY - start[1]) > 5) dragged.current = true;
        if (!dragged.current) return;
        const k = v.s / r.width;
        setView({ ...v, x: v.x - (ev.clientX - prev[0]) * k, y: v.y - (ev.clientY - prev[1]) * k });
        setMode("frei");
      } else if (pts.size === 2 && prev) {
        const [a, b] = [...pts.values()];
        const other = a === pts.get(ev.pointerId) ? b : a;
        const before = Math.hypot(prev[0] - other[0], prev[1] - other[1]);
        const after = Math.hypot(ev.clientX - other[0], ev.clientY - other[1]);
        if (before > 0 && after > 0) {
          dragged.current = true;
          const [cx, cy] = toMap((ev.clientX + other[0]) / 2, (ev.clientY + other[1]) / 2);
          zoomAt(before / after, cx, cy);
          setMode("frei");
        }
      }
    };
    const down = (ev: PointerEvent) => pts.set(ev.pointerId, [ev.clientX, ev.clientY]);
    const up = (ev: PointerEvent) => {
      pts.delete(ev.pointerId);
      if (pts.size === 0) {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerdown", down);
        window.removeEventListener("pointerup", up);
        window.removeEventListener("pointercancel", up);
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerdown", down);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  };
  // Kartenkacheln (Wege, Straßen, Wasser) nur im aufgedeckten Bereich, nachgeladen je Ausschnitt.
  const [tiles, setTiles] = useState<HeroTile[]>([]);
  useEffect(() => {
    if (!view || !w?.available) return;
    const t = setTimeout(() => {
      const px = (svgRef.current?.clientWidth ?? 800) * Math.min(2, window.devicePixelRatio || 1);
      api.heroWorldTiles(view.x, -(view.y + view.s), view.x + view.s, -view.y, px)
        .then((r) => setTiles(r.tiles)).catch(() => setTiles([]));
    }, 250);
    return () => clearTimeout(t);
  }, [view, w?.available]);
  if (!w?.available || !view) {
    return <Card><CardTitle title="Weltkarte" sub="Erscheint, sobald GPS-Routen deiner Läufe vorliegen (Garmin)." /></Card>;
  }
  const pick = (key: string) => { setPicked(key); setMode("fokus"); };
  const rings = w.rings ?? [{ name: "Nahland", outer_m: w.radius_m }];
  const pois = w.pois ?? [];
  const regionsByName = Object.fromEntries(w.regions.map((r) => [r.name, r]));
  const sectorNames = (ring: number) => w.regions.filter((r) => r.ring === ring && r.name !== "Zitadelle").map((r) => r.name);
  const font = view.s / 34;
  const icon = view.s / 70;
  const targetKeys = new Set(targets.map((t) => t.key));
  const found = pois.filter((p) => p.found).sort((a, b) => (b.found_on ?? "").localeCompare(a.found_on ?? ""));
  const shown = dungeons.filter((d) => d.discovered);
  const teasers = dungeons.filter((d) => !d.discovered && (targetKeys.has(d.key) || d.key === picked || (d.region && regionsByName[d.region]?.discovered)));
  const placeTeasers = pois.filter((p) => !p.found && regionsByName[p.region]?.discovered);
  const discoveredCount = w.regions.filter((r) => r.discovered).length;
  const cleared = dungeons.filter((d) => d.cleared).length;
  return (
    <div className="space-y-3">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <CardTitle title="Weltkarte" sub={`Deine GPS-Routen lichten den Nebel · ${discoveredCount} von ${w.regions.length} Gebieten · ${cleared} von ${dungeons.length} Verliesen · ${num(w.km2)} km² erkundet`} />
          <div className="flex shrink-0 overflow-hidden rounded border border-[#4b3a22] text-[11px]">
            {([["erkundet", "Erkundet"], ["nah", "Nahland"], ["welt", "30 km"]] as [ViewMode, string][]).map(([k, l]) => (
              <button key={k} type="button" onClick={() => { setMode(k); if (k === mode && preset) setView(preset); }}
                      className={`px-2 py-1 ${mode === k ? "bg-[#2a2013] text-[#ffd100]" : "text-muted hover:text-[#ffd100]"}`}>{l}</button>
            ))}
          </div>
        </div>
        <div className="grid gap-4 @3xl:grid-cols-[minmax(0,1fr)_260px]">
          <div className="relative">
          <svg ref={svgRef} viewBox={`${view.x} ${view.y} ${view.s} ${view.s}`} role="img"
               className="aspect-square w-full cursor-grab touch-none select-none rounded-md border border-[#3a2d1a] active:cursor-grabbing"
               aria-label={`Weltkarte: ${discoveredCount} von ${w.regions.length} Gebieten entdeckt`}
               onPointerDown={onPointerDown}
               onClickCapture={(e) => { if (dragged.current) { e.stopPropagation(); dragged.current = false; } }}
               onDoubleClick={(e) => { const [cx, cy] = toMap(e.clientX, e.clientY); zoomAt(0.5, cx, cy); setMode("frei"); }}>
            <defs>
              <mask id="world-reveal" maskUnits="userSpaceOnUse" x={view.x} y={view.y} width={view.s} height={view.s}>
                <g filter="url(#world-soft)">
                  {w.cells.map(([i, j]) => (
                    <rect key={`${i}:${j}`} x={i * w.cell_m - w.cell_m * 0.25} y={-(j + 1) * w.cell_m - w.cell_m * 0.25}
                          width={w.cell_m * 1.5} height={w.cell_m * 1.5} fill="#fff" />
                  ))}
                </g>
              </mask>
              <radialGradient id="world-fog" cx="50%" cy="50%" r="70%">
                <stop offset="0" stopColor="#1b1610" /><stop offset="1" stopColor="#070605" />
              </radialGradient>
              <filter id="world-soft" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation={w.cell_m * 0.35} /></filter>
            </defs>
            <rect x={view.x} y={view.y} width={view.s} height={view.s} fill="url(#world-fog)" />
            {[w.core_m, ...rings.map((r) => r.outer_m)].map((r, i) => (
              <circle key={r} cx="0" cy="0" r={r} fill="none" stroke={i ? "#3a2d1a" : "#5b4526"} strokeWidth={view.s / 320}
                      strokeDasharray={i ? `${view.s / 60} ${view.s / 80}` : undefined} />
            ))}
            {Array.from({ length: 8 }, (_, i) => {
              const a = (i * 45 + 22.5) * Math.PI / 180;
              return <line key={i} x1={Math.sin(a) * w.core_m} y1={-Math.cos(a) * w.core_m} x2={Math.sin(a) * w.radius_m} y2={-Math.cos(a) * w.radius_m}
                           stroke="#2c2216" strokeWidth={view.s / 400} />;
            })}
            <g filter="url(#world-soft)">
              {w.cells.map(([i, j]) => (
                <rect key={`${i}:${j}`} x={i * w.cell_m - w.cell_m * 0.15} y={-(j + 1) * w.cell_m - w.cell_m * 0.15}
                      width={w.cell_m * 1.3} height={w.cell_m * 1.3} fill="#d9c08a" opacity={tiles.length ? 0.18 : 0.55} />
              ))}
            </g>
            {tiles.length > 0 && <g mask="url(#world-reveal)" style={{ filter: TILE_FILTER }}>
              {tiles.map((t) => (
                <image key={t.key} href={api.heroTileUrl(t.key)} x={t.x} y={t.y} width={t.w + 0.5} height={t.h + 0.5} preserveAspectRatio="none" />
              ))}
            </g>}
            {w.routes.map((r) => (
              <polyline key={r.date + r.points.length} points={r.points.map(([x, y]) => `${x},${-y}`).join(" ")}
                        fill="none" stroke="#e3b64f" strokeOpacity={tiles.length ? 0.6 : 0.75} strokeWidth={Math.max(view.s / (tiles.length ? 420 : 260), 6)} strokeLinejoin="round" strokeLinecap="round" />
            ))}
            {rings.map((ring, ri) => {
              const inner = ri ? rings[ri - 1].outer_m : w.core_m;
              if (ring.outer_m - inner < view.s / 9) return null;  // zu klein in dieser Ansicht
              const rad = (inner + ring.outer_m) / 2;
              return sectorNames(ri).map((name, i) => {
                const a = i * 45 * Math.PI / 180, r = regionsByName[name];
                return <text key={name} x={Math.sin(a) * rad} y={-Math.cos(a) * rad} textAnchor="middle" fontSize={font} fontFamily="var(--font-cinzel), serif"
                             fill={r?.discovered ? TIP_YELLOW : "#5b4526"} style={{ paintOrder: "stroke" }} stroke="#000" strokeWidth={font / 6}>
                  {r?.discovered ? name : "???"}
                </text>;
              });
            })}
            {rings.map((ring) => (
              <text key={ring.name} x={ring.outer_m * 0.71} y={-ring.outer_m * 0.71} fontSize={font * 0.7} fill="#6b5a40" textAnchor="middle"
                    style={{ paintOrder: "stroke" }} stroke="#000" strokeWidth={font / 8}>{ring.name} · {num(ring.outer_m / 1000)} km</text>
            ))}
            {shown.map((d) => <DungeonTrack key={d.key} d={d} view={view} active={d.key === picked} onPick={() => pick(d.key)} />)}
            {teasers.map((d) => <Teaser key={d.key} x={d.x} y={d.y} size={icon * (d.key === picked ? 1.5 : 1)} title={`${d.name} (im Nebel) · Stufe ${d.level}`} />)}
            {placeTeasers.map((p) => <Teaser key={p.id} x={p.x} y={p.y} size={icon * 0.6} color={KIND_COLOR[p.kind]} title={`Unentdeckt · ${p.kind_label}`} />)}
            {found.map((p) => <PlaceMark key={p.id} p={p} size={icon} />)}
            <g>
              <circle cx="0" cy="0" r={view.s / 80} fill="#ff8000" stroke="#000" strokeWidth={view.s / 400} />
              <text x="0" y={view.s / 28} textAnchor="middle" fontSize={font * 0.8} fill="#efe3c8" stroke="#000" strokeWidth={font / 7} style={{ paintOrder: "stroke" }}>Zitadelle · Heimat</text>
            </g>
          </svg>
          <div className="absolute right-2 top-2 flex flex-col overflow-hidden rounded border border-[#4b3a22] bg-black/70 text-[15px] leading-none">
            <button type="button" aria-label="Hineinzoomen" onClick={() => { zoomAt(0.6); setMode("frei"); }} className="px-2.5 py-1.5 text-[#efe3c8] hover:text-[#ffd100]">+</button>
            <button type="button" aria-label="Herauszoomen" onClick={() => { zoomAt(1 / 0.6); setMode("frei"); }} className="border-t border-[#4b3a22] px-2.5 py-1.5 text-[#efe3c8] hover:text-[#ffd100]">−</button>
            <button type="button" aria-label="Zur Heimat" title="Zur Heimat" onClick={() => { setPicked(null); setMode("erkundet"); if (mode === "erkundet" && preset) setView(preset); }}
                    className="border-t border-[#4b3a22] px-2.5 py-1.5 text-[12px] text-[#efe3c8] hover:text-[#ffd100]">⌂</button>
          </div>
          <p className="pointer-events-none absolute bottom-2 left-2 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-muted">Ziehen · Mausrad oder zwei Finger zoomen · Doppelklick</p>
          </div>
          <div className="space-y-3 text-[12px]">
            {focus && <section className="rounded border border-[#4b3a22] bg-black/40 p-2">
              <div className="flex items-baseline justify-between gap-2">
                <h4 className="wow-title truncate text-[13px]" style={{ color: focus.heroic ? "#ff8000" : DUNGEON }}>{focus.name}</h4>
                <button type="button" onClick={() => { setPicked(null); setMode("erkundet"); }} className="text-[10px] text-muted hover:text-[#ffd100]">schließen</button>
              </div>
              <p className="text-[10px] text-muted">{TYPE_ICON[focus.type]} {focus.type_label} · <span style={{ color: levelColor(focus.level, heroLevel) }}>Stufe {focus.level}</span> · {num(focus.length_km)} km Strecke · {num(focus.km)} km {dir(focus.x, focus.y)}</p>
              {focus.discovered && <p className="mt-1 text-[11px] italic text-[#cbb98f]">„{focus.desc}“</p>}
              <ol className="mt-1.5 space-y-1">
                {focus.segments.map((s, i) => (
                  <li key={i}>
                    <div className="flex items-baseline justify-between gap-2">
                      <span style={{ color: s.cleared ? "#40c040" : "#efe3c8" }}>{s.cleared ? "✔" : `${i + 1}.`} {focus.discovered ? s.boss : "???"}</span>
                      <span className="shrink-0 tabular-nums text-[10px] text-muted">{Math.round(s.coverage * 100)} %{s.cleared_on ? ` · ${dm(s.cleared_on)}` : ""}</span>
                    </div>
                    <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-[#0a0807]">
                      <div className="h-full rounded-full" style={{ width: `${Math.min(100, s.coverage / 0.8 * 100)}%`, background: s.cleared ? "#40c040" : DUNGEON }} />
                    </div>
                  </li>
                ))}
              </ol>
              <p className="mt-1.5 text-[10px] text-muted">Belohnung: {focus.xp} EP + {focus.segments.length} × {focus.segments[0]?.xp} EP je Boss, {focus.gold} Gold, Beute · heroisch (alles in einem Lauf) +50 % EP und bessere Beute</p>
            </section>}
            {targets.length > 0 && <section>
              <h4 className="wow-title mb-1 text-[12px] text-[#ffd100]">Nächste Verliese</h4>
              <ul className="space-y-1">
                {targets.map((t) => (
                  <li key={t.key}>
                    <button type="button" onClick={() => pick(t.key)} className="w-full rounded border border-[#3a2d1a] bg-black/30 px-2 py-1 text-left hover:border-[#c08cff]">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="truncate font-semibold" style={{ color: DUNGEON }}>{TYPE_ICON[t.type]} {t.name}</span>
                        <span className="shrink-0 font-semibold tabular-nums" style={{ color: levelColor(t.level, heroLevel) }}>Stufe {t.level}</span>
                      </div>
                      <p className="text-[10px] text-muted">{num(t.km)} km {dir(t.x, t.y)} · {num(t.length_km)} km Strecke · {status(t).label}</p>
                    </button>
                  </li>
                ))}
              </ul>
            </section>}
            <section>
              <h4 className="wow-title mb-1 text-[12px] text-[#ffd100]">Schreine & Schätze ({found.length}/{pois.length})</h4>
              {found.length === 0 ? <p className="text-[11px] text-muted">Noch nichts – lauf in den Nebel.</p> : (
                <ul className="space-y-0.5">
                  {found.map((p) => (
                    <li key={p.id} className="flex items-baseline justify-between gap-2">
                      <span className="truncate" style={{ color: KIND_COLOR[p.kind] }}>{p.name}</span>
                      <span className="shrink-0 text-[10px] text-muted">{p.found_on ? dm(p.found_on) : ""}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            {rings.map((ring, ri) => {
              const list = w.regions.filter((r) => r.ring === ri);
              const n = list.filter((r) => r.discovered).length;
              return (
                <details key={ring.name} open={ri === 0}>
                  <summary className="wow-title cursor-pointer text-[12px] text-[#ffd100]">{ring.name} <span className="text-muted">· {n}/{list.length} · {list[0]?.xp} EP je Gebiet</span></summary>
                  <ul className="mt-1 space-y-1.5">
                    {list.map((r) => (
                      <li key={r.name}>
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="truncate font-semibold" style={{ color: r.discovered ? TIP_YELLOW : "#6b5a40" }}>{r.discovered ? r.name : "??? (unentdeckt)"}</span>
                          <span className="shrink-0 tabular-nums text-muted">{num(r.pct)} %</span>
                        </div>
                        <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-[#0a0807]">
                          <div className="h-full rounded-full" style={{ width: `${Math.min(100, r.pct * 4)}%`, background: r.discovered ? "#d9c08a" : "transparent" }} />
                        </div>
                        {r.discovered && r.discovered_on && <p className="text-[10px] text-muted">entdeckt am {dm(r.discovered_on)}</p>}
                      </li>
                    ))}
                  </ul>
                </details>
              );
            })}
          </div>
        </div>
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted">
          <span><span style={{ color: DUNGEON }}>━</span> Verlies-Strecke (gestrichelt = Abschnitt offen)</span>
          <span><span style={{ color: KIND_COLOR.schrein }}>◆</span> Schrein: 100 EP</span>
          <span><span style={{ color: KIND_COLOR.schatz }}>■</span> Schatz: Gold</span>
          <span>Stufe: <span style={{ color: "#40c040" }}>leicht</span> · <span style={{ color: "#ffff00" }}>ebenbürtig</span> · <span style={{ color: "#ff3b3b" }}>gefährlich</span></span>
        </div>
        <details className="mt-2 rounded border border-[#3a2d1a] bg-black/30 px-3 py-2 text-[12px]">
          <summary className="wow-title cursor-pointer text-[#ffd100]">Wie decke ich auf?</summary>
          <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[#d8c9a6]">
            <li><b>Nebel:</b> Die Karte ist in 150-m-Felder geteilt. Jedes Feld, durch das deine GPS-Spur läuft, wird aufgedeckt – du legst also einen rund 150 m breiten Streifen frei. Es zählen nur Läufe mit GPS (Garmin).</li>
            <li><b>Gebiet:</b> entdeckt, sobald ein einziges Feld darin aufgedeckt ist.</li>
            <li><b>Schrein / Schatz:</b> gefunden, wenn deine Spur auf etwa 250 m herankommt (Grenzland 400 m, Fernland 600 m).</li>
            <li><b>Verlies sichtbar:</b> Die Strecke erscheint, sobald aufgedeckte Felder etwa 300 m an sie heranreichen – oder du ein Stück davon läufst.</li>
            <li><b>Abschnitt bezwungen:</b> Ein einzelner Lauf muss 80 % des Abschnitts abdecken; als abgedeckt gilt ein Streckenpunkt, wenn deine Spur höchstens 50 m entfernt war. Die Richtung ist egal.</li>
            <li><b>Verlies bezwungen:</b> alle Abschnitte, gern über mehrere Läufe verteilt. Alle in <i>einem</i> Lauf = heroisch.</li>
            <li><b>Wege & Straßen</b> der Karte erscheinen nur in aufgedeckten Feldern.</li>
          </ul>
        </details>
        <p className="mt-1 text-[10px] text-muted">Ein Abschnitt gilt als bezwungen, wenn ein Lauf ihn zu 80 % abdeckt (50 m Toleranz) · Strecken erscheinen, sobald der Nebel in ihrer Nähe fällt · Karte und Wege © OpenStreetMap-Mitwirkende, Verliese geroutet mit BRouter · keine absoluten Koordinaten.</p>
      </Card>
      <HeroExpeditions dungeons={dungeons} heroLevel={heroLevel} onPick={pick} />
    </div>
  );
}

// --- Expeditionsbuch: alle Strecken-Verliese zum Sammeln, nach Landschaft --------------------------
function HeroExpeditions({ dungeons, heroLevel, onPick }: { dungeons: HeroDungeon[]; heroLevel: number; onPick: (key: string) => void }) {
  const [onlyOpen, setOnlyOpen] = useState(false);
  if (!dungeons.length) return null;
  const cleared = dungeons.filter((d) => d.cleared).length, heroic = dungeons.filter((d) => d.heroic).length;
  const bosses = dungeons.reduce((n, d) => n + d.segments.filter((s) => s.cleared).length, 0);
  const allBosses = dungeons.reduce((n, d) => n + d.segments.length, 0);
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <CardTitle title="Expeditionsbuch" sub={`${cleared}/${dungeons.length} Verliese · ${heroic} heroisch · ${bosses}/${allBosses} Abschnittsbosse · echte Wege durch Wald, Aue, Felder und Dörfer`} />
        <label className="flex shrink-0 items-center gap-1.5 text-[11px] text-muted">
          <input type="checkbox" checked={onlyOpen} onChange={(e) => setOnlyOpen(e.target.checked)} /> nur offene
        </label>
      </div>
      <div className="space-y-3">
        {TYPE_ORDER.map((type) => {
          const list = dungeons.filter((d) => d.type === type && (!onlyOpen || !d.cleared)).sort((a, b) => a.level - b.level);
          if (!list.length) return null;
          const all = dungeons.filter((d) => d.type === type);
          return (
            <section key={type}>
              <h4 className="wow-title mb-1.5 text-[12px] text-[#ffd100]">{TYPE_ICON[type]} {all[0].type_label} <span className="text-muted">· {all.filter((d) => d.cleared).length}/{all.length}</span></h4>
              <ul className="grid gap-1.5 @xl:grid-cols-2 @4xl:grid-cols-3">
                {list.map((d) => {
                  const st = status(d);
                  return (
                    <li key={d.key}>
                      <button type="button" onClick={() => onPick(d.key)}
                              className="w-full rounded border bg-black/30 px-2 py-1.5 text-left transition-colors hover:border-[#c08cff]"
                              style={{ borderColor: d.cleared ? "color-mix(in srgb, " + st.color + " 55%, transparent)" : "#3a2d1a", opacity: d.discovered ? 1 : 0.75 }}>
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="truncate font-semibold" style={{ color: d.discovered ? (d.heroic ? "#ff8000" : DUNGEON) : "#8a7a5c" }}>{d.name}</span>
                          <span className="shrink-0 text-[11px] font-semibold tabular-nums" style={{ color: levelColor(d.level, heroLevel) }}>{d.level}</span>
                        </div>
                        <div className="mt-1 flex items-center gap-1">
                          {d.segments.map((s, i) => (
                            <span key={i} title={`${d.discovered ? s.boss : "???"} · ${Math.round(s.coverage * 100)} %`}
                                  className="h-1.5 flex-1 rounded-full" style={{ background: s.cleared ? "#40c040" : s.coverage > 0 ? "#7a5aa8" : "#2a2116" }} />
                          ))}
                        </div>
                        <p className="mt-0.5 text-[10px] text-muted">
                          <span style={{ color: st.color }}>{st.label}</span> · {num(d.length_km)} km · {num(d.km)} km {dir(d.x, d.y)}
                          {d.cleared_on ? ` · ${dm(d.heroic_on ?? d.cleared_on)}` : ""}
                        </p>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}
      </div>
      <p className="mt-2 text-[10px] text-muted">Klick zeigt das Verlies auf der Karte · Stufe = Entfernung von der Heimat + Streckenlänge · Titel: Verliesgänger, Seenwächter, Hüter der Wälder, Dorfchronist, Deichgraf, Auenläufer, Feldherr, Heroischer Pfadfinder.</p>
    </Card>
  );
}
