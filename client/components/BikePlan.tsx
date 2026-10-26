"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { api, bikeZwoUrl, type BikeCheckpoints, type BikeExecution, type BikePlanOverview, type BikeSession, type BikeSessionStatus, type BikeStep } from "@/lib/api";
import { de, de0, dm, dur } from "@/lib/format";
import { powerZoneColor } from "@/components/Cycling";

// Farbe eines Schritts = Coggan-Zone seiner Mitte (wie Leistungskurve/Zonen auf /rad).
const COGGAN = [55, 75, 90, 105, 120, 150];
const stepColor = (s: BikeStep) => {
  if (!s.power_pct) return "var(--color-line)";
  const mid = (s.power_pct[0] + s.power_pct[1]) / 2;
  return powerZoneColor(COGGAN.findIndex((b) => mid <= b) + 1 || 7);
};

const STATUS: Record<BikeSessionStatus, { label: string; cls: string }> = {
  done: { label: "erledigt", cls: "border-good text-good" },
  run: { label: "als Lauf", cls: "border-good text-good" },
  missed: { label: "verpasst", cls: "border-bad text-bad" },
  skipped: { label: "ausgelassen", cls: "border-line text-muted" },
  today: { label: "heute", cls: "border-accent bg-accent text-white" },
  planned: { label: "geplant", cls: "border-line text-muted" },
};
const KIND: Record<string, string> = { z2: "Z2", z2_optional: "locker · optional", hard: "hart", test: "Test" };

