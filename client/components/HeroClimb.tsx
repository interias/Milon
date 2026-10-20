"use client";

import type { Hero } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { de0, dm } from "@/lib/format";

const TIP_YELLOW = "#ffd100";
const MUTED_LINE = "#4b3a22";
const W = 600, H = 170, X0 = 28, PAD_TOP = 22, BASE = H - 18;
const EVEREST = 8848;

const rar = (loot: string) => `var(--rar-${loot})`;

// --- Kletter-Bosse: Höhenprofil der Gipfel-Leiter mit Fortschritt ------------------------
export function HeroClimbCard({ data }: { data: Hero }) {
  const c = data.climb;
  if (!c?.peaks?.length) return null;
  const peaks = c.peaks;
  const step = (W - X0 - 16) / peaks.length;
  const pts = [{ x: X0, y: BASE, hm: 0 }, ...peaks.map((p, i) => ({ x: X0 + step * (i + 1), y: BASE - (p.hm / EVEREST) * (BASE - PAD_TOP), hm: p.hm }))];
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  const area = `${line} L${pts[pts.length - 1].x} ${BASE} L${X0} ${BASE} Z`;
  // x-Position des aktuellen Standes entlang der Leiter (nach Everest voll)
  const cum = c.total_hm;
  let cur = pts[pts.length - 1].x;
  for (let i = 1; i < pts.length; i++) {
    if (cum <= pts[i].hm) { cur = pts[i - 1].x + ((cum - pts[i - 1].hm) / (pts[i].hm - pts[i - 1].hm)) * (pts[i].x - pts[i - 1].x); break; }
  }
  const done = peaks.filter((p) => p.reached).length;
  return (
    <Card>
      <CardTitle title="Kletter-Bosse"
                 sub={`Zwift-Höhenmeter seit deinem Starttag · ${done}/${peaks.length} Gipfel · danach alle ${de0(EVEREST)} Hm eine Wiederholungsrunde`} />
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <p className="font-display text-2xl font-bold" style={{ color: TIP_YELLOW }}>{de0(cum)} <span className="text-sm font-normal text-muted">Hm</span></p>
        {c.next && <p className="text-[12px] text-muted">Noch {de0(c.next_in_hm)} Hm bis <span style={{ color: rar(c.next.loot) }}>{c.next.name}</span></p>}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full" role="img"
           aria-label={`Höhenprofil: ${de0(cum)} Höhenmeter, ${done} von ${peaks.length} Gipfeln erreicht`}>
        <defs>
          <clipPath id="climb-done"><rect x="0" y="0" width={cur} height={H} /></clipPath>
          <linearGradient id="climb-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#6fd3e8" stopOpacity=".55" /><stop offset="1" stopColor="#6fd3e8" stopOpacity=".08" />
          </linearGradient>
        </defs>
        <path d={area} fill="rgba(255,255,255,.04)" />
        <path d={line} fill="none" stroke={MUTED_LINE} strokeWidth="2" strokeLinejoin="round" />
        <g clipPath="url(#climb-done)">
          <path d={area} fill="url(#climb-fill)" />
          <path d={line} fill="none" stroke="#6fd3e8" strokeWidth="2.5" strokeLinejoin="round" />
        </g>
        <line x1={X0} y1={BASE} x2={W - 8} y2={BASE} stroke={MUTED_LINE} />
        {cum > 0 && cum < EVEREST && <circle cx={cur} cy={(() => {
          for (let i = 1; i < pts.length; i++) if (cum <= pts[i].hm) return pts[i - 1].y + ((cum - pts[i - 1].hm) / (pts[i].hm - pts[i - 1].hm)) * (pts[i].y - pts[i - 1].y);
          return pts[pts.length - 1].y;
        })()} r="4.5" fill="#fff" stroke="#6fd3e8" strokeWidth="2" />}
        {peaks.map((p, i) => (
          <g key={p.key}>
            <circle cx={pts[i + 1].x} cy={pts[i + 1].y} r="9" fill={p.reached ? rar(p.loot) : "#1a1510"} stroke={p.reached ? "#000" : MUTED_LINE} strokeWidth="1.5" />
            <text x={pts[i + 1].x} y={pts[i + 1].y + 3.5} textAnchor="middle" fontSize="10" fontWeight="700" fill={p.reached ? "#000" : "#9d9d9d"}>{i + 1}</text>
          </g>
        ))}
      </svg>
      <ol className="mt-1 space-y-1.5">
        {peaks.map((p, i) => (
          <li key={p.key} className="flex items-center gap-2.5">
            <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] font-bold"
                  style={{ background: p.reached ? rar(p.loot) : "#1a1510", color: p.reached ? "#000" : "#9d9d9d", border: `1px solid ${p.reached ? "#000" : MUTED_LINE}` }}>{i + 1}</span>
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-2">
                <p className="truncate text-[13px] font-semibold" style={{ color: p.reached ? rar(p.loot) : "#cfc3a8" }}>{p.name}</p>
                <span className="shrink-0 text-[11px] tabular-nums text-muted">{de0(p.hm)} Hm</span>
              </div>
              {p.reached ? (
                <p className="text-[11px] text-muted">Bezwungen am {dm(p.reached_on!)} · +{p.xp} EP + Beute</p>
              ) : (
                <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-black/40" aria-label={`${Math.round(p.progress * 100)} %`}>
                  <div className="h-full" style={{ width: `${p.progress * 100}%`, background: "#6fd3e8" }} />
                </div>
              )}
            </div>
          </li>
        ))}
        {c.rounds.map((r) => (
          <li key={r.n} className="flex items-baseline justify-between gap-2 pl-7 text-[12px]">
            <span style={{ color: rar("lila") }}>{r.name}</span>
            <span className="text-[11px] text-muted">{dm(r.reached_on)} · +{r.xp} EP</span>
          </li>
        ))}
      </ol>
      {c.rides === 0 && <p className="mt-2 text-[11px] text-muted">Noch keine Zwift-Fahrt seit deinem Starttag – jede Fahrt zählt ihre Höhenmeter mit.</p>}
    </Card>
  );
}

