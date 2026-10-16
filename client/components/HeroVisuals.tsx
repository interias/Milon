"use client";

import { useEffect, useState } from "react";
import type { Hero, HeroAttribute, HeroItem } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { linePath } from "@/components/charts";
import { de0, dm } from "@/lib/format";
import { play } from "@/lib/hero-sound";

const rc = (r: string) => `var(--rar-${r})`;
const TIP_YELLOW = "#ffd100";

// --- Figur wie das Modell im WoW-Charakterfenster ------------------------------------------
// Angelegte Gegenstände leuchten an ihrer Körperstelle (Prozent der 2:3-Figur).
const SPOTS: Record<string, [number, number][]> = {
  kopf: [[50, 7]], hals: [[50, 17]], schultern: [[33, 21], [67, 21]], brust: [[50, 31]],
  handgelenk: [[29, 50], [71, 50]], haende: [[28, 56], [72, 56]], beine: [[43, 72], [57, 72]],
  fuesse: [[39, 94], [61, 94]], ring: [[73, 58]], schmuck: [[50, 47]],
};

export function HeroFigure({ color, equipment, aura }: { color: string; equipment: Record<string, HeroItem>; aura?: { color: string; pulse: boolean } | null }) {
  const mask = { maskImage: "url(/img/silhouette/front-filled.png)", WebkitMaskImage: "url(/img/silhouette/front-filled.png)",
                 maskSize: "contain", WebkitMaskSize: "contain", maskRepeat: "no-repeat", WebkitMaskRepeat: "no-repeat",
                 maskPosition: "center", WebkitMaskPosition: "center" } as React.CSSProperties;
  return (
    <div className="relative mx-auto h-full w-full max-w-[170px]" aria-hidden="true">
      {aura && <div className={`absolute inset-x-[4%] inset-y-[2%] rounded-[50%] ${aura.pulse ? "wow-aura-pulse" : ""}`}
                    style={{ background: `radial-gradient(ellipse at center, color-mix(in srgb, ${aura.color} 55%, transparent), transparent 70%)`, opacity: aura.pulse ? undefined : 0.6 }} />}
      <div className="absolute inset-x-[6%] bottom-0 h-[9%] rounded-[50%]"
           style={{ background: `radial-gradient(ellipse at center, color-mix(in srgb, ${color} 55%, transparent), transparent 70%)` }} />
      <div className="absolute inset-x-0 bottom-[3%] top-0">
        <div className="wow-figure h-full w-full" style={{ ["--fig" as string]: `color-mix(in srgb, ${color} 70%, transparent)` }}>
          <div className="h-full w-full" style={{ ...mask, background: `linear-gradient(180deg, ${color}, color-mix(in srgb, ${color} 30%, #000) 95%)` }} />
        </div>
        {Object.entries(equipment).flatMap(([slot, it]) => (SPOTS[slot] ?? []).map(([x, y], i) => (
          <span key={`${slot}-${i}`} className="absolute aspect-square w-[16%] -translate-x-1/2 -translate-y-1/2 rounded-full mix-blend-screen"
                style={{ left: `${x}%`, top: `${y}%`, background: `radial-gradient(circle, ${rc(it.rarity)}, transparent 68%)` }} />
        )))}
      </div>
    </div>
  );
}

