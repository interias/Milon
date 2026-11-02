"use client";

import { useEffect, useState } from "react";
import { api, type WalkpadDaily, type WalkpadLive } from "@/lib/api";
import { Card } from "@/components/ui";
import { de, de0, dm, dur } from "@/lib/format";

const TILE = "rounded-lg border border-line px-3 py-2";

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return <div className={TILE}>
    <p className="text-[11px] text-muted">{label}</p>
    <p className="font-display text-lg font-bold tabular-nums">{value}</p>
    {sub && <p className="text-[11px] text-muted">{sub}</p>}
  </div>;
}

/** Laufende Session aus dem Recorder-Snapshot (alle ~2 s). */
export function WalkpadLiveStats({ live, speed, today }: { live: WalkpadLive | null; speed: number | null; today: { minutes: number; km: number; steps: number } | null }) {
  if (!live) return <p className="mt-4 text-xs text-muted">Keine laufende Session – die Werte erscheinen, sobald das Band läuft.</p>;
  const started = live.elapsed_s != null ? new Date(Date.now() - live.elapsed_s * 1000) : null;
  const km = (live.distance_m ?? 0) / 1000;
  const idle = (live.idle_s ?? 0) >= 30;
  return <div className="mt-4">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <p className="text-sm font-semibold">Diese Session{idle ? <span className="font-normal text-muted"> · steht seit {dur(live.idle_s)}</span> : null}</p>
      {started && <p className="text-xs text-muted">seit {started.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })} Uhr</p>}
    </div>
    <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
      <Tile label="Laufzeit" value={dur(live.elapsed_s)} />
      <Tile label="Strecke" value={`${de(km, 2)} km`} sub={live.elevation_m ? `${de0(live.elevation_m)} Hm bei ${de0(live.incline_pct)} %` : undefined} />
      <Tile label="Ø Tempo" value={`${de(live.avg_speed_kmh, 1)} km/h`} sub={live.max_speed_kmh ? `max. ${de(live.max_speed_kmh, 1)}` : undefined} />
      <Tile label="Pace" value={live.pace_s_per_km ? `${dur(live.pace_s_per_km)} /km` : "–"} />
      <Tile label="Schritte (geschätzt)" value={de0(live.steps)} sub={live.cadence_spm && speed ? `≈ ${de0(live.cadence_spm)} /min` : undefined} />
      <Tile label="Aktivkalorien" value={live.kcal != null ? `≈ ${de0(live.kcal)} kcal` : "–"}
        sub={live.kcal_incline ? `davon Steigung +${de0(live.kcal_incline)}` : live.kcal == null ? "kein Gewicht erfasst" : undefined} />
      <Tile label="Pad-Kalorien" value={live.kcal_pad != null ? `${de0(live.kcal_pad)} kcal` : "–"} sub="ohne Steigung" />
      <Tile label="Puls" value={live.hr_bpm ? `${de0(live.hr_bpm)} bpm` : "–"}
        sub={live.avg_hr ? `Ø ${de0(live.avg_hr)}` : "Hände auf die Sensoren"} />
    </div>
    {today && <p className="mt-2 text-xs text-muted">
      Heute inkl. dieser Session: {de0(today.minutes + (live.elapsed_s ?? 0) / 60)} min · {de(today.km + km, 2)} km · {de0(today.steps + live.steps)} Schritte
    </p>}
    {(live.since_packet_s ?? 0) > 10 && <p className="mt-1 text-xs text-bad">Seit {de0(live.since_packet_s)} s kein Datenpaket vom Pad.</p>}
  </div>;
}

const METRICS = [
  { key: "minutes", label: "Minuten", unit: "min", fmt: (v: number) => de0(v) },
  { key: "km", label: "Kilometer", unit: "km", fmt: (v: number) => de(v, 2) },
  { key: "steps", label: "Schritte", unit: "", fmt: (v: number) => de0(v) },
  { key: "kcal", label: "kcal", unit: "kcal", fmt: (v: number) => de0(v) },
] as const;
type MetricKey = (typeof METRICS)[number]["key"];

function niceStep(peak: number): number {
  const raw = peak / 4;
  const mag = 10 ** Math.floor(Math.log10(Math.max(raw, 1e-9)));
  return [1, 2, 2.5, 5, 10].map((f) => f * mag).find((s) => s >= raw) ?? mag * 10;
}

function delta(now: number, before: number | undefined, fmt: (v: number) => string): string | undefined {
  if (before == null) return undefined;
  const d = now - before;
  return `${d >= 0 ? "+" : "−"}${fmt(Math.abs(d))} ggü. davor`;
}