// --- Traumreiche: Zwift-Welten, Routen und Höhenmeter ------------------------------------
export function HeroDreamsCard({ data }: { data: Hero }) {
  const d = data.dreams;
  if (!d?.worlds) return null;
  const visited = new Map(d.worlds.map((w) => [w.world, w]));
  const top = d.route_tiers[d.route_tiers.length - 1];
  const rows = [...d.known.map((n) => visited.get(n) ?? { world: n, known: true, rides: 0, route_count: 0, routes: [], km: 0, hm: 0, first_on: "", last_on: "" }),
                ...d.worlds.filter((w) => !w.known)];
  return (
    <Card>
      <CardTitle title="Traumreiche"
                 sub={`Zwift-Welten und Routen aus deinen Fahrten · ${d.visited_known}/${d.known_total} Welten${d.all_worlds ? " · Traumwandler!" : ""} · Erfolge in der Kategorie Traumreiche`} />
      <ul className="grid gap-2 @3xl:grid-cols-2">
        {rows.map((w) => {
          const on = w.rides > 0;
          return (
            <li key={w.world} className="rounded-md border p-2.5" style={{ borderColor: on ? "#4b3a22" : "#2c2216", background: on ? "rgba(0,0,0,.3)" : "rgba(0,0,0,.15)", opacity: on ? 1 : 0.6 }}>
              <div className="flex items-baseline justify-between gap-2">
                <p className="truncate font-display text-[13px] font-bold" style={{ color: on ? TIP_YELLOW : "#9d9d9d" }}>{on ? "🌐 " : "🌫️ "}{w.world}</p>
                <span className="shrink-0 text-[11px] tabular-nums text-muted">{on ? `${w.rides} ${w.rides === 1 ? "Fahrt" : "Fahrten"}` : "unbesucht"}</span>
              </div>
              {on && <>
                <p className="text-[11px] text-muted">{w.route_count} {w.route_count === 1 ? "Route" : "Routen"} · {de0(w.km)} km · {de0(w.hm)} Hm · erstmals {dm(w.first_on)}</p>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-black/40" aria-label={`${w.route_count} von ${top} Routen`}>
                  <div className="h-full" style={{ width: `${Math.min(1, w.route_count / top) * 100}%`, background: "#6fd3e8" }} />
                </div>
              </>}
            </li>
          );
        })}
      </ul>
      <p className="mb-1 mt-3 font-display text-[11px] uppercase tracking-wider text-muted">Zwift-Höhenmeter · {de0(d.total_hm)} Hm</p>
      <div className="flex flex-wrap gap-1.5">
        {d.hm_tiers.map((t) => (
          <span key={t.hm} className="rounded border px-1.5 py-0.5 text-[11px] tabular-nums"
                style={{ borderColor: t.reached ? "var(--wow-gold)" : MUTED_LINE, color: t.reached ? TIP_YELLOW : "#9d9d9d" }}>{t.reached ? "✓ " : ""}{de0(t.hm)} Hm</span>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-muted">Routen-Stufen: {d.route_tiers.join(" / ")} verschiedene Routen in einer Welt · beste Welt aktuell {d.best_routes}.</p>
    </Card>
  );
}