export function StatusChip({ status }: { status: BikeSessionStatus }) {
  const s = STATUS[status];
  return <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${s.cls}`}>{s.label}</span>;
}

export function StepProfile({ steps, height = 40 }: { steps: BikeStep[]; height?: number }) {
  const timed = steps.filter((s) => s.duration_min);
  const total = timed.reduce((a, s) => a + (s.duration_min ?? 0), 0);
  if (!total) return null;
  return (
    <div className="flex items-end gap-px border-b border-line" style={{ height }} aria-hidden>
      {timed.map((s, i) => {
        const mid = s.power_pct ? (s.power_pct[0] + s.power_pct[1]) / 2 : 50;
        return <div key={i} title={`${s.label} · ${de0(s.duration_min)} min${s.watts ? ` · ${s.watts[0]}–${s.watts[1]} W` : ""}`}
          className="rounded-t-sm" style={{ width: `${((s.duration_min ?? 0) / total) * 100}%`, minWidth: 2, height: `${Math.min(100, (mid / 125) * 100)}%`, background: stepColor(s) }} />;
      })}
    </div>
  );
}

const target = (s: BikeSession) =>
  s.steering === "heart_rate" && s.hr ? `Puls ${s.hr[0] ? `${de0(s.hr[0])}–` : "< "}${de0(s.hr[1])} bpm` : s.kind === "test" ? "bis Abbruch" : "Watt (ERG)";

export function ExecutionLine({ ex }: { ex: BikeExecution | null }) {
  if (!ex) return null;
  if (ex.type === "hr_invalid") return <p className="text-[11px] text-muted">Puls dieser Fahrt unplausibel — keine Bewertung.</p>;
  if (ex.type === "test") return <p className="text-[11px]">FTP aus dem Test: <b>{ex.ftp != null ? `${de0(ex.ftp)} W` : "nicht erkannt"}</b></p>;
  if (ex.type === "hr_band") {
    return (
      <div className="text-[11px]">
        <div className="flex h-2 w-full overflow-hidden rounded" title="Zeit unter / im / über dem Puls-Band">
          <div style={{ width: `${ex.below_pct}%`, background: "#2a78d6" }} />
          <div style={{ width: `${ex.in_band_pct}%`, background: "var(--color-good)" }} />
          <div style={{ width: `${ex.above_pct}%`, background: "var(--color-bad)" }} />
        </div>
        <p className="mt-1 text-muted"><b className="text-ink">{ex.in_band_pct} % im Puls-Band</b> · {ex.below_pct} % darunter · {ex.above_pct} % darüber · Ø {ex.avg_hr} bpm · {ex.minutes} min ohne Ein-/Ausrollen</p>
      </div>
    );
  }
  return (
    <details className="text-[11px]">
      <summary className="cursor-pointer"><b>{ex.hit_pct ?? "–"} % der Intervallzeit im Ziel-Watt-Band</b>{ex.covered_pct < 100 ? ` · ${ex.covered_pct} % der Intervalle gefahren` : ""}</summary>
      <ul className="mt-1 space-y-0.5 tabular-nums text-muted">
        {ex.steps.map((s) => <li key={s.label} className="flex justify-between gap-2"><span>{s.label}</span><span>Ziel {s.target_w ? `${s.target_w[0]}–${s.target_w[1]}` : "–"} W · Ø {de0(s.avg_w)} W · {s.in_band_pct ?? "–"} %</span></li>)}
      </ul>
    </details>
  );
}

export function Warnings({ items }: { items?: string[] }) {
  if (!items?.length) return null;
  return (
    <ul className="grid gap-1">
      {items.map((w) => <li key={w} className="rounded border border-warn/40 bg-warn/10 px-2 py-1 text-[11px] font-medium text-warn">⚠ {w}</li>)}
    </ul>
  );
}

export function SessionCard({ s, open = false, actions }: { s: BikeSession; open?: boolean; actions?: ReactNode }) {
  return (
    <div className={`grid content-start gap-2 rounded-lg border bg-surface p-3 ${s.optional ? "border-dashed" : ""} ${s.kind === "hard" || s.kind === "test" ? "border-[color-mix(in_srgb,var(--color-bad)_35%,var(--color-line))]" : "border-line"}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[11px] text-muted">{s.weekday} {dm(s.date)}{s.gym ? ` · ${s.gym}` : ""}</p>
          <h4 className="truncate text-sm font-semibold">{s.title}</h4>
          <p className="text-[11px] text-muted">{KIND[s.kind] ?? s.kind} · {de0(s.duration_min)} min · {target(s)}</p>
        </div>
        <StatusChip status={s.status} />
      </div>
      <Warnings items={s.warnings} />
      <StepProfile steps={s.steps} />
      <details open={open}>
        <summary className="cursor-pointer text-[11px] text-muted">Schritte · Watt bei FTP {de0(s.ftp)} W</summary>
        <ul className="mt-1 space-y-0.5 text-[11px] tabular-nums">
          {s.steps.map((st, i) => (
            <li key={i} className="grid grid-cols-[2.5rem_minmax(0,1fr)_auto] gap-2">
              <span className="text-muted">{st.duration_min ? `${de0(st.duration_min)}′` : "–"}</span>
              <span className="truncate">{st.label}{st.cadence?.[0] ? <span className="text-muted"> · {st.cadence[0]}{st.cadence[1] ? `–${st.cadence[1]}` : "+"} U/min</span> : null}</span>
              <span className="font-semibold">{st.watts ? `${st.watts[0]}–${st.watts[1]} W` : ""}</span>
            </li>
          ))}
        </ul>
      </details>
      {s.status === "done" && s.ride && (
        <div className="grid gap-1 border-t border-line pt-2">
          <Link href={`/rad/${encodeURIComponent(s.ride.activity_id)}`} className="truncate text-[11px] text-accent">
            {s.ride.title ?? "Fahrt"} · {de0(s.ride.minutes)} min{s.ride.np ? ` · NP ${de0(s.ride.np)} W` : ""}{s.ride.avg_hr ? ` · Ø ${de0(s.ride.avg_hr)} bpm` : ""} →
          </Link>
          <ExecutionLine ex={s.execution} />
        </div>
      )}
      {s.status === "run" && s.run && <p className="border-t border-line pt-2 text-[11px] text-muted">Als Lauf: {de(s.run.km, 1)} km · {de0(s.run.minutes)} min{s.run.avg_hr ? ` · Ø ${de0(s.run.avg_hr)} bpm` : ""}</p>}
      {s.run_alternative && s.status !== "done" && s.status !== "run" && <p className="text-[11px] text-muted">Lauf-Variante: {s.run_alternative}</p>}
      {s.note && <p className="text-[11px] text-muted">{s.note}</p>}
      {s.zwo && <a href={bikeZwoUrl(s.id)} download className="justify-self-start text-[11px] font-semibold text-accent underline underline-offset-4">Zwift-Workout (.zwo)</a>}
      {actions}
    </div>
  );
}