/** Tagesbalken der letzten `days` Tage mit umschaltbarer Kennzahl. */
export function WalkpadDailyStats({ days = 37, revision = 0, onLoaded }: { days?: number; revision?: number; onLoaded?: (d: WalkpadDaily) => void }) {
  const [data, setData] = useState<WalkpadDaily | null>(null);
  const [failed, setFailed] = useState(false);
  const [metric, setMetric] = useState<MetricKey>("minutes");
  useEffect(() => {
    let active = true;
    api.walkpadDaily(days).then((v) => { if (active) { setData(v); onLoaded?.(v); } }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [days, revision]); // eslint-disable-line react-hooks/exhaustive-deps

  const m = METRICS.find((x) => x.key === metric)!;
  const height = 200, labelH = 18, plotH = height - labelH - 4;
  const values = data?.series.map((s) => s[metric]) ?? [];
  const step = niceStep(Math.max(...values, 1));
  const max = Math.ceil(Math.max(...values, 1) / step) * step;
  const ticks = Array.from({ length: Math.round(max / step) + 1 }, (_, i) => i * step);
  const stride = Math.max(1, Math.ceil(days / 7));
  const t = data?.total, p = data?.previous ?? undefined;

  return <Card className="mt-4">
    <h2 className="text-sm font-semibold">Laufband · letzte {days} Tage</h2>
    {!data || !t ? <p className="mt-3 text-xs text-muted" role="status">{failed ? "Daten konnten nicht geladen werden." : "Wird geladen …"}</p> : <>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Tile label="Gehzeit" value={`${de0(t.minutes)} min`} sub={delta(t.minutes, p?.minutes, de0)} />
        <Tile label="Strecke" value={`${de(t.km, 1)} km`} sub={delta(t.km, p?.km, (v) => de(v, 1))} />
        <Tile label="Schritte" value={de0(t.steps)} sub={delta(t.steps, p?.steps, de0)} />
        <Tile label="Aktivkalorien" value={`≈ ${de0(t.kcal)}`} sub={t.elevation_m ? `${de0(t.elevation_m)} Hm` : undefined} />
        <Tile label="Aktive Tage" value={`${t.active_days} / ${days}`} sub={`${t.sessions} Sessions`} />
        <Tile label="Ø je aktivem Tag" value={t.per_active_day_min != null ? `${de0(t.per_active_day_min)} min` : "–"} />
        <Tile label="Ø Tempo" value={t.avg_speed_kmh != null ? `${de(t.avg_speed_kmh, 1)} km/h` : "–"} />
        <Tile label="Längste Session" value={t.longest_min != null ? `${de0(t.longest_min)} min` : "–"} sub={t.best_day ? `bester Tag ${dm(t.best_day)}` : undefined} />
      </div>

      <div className="mt-4 flex flex-wrap gap-1.5" role="group" aria-label="Kennzahl">
        {METRICS.map((x) => <button key={x.key} type="button" onClick={() => setMetric(x.key)} aria-pressed={metric === x.key}
          className={`rounded-full border px-3 py-1 text-xs ${metric === x.key ? "border-accent bg-accent text-white" : "border-line text-muted"}`}>{x.label}</button>)}
      </div>

      <div className="mt-3 flex" style={{ height }}>
        <div className="relative w-10 shrink-0 text-right text-[10px] leading-none text-muted sm:w-14">
          {ticks.map((v) => <span key={v} className="absolute right-2 -translate-y-1/2" style={{ top: height - labelH - 4 - (v / max) * plotH }}>{m.fmt(v)}</span>)}
        </div>
        <div className="relative flex min-w-0 flex-1 items-end gap-[2px]">
          {ticks.map((v) => <div key={v} aria-hidden className={`pointer-events-none absolute inset-x-0 border-t ${v === 0 ? "border-muted/50" : "border-line"}`}
            style={{ top: height - labelH - 4 - (v / max) * plotH }} />)}
          {data.series.map((s, i) => {
            const v = s[metric];
            const isToday = i === data.series.length - 1;
            const tip = s.sessions
              ? `${dm(s.date)}${isToday ? " (heute bisher)" : ""}: ${de0(s.minutes)} min · ${de(s.km, 2)} km · ${de0(s.steps)} Schritte · ≈ ${de0(s.kcal)} kcal` +
                (s.sessions > 1 ? ` · ${s.sessions} Sessions` : "")
              : `${dm(s.date)}: kein Walk`;
            return <div key={s.date} title={tip} className="group relative flex h-full min-w-0 flex-1 flex-col items-center justify-end">
              <div className="w-full rounded-t bg-accent group-hover:brightness-110"
                style={{ height: v > 0 ? Math.max(2, (v / max) * plotH) : 0, opacity: isToday ? 0.5 : 1 }} />
              <span className="mt-1 w-full whitespace-nowrap text-center text-[9px] leading-none text-muted" style={{ height: labelH }}>
                {(i % stride === 0 && i < data.series.length - stride) || isToday ? dm(s.date) : ""}
              </span>
            </div>;
          })}
        </div>
      </div>
      <p className="mt-2 text-xs text-muted">{m.label} je Tag{m.unit ? ` (${m.unit})` : ""} · heller Balken = heute, noch offen</p>

      <details className="mt-3 text-xs text-muted">
        <summary className="cursor-pointer py-1">Werte als Tabelle</summary>
        <div className="overflow-x-auto">
          <table className="mt-2 w-full tabular-nums">
            <thead><tr className="border-b border-line text-right"><th className="pb-1 text-left font-medium">Tag</th>
              <th className="pb-1 font-medium">min</th><th className="pb-1 font-medium">km</th><th className="pb-1 font-medium">Schritte</th>
              <th className="pb-1 font-medium">kcal</th><th className="pb-1 font-medium">km/h</th></tr></thead>
            <tbody className="divide-y divide-line">
              {[...data.series].reverse().filter((s) => s.sessions).map((s) => <tr key={s.date} className="text-right">
                <th scope="row" className="py-1 text-left font-medium text-ink">{dm(s.date)}</th>
                <td className="py-1">{de0(s.minutes)}</td><td className="py-1">{de(s.km, 2)}</td><td className="py-1">{de0(s.steps)}</td>
                <td className="py-1">{de0(s.kcal)}</td><td className="py-1">{de(s.avg_speed_kmh, 1)}</td>
              </tr>)}
            </tbody>
          </table>
        </div>
      </details>
      <p className="mt-3 text-xs text-muted">
        Vergleich mit den {days} Tagen davor. Schritte geschätzt aus der Strecke, kcal = Aktivkalorien nach der ACSM-Gehformel inkl. Steigung.
      </p>
    </>}
  </Card>;
}