// --- Spinnennetz der Attribute: jetzt vs. vor 30 Tagen ------------------------------------
export function AttributeRadar({ items, color }: { items: HeroAttribute[]; color: string }) {
  const size = 230, c = size / 2, r = 78;
  const n = items.length;
  const pt = (i: number, v: number) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
    return [c + Math.cos(a) * r * v, c + Math.sin(a) * r * v] as const;
  };
  const poly = (vals: number[]) => vals.map((v, i) => pt(i, v).join(",")).join(" ");
  const now = items.map((a) => (a.score ?? 0) / 100);
  const before = items.map((a) => ((a.score ?? 0) - (a.delta ?? 0)) / 100);
  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="mx-auto w-full max-w-[260px]" role="img"
         aria-label={`Attribute: ${items.map((a) => `${a.label} ${a.score ?? "–"}`).join(", ")}`}>
      {[0.25, 0.5, 0.75, 1].map((f) => <polygon key={f} points={poly(Array(n).fill(f))} fill="none" stroke="#4b3a22" strokeWidth={f === 1 ? 1.2 : 0.7} />)}
      {items.map((_, i) => { const [x, y] = pt(i, 1); return <line key={i} x1={c} y1={c} x2={x} y2={y} stroke="#4b3a22" strokeWidth="0.7" />; })}
      <polygon points={poly(before)} fill="none" stroke="#9d9d9d" strokeWidth="1.2" strokeDasharray="3 3" />
      <polygon points={poly(now)} fill={`color-mix(in srgb, ${color} 30%, transparent)`} stroke={color} strokeWidth="2" strokeLinejoin="round" />
      {now.map((v, i) => { const [x, y] = pt(i, v); return <circle key={i} cx={x} cy={y} r="2.8" fill={color} stroke="#000" strokeWidth=".8" />; })}
      {items.map((a, i) => {
        const [x, y] = pt(i, 1.24);
        return <text key={a.key} x={x} y={y} textAnchor="middle" dominantBaseline="middle" fontSize="10" fill={TIP_YELLOW}>
          {a.label}<tspan x={x} dy="11" fill="#efe3c8" fontWeight="700">{a.score ?? "–"}</tspan>
        </text>;
      })}
    </svg>
  );
}

// --- Chronik: Stufenverlauf + EP je Woche nach Quelle -------------------------------------
const SOURCES: [keyof Hero["progression"][number], string, string][] = [
  ["laufen", "Laufen", "#aad372"], ["kraft", "Kraft", "#c69b6d"], ["alltag", "Alltag", "#3fc7eb"],
  ["erfolge", "Erfolge", "#ffd100"], ["ruhebonus", "Ausgeruht", "#3d7bd9"],
  ["buffs", "Buffs", "#ff7d0a"], ["fokus", "Fokus", "#f48cba"], ["talente", "Talente", "#a330c9"], ["auftraege", "Aufträge", "#e6cc80"],
  ["bosse", "Bosse", "#c41e3a"], ["instanzen", "Instanzen", "#0070dd"], ["taeglich", "Tagesaufgaben", "#9d9d9d"], ["event", "Events", "#ff8a3d"], ["duelle", "Duelle", "#a9b8d8"],
];

