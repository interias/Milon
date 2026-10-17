"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, dungeonFileUrl, type Hero, type HeroDungeon, type HeroOwnRoute, type HeroPlace, type HeroTile } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { dm } from "@/lib/format";

const TIP_YELLOW = "#ffd100";
const DUNGEON = "#c08cff";
const RUN_TRACK = "#e3b64f";
const RIDE_TRACK = "#8fd16f";  // Radspur: grün gestrichelt, klar von der goldenen Laufspur abgesetzt
const DIRS = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"];
const KIND_COLOR: Record<HeroPlace["kind"], string> = { schrein: "#6fd3e8", schatz: TIP_YELLOW };
const TYPE_ICON: Record<string, string> = { wasser: "🌊", wald: "🌲", aue: "🪶", deich: "🏰", feld: "🌾", dorf: "🏘️", eigen: "🧭" };
const TYPE_ORDER = ["wasser", "wald", "aue", "deich", "feld", "dorf", "eigen"];
type ViewMode = "erkundet" | "nah" | "welt" | "fokus" | "frei" | "folgen";
// Kartenkacheln im Pergament-Ton der Seite
const TILE_FILTER = "sepia(.65) saturate(.8) brightness(.6) contrast(1.12)";
type Box = { x: number; y: number; s: number };
const FOLLOW_S = 1600;  // visible edge in m while following the own position
const LIVE_OWN = "#4cc9ff";
const LIVE_OTHER = "#7ee0a1";

// Expedition mode: own position, heading and target on top of the normal map. All coordinates are
// metres relative to home (from world.live), never raw lat/lon.
export type LiveMap = {
  own: string | null;                // session drawn as "mine"
  pos: [number, number] | null;      // last point of that session
  heading: number | null;            // compass heading in degrees from north, if known
  target: { kind: "poi" | "dungeon"; id: string; chosen: boolean } | null;
  setTarget?: (kind: "poi" | "dungeon", id: string) => void;
};

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
  if (d.provisional) return { label: "Vorläufig entdeckt", color: "#6fd3e8" };
  return { label: "Im Nebel", color: "#6b5a40" };
}

// --- Kartensymbole: feste Bildschirmgröße, klare Formen je Art -----------------------------------
type MarkKind = HeroPlace["kind"] | "verlies" | "heimat";
type MarkState = "found" | "near" | "far";
const NEAR_HINT_M = 1000;  // ab hier ist die Art des Ortes zu erkennen
const MARK_COLOR: Record<MarkKind, string> = { schatz: TIP_YELLOW, schrein: "#6fd3e8", verlies: DUNGEON, heimat: "#ff8000" };
const tier = (found: boolean, closest: number | null | undefined): MarkState =>
  found ? "found" : closest != null && closest <= NEAR_HINT_M ? "near" : "far";

function Glyph({ kind }: { kind: MarkKind }) {
  switch (kind) {
    case "schatz": return <>
      <path d="M-9 -2Q0 -11 9 -2Z" fill="#ffe27a" stroke="#3a2400" strokeWidth="1.2" />
      <rect x="-9" y="-2" width="18" height="11" rx="1.5" fill={TIP_YELLOW} stroke="#3a2400" strokeWidth="1.2" />
      <rect x="-1.6" y="-5" width="3.2" height="14" fill="#8a5a00" /><rect x="-2.4" y="0" width="4.8" height="4" rx="1" fill="#3a2400" />
    </>;
    case "schrein": return <>
      <path d="M0 -12L6.5 -3L0 6L-6.5 -3Z" fill="#9de8f5" stroke="#0c3a44" strokeWidth="1.2" />
      <path d="M0 -12L0 6M-6.5 -3H6.5" stroke="#0c3a44" strokeWidth=".8" opacity=".6" />
      <rect x="-7.5" y="7" width="15" height="3.5" rx="1" fill="#3a8fa0" stroke="#0c3a44" strokeWidth="1" />
    </>;
    case "verlies": return <>
      <path d="M-9 10V0A9 9 0 0 1 9 0V10Z" fill={DUNGEON} stroke="#1a0f24" strokeWidth="1.2" />
      <path d="M-4.5 10V1.5A4.5 4.5 0 0 1 4.5 1.5V10Z" fill="#1a0f24" />
      <path d="M-9 4H-4.5M4.5 4H9M-7 -4L-4 -2M7 -4L4 -2" stroke="#1a0f24" strokeWidth="1" />
    </>;
    default: return <path d="M-10 10V-3H-7V-8H-3V-3H3V-8H7V-3H10V10H3V4A3 3 0 0 0 -3 4V10Z" fill="#ff8000" stroke="#3a1a00" strokeWidth="1.2" />;
  }
}