// ---- Karte oben auf /rad: heute + Woche ----
export function PlanTodayCard({ data }: { data: BikePlanOverview }) {
  const weeks = data.weeks ?? [];
  const week = weeks.find((w) => w.current);
  const all = weeks.flatMap((w) => w.sessions);
  const today = data.today ?? "";
  const focus = all.find((s) => s.date === today) ?? all.find((s) => s.date > today);
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">{data.plan?.name}{week ? ` · Woche ${week.week}${week.phase ? ` · ${week.phase}` : ""}` : ""}</h3>
          <p className="text-[11px] text-muted">{week?.goal ?? (all.length && today > all[all.length - 1].date ? "Plan abgeschlossen" : "Plan beginnt bald")} · FTP {de0(data.ftp?.watts)} W ({FTP_SOURCE[data.ftp?.source ?? "plan"]})</p>
        </div>
        <Link href="/rad/plan" className="text-xs font-semibold text-accent">Ganzer Plan →</Link>
      </div>
      {week && (
        <div className="grid grid-cols-7 gap-1" aria-label="Diese Woche">
          {Array.from({ length: 7 }, (_, i) => {
            const d = new Date(week.start); d.setDate(d.getDate() + i);
            const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
            const s = week.sessions.find((x) => x.date === iso);
            return (
              <div key={iso} title={s ? `${s.title} · ${STATUS[s.status].label}` : "Ruhetag"}
                className={`grid min-w-0 gap-1 rounded-md px-0.5 py-1.5 text-center ${iso === today ? "ring-2 ring-accent" : ""} bg-surface-alt`}>
                <span className="text-[10px] text-muted">{["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][i]}</span>
                {s ? <span className={`truncate rounded text-[10px] font-semibold ${s.status === "done" || s.status === "run" ? "bg-good/15 text-good" : s.status === "missed" ? "text-bad line-through" : ""}`}>
                  {s.status === "done" || s.status === "run" ? "✓" : s.kind === "hard" ? "hart" : s.kind === "test" ? "Test" : s.optional ? "opt." : "Z2"}
                </span> : <span className="text-[10px] text-muted">–</span>}
              </div>
            );
          })}
        </div>
      )}
      {focus ? <div><p className="mb-1 text-[11px] text-muted">{focus.date === today ? "Heute" : "Als Nächstes"}</p><SessionCard s={focus} open={focus.date === today} /></div>
        : <p className="text-xs text-muted">Keine weitere Einheit im Plan.</p>}
    </div>
  );
}

export const FTP_SOURCE: Record<string, string> = { plan: "Startwert", ramp: "Ramp-Test", manual: "von Hand" };

// ---- Messpunkte ----
const fmtVal = (m: NonNullable<BikeCheckpoints["metrics"]>[number], v: number | null | undefined) =>
  v == null ? "–" : m.pace ? `${dur(v)}/km` : m.unit === "W/kg" ? de(v, 2) : m.unit === "kg" || m.unit === "ml/kg/min" || m.unit === "%" ? de(v, 1) : de0(v);
const CP_LABEL: Record<string, string> = { start: "Start", w4: "Woche 4", w8: "Woche 8" };

export function CheckpointTable({ data, onChange }: { data: BikeCheckpoints; onChange: (d: BikeCheckpoints) => void }) {
  const [edit, setEdit] = useState<{ cp: string; key: string } | null>(null);
  const [val, setVal] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const cps = data.checkpoints ?? [];
  const save = async (value: number | null) => {
    if (!edit) return;
    try {
      onChange(await api.bikePlanCheckpointSet({ checkpoint: edit.cp, key: edit.key, value }));
      setEdit(null); setErr(null);
    } catch (e) { setErr(String(e)); }
  };
  const parse = (m: NonNullable<BikeCheckpoints["metrics"]>[number], text: string) => {
    if (m.pace && text.includes(":")) { const [a, b] = text.split(":"); return Number(a) * 60 + Number(b); }
    return Number(text.replace(",", "."));
  };
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-xs tabular-nums">
          <thead><tr className="border-b border-line text-right text-muted">
            <th className="pb-1 text-left font-medium">Kennzahl</th>
            {cps.map((c) => <th key={c.key} className="pb-1 font-medium">{CP_LABEL[c.key] ?? c.key}<span className="block text-[10px] font-normal">{dm(c.date)}</span></th>)}
            <th className="pb-1 font-medium">jetzt</th><th className="pb-1 font-medium">Δ</th><th className="pb-1 font-medium">Ziel W8</th>
          </tr></thead>
          <tbody className="divide-y divide-line">
            {(data.metrics ?? []).map((m) => (
              <tr key={m.key} className="text-right align-top">
                <th scope="row" className="py-1.5 text-left font-medium">{m.name}<span className="block text-[10px] font-normal text-muted">{m.unit}{m.auto ? "" : " · nur Handwert"}</span></th>
                {cps.map((c) => {
                  const cell = m.values[c.key];
                  const editing = edit?.cp === c.key && edit.key === m.key;
                  return (
                    <td key={c.key} className="py-1.5">
                      {editing ? (
                        <form className="flex justify-end gap-1" onSubmit={(e) => { e.preventDefault(); const n = parse(m, val); if (Number.isFinite(n)) save(n); }}>
                          <input autoFocus value={val} onChange={(e) => setVal(e.target.value)} inputMode={m.pace ? "text" : "decimal"} placeholder={m.pace ? "6:30" : ""}
                            className="w-16 rounded border border-line bg-surface px-1 text-right text-base sm:text-xs" aria-label={`${m.name} ${CP_LABEL[c.key] ?? c.key}`} />
                          <button type="submit" className="text-accent">✓</button>
                          {cell?.source === "manual" && <button type="button" onClick={() => save(null)} className="text-muted" title="Handwert entfernen">✕</button>}
                          <button type="button" onClick={() => setEdit(null)} className="text-muted" title="Abbrechen">↩</button>
                        </form>
                      ) : (
                        <button type="button" onClick={() => { setEdit({ cp: c.key, key: m.key }); setVal(cell ? (m.pace ? dur(cell.value) : String(cell.value).replace(".", ",")) : ""); }}
                          title={cell ? `${cell.source === "auto" ? "automatisch" : cell.source === "manual" ? "von Hand" : "aus der Plan-Datei"}${cell.note ? ` · ${cell.note}` : ""} — antippen zum Überschreiben` : "antippen zum Eintragen"}
                          className={`${cell?.source === "plan" ? "text-muted" : ""} ${cell?.source === "manual" ? "underline decoration-dotted underline-offset-2" : ""}`}>
                          {cell?.estimated ? "~" : ""}{fmtVal(m, cell?.value)}
                        </button>
                      )}
                    </td>
                  );
                })}
                <td className="py-1.5 font-semibold" title={m.now?.note ?? undefined}>{fmtVal(m, m.now?.value)}</td>
                <td className={`py-1.5 ${m.verdict === "up" ? "text-good" : m.verdict === "down" ? "text-bad" : "text-muted"}`}>
                  {m.delta == null ? "–" : `${m.delta > 0 ? "+" : ""}${m.pace ? `${de0(m.delta)} s` : fmtVal(m, m.delta)}`}
                </td>
                <td className="py-1.5 text-muted">{m.target ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {err && <p role="alert" className="mt-2 text-xs text-bad">{err}</p>}
      <p className="mt-2 text-[11px] text-muted">Werte kommen automatisch aus Milon, sobald der Messtag erreicht ist; grau = aus der Plan-Datei, ~ = Schätzung, gepunktet = von Hand. Antippen überschreibt. Δ = neuester Wert gegen Start, grün = besser (egal ob dafür steigend oder fallend).</p>
      <details className="mt-2 text-[11px] text-muted">
        <summary className="cursor-pointer py-1">So wird gemessen</summary>
        <ul className="mt-1 space-y-1">{(data.metrics ?? []).map((m) => <li key={m.key}><b className="text-ink">{m.name}:</b> {m.how}{m.now?.note ? ` (Milon: ${m.now.note})` : ""}</li>)}</ul>
      </details>
    </div>
  );
}