export function HeroChronicle({ data }: { data: Hero }) {
  const prog = data.progression;
  if (prog.length < 2) return null;
  const W = 330, H = 160, L = 26, B = 20, T = 10;
  const lv = prog.map((p) => p.level);
  const lo = Math.floor(Math.min(...lv)), hi = Math.ceil(Math.max(...lv));
  const x = (i: number) => L + (i / (prog.length - 1)) * (W - L - 6);
  const y = (v: number) => T + (1 - (v - lo) / Math.max(1, hi - lo)) * (H - T - B);
  const pts = prog.map((p, i) => [x(i), y(p.level)] as const);
  const line = linePath(pts, true);
  const ticks = Array.from({ length: 5 }, (_, k) => Math.round((k / 4) * (prog.length - 1)));
  const step = Math.max(5, Math.ceil((hi - lo) / 5 / 5) * 5);
  const grid = Array.from({ length: Math.floor((hi - lo) / step) + 1 }, (_, k) => Math.ceil(lo / step) * step + k * step).filter((v) => v <= hi);

  const recent = prog.slice(-12);
  const maxWeek = Math.max(1, ...recent.map((p) => SOURCES.reduce((s, [k]) => s + (p[k] as number), 0)));
  const BW = 330, BH = 140;
  const slot = (BW - L) / recent.length;
  return (
    <Card>
      <CardTitle title="Chronik" sub={`Stufenverlauf seit ${dm(prog[0].week)} · EP je Woche nach Quelle (12 Wochen)`} />
      <div className="grid gap-5 @3xl:grid-cols-2">
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Stufe von ${lv[0].toFixed(0)} auf ${lv.at(-1)!.toFixed(1)}`}>
          <defs>
            <linearGradient id="wow-lv" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="#b36cf0" stopOpacity=".45" /><stop offset="1" stopColor="#b36cf0" stopOpacity="0" />
            </linearGradient>
          </defs>
          {grid.map((g) => <g key={g}>
            <line x1={L} x2={W - 6} y1={y(g)} y2={y(g)} stroke="#2c2216" />
            <text x={L - 6} y={y(g)} textAnchor="end" dominantBaseline="middle" fontSize="10" fill="#a99c80">{g}</text>
          </g>)}
          <path d={`${line} L ${x(prog.length - 1)} ${H - B} L ${L} ${H - B} Z`} fill="url(#wow-lv)" />
          <path d={line} fill="none" stroke="#b36cf0" strokeWidth="2.4" />
          <circle cx={pts.at(-1)![0]} cy={pts.at(-1)![1]} r="4" fill={TIP_YELLOW} stroke="#000" />
          {ticks.map((i) => <text key={i} x={x(i)} y={H - 6} textAnchor="middle" fontSize="10" fill="#a99c80">{dm(prog[i].week)}</text>)}
        </svg>
        <div>
          <svg viewBox={`0 0 ${BW} ${BH}`} className="w-full" role="img" aria-label="EP je Woche nach Quelle">
            {recent.map((p, i) => {
              let acc = 0;
              return <g key={p.week}>
                <title>{`Woche ${dm(p.week)}: ${SOURCES.map(([k, l]) => `${l} ${de0(p[k] as number)}`).join(", ")}`}</title>
                {SOURCES.map(([k, , col]) => {
                  const v = p[k] as number;
                  const h = (v / maxWeek) * (BH - B - 18);
                  acc += h;
                  return v > 0 ? <rect key={k} x={L + i * slot + slot * 0.15} width={slot * 0.7} y={BH - B - acc} height={h} fill={col} /> : null;
                })}
                {i % 3 === 0 && <text x={L + i * slot + slot / 2} y={BH - 6} textAnchor="middle" fontSize="10" fill="#a99c80">{dm(p.week)}</text>}
              </g>;
            })}
            <text x={L} y={10} fontSize="10" fill="#a99c80">max. {de0(maxWeek)} EP / Woche</text>
            <line x1={L} x2={BW} y1={BH - B} y2={BH - B} stroke="#4b3a22" />
          </svg>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted">
            {SOURCES.map(([k, label, col]) => <span key={k}><span className="mr-1 inline-block h-2 w-2 rounded-sm align-middle" style={{ background: col }} />{label}</span>)}
          </div>
        </div>
      </div>
    </Card>
  );
}

// --- Stufenaufstieg seit dem letzten Besuch ------------------------------------------------
export function LevelUpBanner({ level, title }: { level: number; title: string }) {
  const [show, setShow] = useState(false);
  useEffect(() => {
    try {
      const prev = Number(localStorage.getItem("milon.hero.level") || 0);
      localStorage.setItem("milon.hero.level", String(level));
      if (prev && level > prev) {
        setShow(true);
        play("levelup");
        const t = setTimeout(() => setShow(false), 5000);
        return () => clearTimeout(t);
      }
    } catch { /* ohne Speicher kein Banner */ }
  }, [level]);
  if (!show) return null;
  return (
    <div role="status" className="wow-banner pointer-events-none fixed left-1/2 top-20 z-50 rounded-lg border px-8 py-4 text-center"
         style={{ borderColor: "var(--wow-gold)", background: "radial-gradient(circle at 50% 0%, rgba(120,82,28,.9), rgba(12,9,6,.95))", boxShadow: "0 0 30px rgba(227,182,79,.5)" }}>
      <p className="font-display text-xs uppercase tracking-[.3em] text-muted">Stufenaufstieg</p>
      <p className="font-display text-4xl font-bold" style={{ color: TIP_YELLOW, textShadow: "0 0 18px rgba(255,209,0,.7)" }}>Stufe {level}</p>
      <p className="font-display text-sm" style={{ color: "var(--wow-gold-soft)" }}>&lt;{title}&gt;</p>
    </div>
  );
}