function Marker({ x, y, unit, kind, state, level, levelCol, ring, selected, title, onSelect }: {
  x: number; y: number; unit: number; kind: MarkKind; state: MarkState; level?: number; levelCol?: string; ring?: string;
  selected: boolean; title: string; onSelect: () => void;
}) {
  const c = MARK_COLOR[kind];
  return (
    <g transform={`translate(${x} ${-y}) scale(${unit * (selected ? 1.25 : 1)})`} className="cursor-pointer"
       onClick={(e) => { e.stopPropagation(); onSelect(); }}>
      <title>{title}</title>
      <circle r="15" fill="#120d08" fillOpacity={state === "far" ? 0.75 : 0.92} stroke={selected ? "#fff" : state === "far" ? "#8a7a5c" : ring ?? c}
              strokeWidth={selected ? 2.5 : 2} strokeDasharray={state === "found" ? undefined : "4 3"} />
      {state === "far"
        ? <text y="6" textAnchor="middle" fontSize="18" fontWeight="700" fill="#d9c08a">?</text>
        : <g opacity={state === "near" ? 0.5 : 1}><Glyph kind={kind} /></g>}
      {state === "near" && <g transform="translate(10 -10)"><circle r="6" fill="#120d08" stroke="#d9c08a" strokeWidth="1.2" />
        <text y="3.5" textAnchor="middle" fontSize="9" fontWeight="700" fill="#d9c08a">?</text></g>}
      {level != null && <g transform="translate(0 19)">
        <rect x="-10" y="-6" width="20" height="11" rx="3" fill="#120d08" stroke={levelCol} strokeWidth="1" />
        <text y="3" textAnchor="middle" fontSize="8.5" fontWeight="700" fill={levelCol}>{level}</text>
      </g>}
    </g>
  );
}

function DungeonTrack({ d, unit, active, onPick }: { d: HeroDungeon; unit: number; active: boolean; onPick: () => void }) {
  const w = unit * (active ? 6 : 4);
  return (
    <g onClick={(e) => { e.stopPropagation(); onPick(); }} className="cursor-pointer">
      <title>{`${d.name} · ${d.type_label} · Stufe ${d.level} · ${status(d).label}`}</title>
      {d.segments.map((s, i) => (
        <polyline key={i} points={s.points.map(([x, y]) => `${x},${-y}`).join(" ")} fill="none"
                  stroke={s.cleared ? DUNGEON : "#7a5aa8"} strokeOpacity={s.cleared ? 0.95 : 0.75} strokeWidth={w}
                  strokeDasharray={s.cleared ? undefined : `${w * 2} ${w * 1.6}`} strokeLinecap="round" strokeLinejoin="round" />
      ))}
    </g>
  );
}

type Sel = { kind: "poi" | "verlies" | "heimat"; id: string };

const near = (m: number | null | undefined) => m != null ? `Dein aufgedeckter Bereich endet etwa ${m >= 1000 ? `${num(Math.round(m / 100) / 10)} km` : `${m} m`} davor.` : null;

function TargetButton({ onClick, active }: { onClick: () => void; active: boolean }) {
  return <button type="button" onClick={onClick} disabled={active}
                 className="mt-1.5 rounded border border-[#4b3a22] px-2 py-0.5 text-[11px] text-[#ffd100] hover:bg-[#2a2013] disabled:opacity-60">{active ? "✔ Aktuelles Ziel" : "Als Ziel setzen"}</button>;
}

function PlaceInfo({ p, onTarget, isTarget }: { p: HeroPlace; onTarget?: () => void; isTarget?: boolean }) {
  const st = tier(p.found, p.closest_m);
  if (st === "far") return <>
    <p className="wow-title text-[13px] text-[#d9c08a]">Unbekannter Ort</p>
    <p className="text-muted">Irgendetwas liegt hier im Nebel.</p>
    {near(p.closest_m) && <p className="mt-1 text-[11px] text-[#cbb98f]">{near(p.closest_m)}</p>}
    {onTarget && <TargetButton onClick={onTarget} active={!!isTarget} />}
  </>;
  if (st === "near") return <>
    <p className="wow-title text-[13px]" style={{ color: MARK_COLOR[p.kind] }}>{p.kind === "schrein" ? "Ein Schrein im Nebel" : "Ein Schatz im Nebel"}</p>
    <p className="text-muted">{p.kind === "schrein" ? "Ein schwaches Leuchten zwischen den Schwaden." : "Etwas glitzert zwischen den Schwaden."}</p>
    <p className="mt-1 text-[11px] text-[#cbb98f]">{near(p.closest_m)} Komm näher.</p>
    {onTarget && <TargetButton onClick={onTarget} active={!!isTarget} />}
  </>;
  return <>
    <p className="wow-title pr-4 text-[13px]" style={{ color: MARK_COLOR[p.kind] }}>{p.name}</p>
    <p className="text-[11px] text-muted">{p.kind_label} · Stufe {p.level} · {p.region}</p>
    <p className="mt-1">Belohnung: {p.xp} EP{p.gold ? `, ${p.gold} Gold` : ""}</p>
    {p.found_on && <p className="text-[11px] text-[#40c040]">gefunden am {dm(p.found_on)}{p.via === "rad" ? " · zu Rad (halbe Belohnung)" : ""}</p>}
    {p.provisional && <p className="text-[11px] text-[#6fd3e8]">vorläufig gefunden (Live)</p>}
    {onTarget && <TargetButton onClick={onTarget} active={!!isTarget} />}
  </>;
}

function DungeonInfo({ d, heroLevel, onDetails, onTarget, isTarget }: { d: HeroDungeon; heroLevel: number; onDetails: () => void; onTarget?: () => void; isTarget?: boolean }) {
  const st = status(d);
  const done = d.segments.filter((s) => s.cleared).length;
  return <>
    <p className="wow-title pr-4 text-[13px]" style={{ color: d.heroic ? "#ff8000" : DUNGEON }}>{TYPE_ICON[d.type]} {d.name}</p>
    <p className="text-[11px] text-muted">{d.type_label} · <span style={{ color: levelColor(d.level, heroLevel) }}>Stufe {d.level}</span> · {num(d.length_km)} km Strecke</p>
    {d.discovered || d.provisional ? <>
      <p className="mt-1 italic text-[#cbb98f]">„{d.desc}“</p>
      <p className="mt-1"><span style={{ color: st.color }}>{st.label}</span> · {done}/{d.segments.length} Abschnittsbosse</p>
      <button type="button" onClick={onDetails} className="mt-1.5 rounded border border-[#4b3a22] px-2 py-0.5 text-[11px] text-[#ffd100] hover:bg-[#2a2013]">Strecke & Bosse ansehen</button>
    </> : <>
      <p className="mt-1 text-muted">Die Strecke liegt noch im Nebel.</p>
      {near(d.closest_m) && <p className="mt-1 text-[11px] text-[#cbb98f]">{near(d.closest_m)}</p>}
    </>}
    {onTarget && <div><TargetButton onClick={onTarget} active={!!isTarget} /></div>}
    {(d.discovered || d.provisional) && <div className="mt-1.5"><a href={dungeonFileUrl(d.key, "gpx")} download className="inline-block rounded border border-[#4b3a22] px-2 py-0.5 text-[11px] text-[#ffd100] hover:bg-[#2a2013]">Strecke herunterladen (GPX)</a></div>}
  </>;
}

// --- Weltkarte: echte GPS-Routen decken den Nebel auf; Verliese sind echte Strecken -----------------
export function HeroWorld({ data, live, compact, onChanged }: { data: Hero; live?: LiveMap; compact?: boolean; onChanged?: () => void | Promise<void> }) {
  const w = data.world;
  const [mode, setMode] = useState<ViewMode>(live ? "folgen" : "erkundet");
  const livePos = live?.pos ?? null;
  const lx0 = livePos?.[0], ly0 = livePos?.[1];
  const [picked, setPicked] = useState<string | null>(null);
  const heroLevel = data.hero.level;
  const dungeons = useMemo(() => (w?.available ? w.dungeons ?? [] : []), [w]);
  const targets = useMemo(() => dungeons.filter((d) => !d.cleared).sort((a, b) => a.km - b.km).slice(0, 3), [dungeons]);
  const focus = dungeons.find((d) => d.key === picked) ?? null;
  const preset = useMemo<Box | null>(() => {
    if (!w?.available) return null;
    if (mode === "folgen" && lx0 != null && ly0 != null) return { x: lx0 - FOLLOW_S / 2, y: -ly0 - FOLLOW_S / 2, s: FOLLOW_S };
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
  }, [w, mode, targets, focus, lx0, ly0]);
  // Frei verschiebbare Ansicht: Voreinstellungen setzen sie, Ziehen/Zoomen ändert sie.
  const [view, setView] = useState<Box | null>(null);
  useEffect(() => { if (preset && mode !== "frei") setView(preset); }, [preset, mode]);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [sel, setSel] = useState<Sel | null>(null);
  const [pxW, setPxW] = useState(700);
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setPxW(el.clientWidth || 700));
    ro.observe(el);
    return () => ro.disconnect();
  }, [view == null]);  // eslint-disable-line react-hooks/exhaustive-deps
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
        setSel(null);
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
  const unit = view.s / Math.max(200, pxW) * (pxW < 500 ? 0.8 : 1);  // Symbol ≈ 24–30 px, unabhängig vom Zoom
  const targetKeys = new Set(targets.map((t) => t.key));
  const found = pois.filter((p) => p.found).sort((a, b) => (b.found_on ?? "").localeCompare(a.found_on ?? ""));
  const shown = dungeons.filter((d) => d.discovered || d.provisional);
  const dungeonMarks = dungeons.filter((d) => d.discovered || targetKeys.has(d.key) || d.key === picked || d.closest_m != null || (d.region && regionsByName[d.region]?.discovered));
  const poiMarks = pois.filter((p) => p.found || p.closest_m != null || regionsByName[p.region]?.discovered);
  const markAt = (d: HeroDungeon): [number, number] => {
    const first = d.segments[0]?.points[0];
    return d.discovered && first ? [first[0], first[1]] : [d.x, d.y];
  };
  const lv = w.live ?? null;
  const targetAt: [number, number] | null = (() => {
    if (!live?.target) return null;
    if (live.target.kind === "poi") { const p = pois.find((q) => q.id === live.target!.id); return p ? [p.x, p.y] : null; }
    const d = dungeons.find((q) => q.id === live.target!.id);
    return d ? markAt(d) : null;
  })();
  const setTarget = live?.setTarget;
  const selPoi = sel?.kind === "poi" ? pois.find((p) => p.id === sel.id) : undefined;
  const selDg = sel?.kind === "verlies" ? dungeons.find((d) => d.key === sel.id) : undefined;
  const selAt: [number, number] | null = selPoi ? [selPoi.x, selPoi.y] : selDg ? markAt(selDg) : sel?.kind === "heimat" ? [0, 0] : null;
  const discoveredCount = w.regions.filter((r) => r.discovered).length;
  const cleared = dungeons.filter((d) => d.cleared).length;
  return (
    <div className="space-y-3">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <CardTitle title="Weltkarte" sub={`Deine GPS-Routen lichten den Nebel · ${discoveredCount} von ${w.regions.length} Gebieten · ${cleared} von ${dungeons.length} Verliesen · ${num(w.km2)} km² erkundet`} />
          {!live && <Link href="/heldenreise/expedition" className="shrink-0 rounded border border-[#4b3a22] px-2 py-1 text-[11px] text-[#ffd100] hover:bg-[#2a2013]">Expeditionsmodus →</Link>}
          <div className="flex shrink-0 overflow-hidden rounded border border-[#4b3a22] text-[11px]">
            {([...(live ? [["folgen", "Folgen"]] : []), ["erkundet", "Erkundet"], ["nah", "Nahland"], ["welt", "30 km"]] as [ViewMode, string][]).map(([k, l]) => (
              <button key={k} type="button" onClick={() => { setMode(k); if (k === mode && preset) setView(preset); }}
                      className={`px-2 py-1 ${mode === k ? "bg-[#2a2013] text-[#ffd100]" : "text-muted hover:text-[#ffd100]"}`}>{l}</button>
            ))}
          </div>
        </div>
        <div className={compact ? "grid gap-4" : "grid gap-4 @3xl:grid-cols-[minmax(0,1fr)_260px]"}>
          <div className="relative">
          <svg ref={svgRef} viewBox={`${view.x} ${view.y} ${view.s} ${view.s}`} role="img"
               className="aspect-square w-full cursor-grab touch-none select-none rounded-md border border-[#3a2d1a] active:cursor-grabbing"
               aria-label={`Weltkarte: ${discoveredCount} von ${w.regions.length} Gebieten entdeckt`}
               onPointerDown={onPointerDown}
               onClickCapture={(e) => { if (dragged.current) { e.stopPropagation(); dragged.current = false; } }}
               onClick={() => setSel(null)}
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
                        fill="none" stroke={RUN_TRACK} strokeOpacity={tiles.length ? 0.6 : 0.75} strokeWidth={Math.max(view.s / (tiles.length ? 420 : 260), 6)} strokeLinejoin="round" strokeLinecap="round" />
            ))}
            {(w.rides ?? []).map((r) => (
              <polyline key={"rad" + r.date + r.points.length} points={r.points.map(([x, y]) => `${x},${-y}`).join(" ")} data-testid="ride-route"
                        fill="none" stroke={RIDE_TRACK} strokeOpacity={0.85} strokeWidth={Math.max(view.s / 600, 4)}
                        strokeDasharray={`${view.s / 90} ${view.s / 140}`} strokeLinejoin="round" strokeLinecap="round" />
            ))}
            {lv && lv.cells.length > 0 && <g filter="url(#world-soft)" data-testid="live-cells">
              {lv.cells.map(([i, j]) => (
                <rect key={`${i}:${j}`} x={i * w.cell_m - w.cell_m * 0.1} y={-(j + 1) * w.cell_m - w.cell_m * 0.1}
                      width={w.cell_m * 1.2} height={w.cell_m * 1.2} fill="#6fd3e8" opacity={0.42} />
              ))}
            </g>}
            {lv?.routes.map((r) => {
              const mine = r.session === live?.own;
              return <polyline key={r.session} points={r.points.map(([x, y]) => `${x},${-y}`).join(" ")} fill="none"
                               stroke={mine ? LIVE_OWN : LIVE_OTHER} strokeWidth={Math.max(view.s / 300, 6)} strokeOpacity={0.95}
                               strokeLinejoin="round" strokeLinecap="round" data-testid={mine ? "live-route-own" : "live-route"} />;
            })}
            {livePos && targetAt && <line x1={livePos[0]} y1={-livePos[1]} x2={targetAt[0]} y2={-targetAt[1]} stroke="#fff" strokeOpacity={0.6}
                                           strokeWidth={Math.max(view.s / 500, 4)} strokeDasharray={`${view.s / 60} ${view.s / 80}`} />}
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
            {shown.map((d) => <DungeonTrack key={d.key} d={d} unit={unit} active={d.key === picked} onPick={() => setSel({ kind: "verlies", id: d.key })} />)}
            <Marker x={0} y={0} unit={unit} kind="heimat" state="found" selected={sel?.kind === "heimat"} title="Zitadelle · Heimat"
                    onSelect={() => setSel({ kind: "heimat", id: "heimat" })} />
            {poiMarks.map((p) => {
              const st = tier(p.found, p.closest_m);
              return <Marker key={p.id} x={p.x} y={p.y} unit={unit * 0.85} kind={p.kind} state={st} selected={sel?.id === p.id}
                             ring={live?.target?.id === p.id ? "#fff" : p.provisional ? "#6fd3e8" : undefined}
                             title={st === "found" ? p.name : st === "near" ? `${p.kind_label} im Nebel` : "Unbekannter Ort"}
                             onSelect={() => setSel({ kind: "poi", id: p.id })} />;
            })}
            {dungeonMarks.map((d) => {
              const [mx, my] = markAt(d);
              const st: MarkState = d.discovered || d.provisional ? "found" : tier(false, d.closest_m) === "near" ? "near" : "far";
              return <Marker key={d.key} x={mx} y={my} unit={unit} kind="verlies" state={st === "far" ? "near" : st} level={d.level}
                             levelCol={levelColor(d.level, heroLevel)} ring={live?.target?.id === d.id ? "#fff" : d.heroic ? "#ff8000" : d.cleared ? "#40c040" : undefined}
                             selected={sel?.id === d.key} title={`${d.name} · Stufe ${d.level}`} onSelect={() => setSel({ kind: "verlies", id: d.key })} />;
            })}
            {livePos && (
              <g transform={`translate(${livePos[0]} ${-livePos[1]}) scale(${unit})`} data-testid="live-me">
                {live?.heading != null && <path d="M0 0L-13 -34A36 36 0 0 1 13 -34Z" transform={`rotate(${live.heading})`} fill={LIVE_OWN} fillOpacity={0.35} />}
                <circle r="9" fill={LIVE_OWN} stroke="#fff" strokeWidth="3" />
              </g>
            )}
          </svg>
          {sel && selAt && (() => {
            const lx = (selAt[0] - view.x) / view.s * 100, ly = (-selAt[1] - view.y) / view.s * 100;
            if (lx < -2 || lx > 102 || ly < -2 || ly > 102) return null;
            const below = ly < 35;
            const tx = lx < 22 ? "-12%" : lx > 78 ? "-88%" : "-50%";
            return (
              <div role="dialog" aria-label="Ort auf der Karte"
                   className="absolute z-10 w-60 rounded-md border border-[#5a4424] bg-[#0f0b07f2] p-2.5 text-[12px] text-[#efe3c8] shadow-[0_8px_30px_rgba(0,0,0,.7)]"
                   style={{ left: `${lx}%`, top: `${ly}%`, transform: `translate(${tx}, ${below ? "26px" : "calc(-100% - 26px)"})` }}
                   onPointerDown={(e) => e.stopPropagation()}>
                <button type="button" aria-label="Schließen" onClick={() => setSel(null)} className="absolute right-1.5 top-1 text-muted hover:text-[#ffd100]">×</button>
                {sel.kind === "heimat" && <>
                  <p className="wow-title text-[13px] text-[#ff8000]">Zitadelle · Heimat</p>
                  <p className="text-muted">Dein häufigster Startpunkt – die Mitte der Welt.</p>
                </>}
                {selPoi && <PlaceInfo p={selPoi} onTarget={setTarget && (() => setTarget("poi", selPoi.id))} isTarget={!!live?.target?.chosen && live.target.id === selPoi.id} />}
                {selDg && <DungeonInfo d={selDg} heroLevel={heroLevel} onDetails={() => { pick(selDg.key); setSel(null); }}
                                       onTarget={setTarget && (() => setTarget("dungeon", selDg.id))} isTarget={!!live?.target?.chosen && live.target.id === selDg.id} />}
              </div>
            );
          })()}
          <div className="absolute right-2 top-2 flex flex-col overflow-hidden rounded border border-[#4b3a22] bg-black/70 text-[15px] leading-none">
            <button type="button" aria-label="Hineinzoomen" onClick={() => { zoomAt(0.6); setMode("frei"); }} className="px-2.5 py-1.5 text-[#efe3c8] hover:text-[#ffd100]">+</button>
            <button type="button" aria-label="Herauszoomen" onClick={() => { zoomAt(1 / 0.6); setMode("frei"); }} className="border-t border-[#4b3a22] px-2.5 py-1.5 text-[#efe3c8] hover:text-[#ffd100]">−</button>
            <button type="button" aria-label={live ? "Auf mich zentrieren" : "Zur Heimat"} title={live ? "Auf mich zentrieren" : "Zur Heimat"} onClick={() => { setPicked(null); const m = live && livePos ? "folgen" : "erkundet"; setMode(m); if (mode === m && preset) setView(preset); }}
                    className="border-t border-[#4b3a22] px-2.5 py-1.5 text-[12px] text-[#efe3c8] hover:text-[#ffd100]">{live ? "◎" : "⌂"}</button>
          </div>
          <p className="pointer-events-none absolute bottom-2 left-2 hidden rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-muted sm:block">Ziehen · Mausrad oder zwei Finger zoomen · Doppelklick</p>
          </div>
          <div className="space-y-3 text-[12px]">
            {focus && <section className="rounded border border-[#4b3a22] bg-black/40 p-2">
              <div className="flex items-baseline justify-between gap-2">
                <h4 className="wow-title truncate text-[13px]" style={{ color: focus.heroic ? "#ff8000" : DUNGEON }}>{focus.name}</h4>
                <button type="button" onClick={() => { setPicked(null); setMode("erkundet"); }} className="text-[10px] text-muted hover:text-[#ffd100]">schließen</button>
              </div>
              <p className="text-[10px] text-muted">{TYPE_ICON[focus.type]} {focus.type_label} · <span style={{ color: levelColor(focus.level, heroLevel) }}>Stufe {focus.level}</span> · {num(focus.length_km)} km Strecke · {num(focus.km)} km {dir(focus.x, focus.y)}</p>
              {(focus.discovered || focus.provisional) && <p className="mt-1 text-[11px] italic text-[#cbb98f]">„{focus.desc}“</p>}
              <ol className="mt-1.5 space-y-1">
                {focus.segments.map((s, i) => (
                  <li key={i}>
                    <div className="flex items-baseline justify-between gap-2">
                      <span style={{ color: s.cleared || s.provisional ? "#40c040" : "#efe3c8" }}>{s.cleared || s.provisional ? "✔" : `${i + 1}.`} {focus.discovered || focus.provisional ? s.boss : "???"}</span>
                      <span className="shrink-0 tabular-nums text-[10px] text-muted">{Math.round(Math.max(s.coverage, s.live_coverage ?? 0) * 100)} %{s.cleared_on ? ` · ${dm(s.cleared_on)}` : ""}</span>
                    </div>
                    <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-[#0a0807]">
                      <div className="h-full rounded-full" style={{ width: `${Math.min(100, Math.max(s.coverage, s.live_coverage ?? 0) / 0.8 * 100)}%`, background: s.cleared || s.provisional ? "#40c040" : DUNGEON }} />
                    </div>
                  </li>
                ))}
              </ol>
              {(focus.discovered || focus.provisional) && <a href={dungeonFileUrl(focus.key, "gpx")} download className="mt-1.5 inline-block rounded border border-[#4b3a22] px-2 py-0.5 text-[11px] text-[#ffd100] hover:bg-[#2a2013]">Strecke herunterladen (GPX)</a>}
              {setTarget && <TargetButton onClick={() => setTarget("dungeon", focus.id)} active={!!live?.target?.chosen && live.target.id === focus.id} />}
              <p className="mt-1.5 text-[10px] text-muted">Belohnung: {focus.xp} EP + {focus.segments.length} × {focus.segments[0]?.xp} EP je Boss, {focus.gold} Gold, Beute · heroisch (alles in einem Lauf) +50 % EP und bessere Beute</p>
            </section>}
            {!compact && targets.length > 0 && <section>
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
            {!compact && <section>
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
            </section>}
            {!compact && rings.map((ring, ri) => {
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
                        {r.discovered && r.discovered_on && <p className="text-[10px] text-muted">entdeckt am {dm(r.discovered_on)}{r.via === "rad" ? " · zu Rad" : ""}</p>}
                      </li>
                    ))}
                  </ul>
                </details>
              );
            })}
          </div>
        </div>
        {!compact && <>
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted">
          <span><span style={{ color: RUN_TRACK }}>━</span> Laufspur</span>
          <span data-testid="legend-ride"><span style={{ color: RIDE_TRACK }}>┅</span> Radspur (halbe Sicht, halbe Erkundungs-EP)</span>
          <span><span style={{ color: DUNGEON }}>━</span> Verlies-Strecke (gestrichelt = Abschnitt offen)</span>
          <span><span style={{ color: KIND_COLOR.schrein }}>◆</span> Schrein: 100 EP</span>
          <span><span style={{ color: KIND_COLOR.schatz }}>■</span> Schatz: Gold</span>
          <span>Stufe: <span style={{ color: "#40c040" }}>leicht</span> · <span style={{ color: "#ffff00" }}>ebenbürtig</span> · <span style={{ color: "#ff3b3b" }}>gefährlich</span></span>
        </div>
        <details className="mt-2 rounded border border-[#3a2d1a] bg-black/30 px-3 py-2 text-[12px]">
          <summary className="wow-title cursor-pointer text-[#ffd100]">Wie decke ich auf?</summary>
          <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[#d8c9a6]">
            <li><b>Nebel:</b> Du siehst rund 300 m weit – alles in diesem Umkreis um deine GPS-Spur wird aufgedeckt, also ein gut 600 m breiter Streifen. Läufst du eine geschlossene Runde, ist auch die Fläche darin aufgedeckt. Es zählen nur Läufe mit GPS (Garmin).</li>
            <li><b>Zu Rad:</b> Radfahrten mit GPS decken mit halber Sichtweite (rund 150 m) auf und finden Gebiete, Schreine und Schätze – für halbe Erkundungs-EP und halbes Gold. Verlies-Abschnitte zählen nur zu Fuß. Wer etwas am selben Tag zu Fuß findet, bekommt die volle Belohnung.</li>
            <li><b>Gebiet:</b> entdeckt, sobald ein einziges Feld darin aufgedeckt ist.</li>
            <li><b>Schrein / Schatz:</b> gefunden, sobald er in Sichtweite kommt.</li>
            <li><b>Verlies sichtbar:</b> Die Strecke erscheint, sobald ein Stück davon in Sichtweite liegt.</li>
            <li><b>Abschnitt bezwungen:</b> Ein einzelner Lauf muss 80 % des Abschnitts abdecken; als abgedeckt gilt ein Streckenpunkt, wenn deine Spur höchstens 50 m entfernt war. Die Richtung ist egal.</li>
            <li><b>Verlies bezwungen:</b> alle Abschnitte, gern über mehrere Läufe verteilt. Alle in <i>einem</i> Lauf = heroisch.</li>
            <li><b>Wege & Straßen</b> der Karte erscheinen nur in aufgedeckten Feldern.</li>
          </ul>
        </details>
        <p className="mt-1 text-[10px] text-muted">Ein Abschnitt gilt als bezwungen, wenn ein Lauf ihn zu 80 % abdeckt (50 m Toleranz) · Strecken erscheinen, sobald der Nebel in ihrer Nähe fällt · Karte und Wege © OpenStreetMap-Mitwirkende, Verliese geroutet mit BRouter · keine absoluten Koordinaten.</p>
        </>}
      </Card>
      <HeroExpeditions dungeons={dungeons} heroLevel={heroLevel} onPick={pick} />
      {!compact && <HeroOwnRoutes onChanged={onChanged} onPick={pick} />}
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

// --- Eigene Strecken: GPX als privates Verlies oder als gelaufene Spur ----------------------------
function HeroOwnRoutes({ onChanged, onPick }: { onChanged?: () => void | Promise<void>; onPick: (key: string) => void }) {
  const [list, setList] = useState<HeroOwnRoute[] | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const refresh = () => api.heroOwnRoutes().then(setList).catch(() => setList([]));
  useEffect(() => { refresh(); }, []);

  async function upload(mode: "dungeon" | "track") {
    if (!file) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.heroOwnImport(file, mode);
      setMsg({ ok: true, text: r.kind === "dungeon"
        ? `Verlies „${r.name}“ angelegt · ${num(r.length_km)} km · ${r.segments} Abschnitte · Stufe ${r.level}`
        : `${r.name} importiert · ${num(r.length_km)} km${r.superseded ? " · zur selben Zeit gibt es einen Garmin-Lauf, der zählt" : ""}` });
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
      await refresh();
      await onChanged?.();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true);
    try {
      await api.heroOwnDelete(id);
      setConfirm(null);
      await refresh();
      await onChanged?.();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  const btn = "rounded border border-[#4b3a22] px-2 py-1 text-[11px] text-[#ffd100] hover:bg-[#2a2013] disabled:opacity-40";
  return (
    <Card>
      <CardTitle title="Eigene Strecken" sub="GPX-Datei (Track oder Route) als eigenes Verlies oder als gelaufene Spur · privat, nur auf deiner Karte" />
      <div className="flex flex-wrap items-center gap-2 text-[12px]">
        <input ref={inputRef} type="file" accept=".gpx,application/gpx+xml" disabled={busy} aria-label="GPX-Datei wählen"
               onChange={(e) => { setFile(e.target.files?.[0] ?? null); setMsg(null); }}
               className="min-w-0 max-w-full text-base text-muted file:mr-2 file:rounded file:border file:border-[#4b3a22] file:bg-black/30 file:px-2 file:py-1 file:text-[#ffd100] sm:text-[12px]" />
        <button type="button" className={btn} disabled={!file || busy} onClick={() => upload("dungeon")}>Als eigenes Verlies</button>
        <button type="button" className={btn} disabled={!file || busy} onClick={() => upload("track")}>Als gelaufene Spur</button>
      </div>
      <p data-testid="komoot-hint" className="mt-2 text-[11px] text-muted">Komoot: Tour in Komoot als GPX exportieren und hier hochladen.</p>
      {msg && <p className="mt-2 text-[12px]" style={{ color: msg.ok ? "#40c040" : "#ff6b6b" }}>{msg.text}</p>}
      {list && list.length > 0 && (
        <ul className="mt-3 space-y-1.5 text-[12px]">
          {list.map((o) => (
            <li key={o.id} className="flex flex-wrap items-baseline justify-between gap-2 rounded border border-[#3a2d1a] bg-black/30 px-2 py-1.5">
              <span className="min-w-0 truncate">
                <span className="mr-1 rounded border border-[#4b3a22] px-1 text-[10px] text-[#cbb98f]">eigen</span>
                {o.kind === "dungeon" && o.key
                  ? <button type="button" onClick={() => onPick(o.key!)} className="font-semibold hover:underline" style={{ color: DUNGEON }}>{TYPE_ICON.eigen} {o.name}</button>
                  : <span className="font-semibold text-[#efe3c8]">{o.name}</span>}
                <span className="text-[10px] text-muted"> · {num(o.length_km)} km
                  {o.kind === "dungeon" ? ` · Stufe ${o.level} · ${o.segments} Abschnitte · ${o.cleared ? "bezwungen" : o.discovered ? "entdeckt" : "im Nebel"}`
                    : o.superseded ? " · Garmin-Lauf zur selben Zeit zählt" : " · deckt den Nebel auf"}</span>
              </span>
              {confirm === o.id
                ? <span className="flex shrink-0 gap-1.5">
                    <button type="button" className={btn} disabled={busy} onClick={() => remove(o.id)}>Sicher? Löschen</button>
                    <button type="button" className="text-[11px] text-muted hover:text-[#ffd100]" onClick={() => setConfirm(null)}>abbrechen</button>
                  </span>
                : <button type="button" className="shrink-0 text-[11px] text-muted hover:text-[#ff6b6b]" onClick={() => setConfirm(o.id)}>löschen</button>}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[10px] text-muted">Verlies: 2–4 Abschnitte nach Länge, Stufe aus Entfernung und Länge, Abschnitte zählen erst durch Läufe ab dem Importtag. Spur: nur mit Zeitstempeln, deckt den Nebel auf wie ein Garmin-Lauf (ein Garmin-Lauf zur selben Zeit hat Vorrang), zählt aber nicht als Lauf. Mindestens 2 km, alle Punkte innerhalb der Weltkarte, höchstens 10 MiB. Löschen entfernt auch Fortschritt und Beute des Verlieses.</p>
    </Card>
  );
}
