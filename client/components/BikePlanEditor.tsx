"use client";

import { useState } from "react";
import { api, type BikePlanOverview, type BikeSession, type BikeStepInput, type BikeWeek } from "@/lib/api";
import { de0, dm } from "@/lib/format";
import { SessionCard, StepProfile, Warnings } from "@/components/BikePlan";

const KINDS: [string, string][] = [["z2", "Z2"], ["z2_optional", "locker · optional"], ["hard", "hart"], ["test", "Test"]];
const GYM_OPTIONS = ["Gym Oberkörper", "Gym Beine"];
const input = "rounded border border-line bg-surface px-1.5 py-1 text-base sm:text-xs";

type Props = { week: BikeWeek; data: BikePlanOverview; onData: (d: BikePlanOverview) => void };

// ---- Woche im Bearbeiten-Modus: alle Tage, Gym je Tag, Einheiten verschieben/anlegen/löschen ----
export function WeekEditor({ week, data, onData }: Props) {
  const [editing, setEditing] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [drag, setDrag] = useState<number | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const templates = uniqueTemplates(data);
  const run = async (p: Promise<BikePlanOverview>) => {
    try { onData(await p); setErr(null); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <div className="grid gap-2 px-3 pb-3">
      <Warnings items={week.warnings} />
      {err && <p role="alert" className="text-xs text-bad">{err}</p>}
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {(week.days ?? []).map((d) => {
          const s = week.sessions.find((x) => x.date === d.date);
          const gymValue = d.gym ?? "";
          return (
            <div key={d.date}
              onDragOver={(e) => { if (drag != null) { e.preventDefault(); setOver(d.date); } }}
              onDragLeave={() => setOver((o) => (o === d.date ? null : o))}
              onDrop={(e) => { e.preventDefault(); setOver(null); if (drag != null) run(api.bikePlanSessionUpdate(drag, { day: d.date })); setDrag(null); }}
              className={`grid content-start gap-2 rounded-lg border border-dashed p-2 ${over === d.date ? "border-accent bg-accent/5" : "border-line"} ${s && editing === s.id ? "sm:col-span-2 xl:col-span-3" : ""}`}>
              <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
                <span className="font-semibold">{d.weekday} {dm(d.date)}{d.hevy ? <span className="ml-1 font-normal text-muted">· Hevy: {d.hevy}</span> : null}</span>
                <select value={gymValue} onChange={(e) => run(api.bikePlanGym(d.date, e.target.value || null))} className={input} aria-label={`Gym am ${dm(d.date)}`}>
                  <option value="">kein Gym</option>
                  {[...new Set([...GYM_OPTIONS, ...(gymValue ? [gymValue] : [])])].map((g) => <option key={g} value={g}>{g}</option>)}
                </select>
              </div>
              {s && editing === s.id ? (
                <SessionEditor s={s} data={data} onCancel={() => setEditing(null)} onSaved={(o) => { onData(o); setEditing(null); }} />
              ) : s ? (
                <div draggable onDragStart={() => setDrag(s.id)} onDragEnd={() => { setDrag(null); setOver(null); }} className="cursor-grab">
                  <SessionCard s={s} actions={
                    <div className="flex flex-wrap gap-3 border-t border-line pt-2 text-[11px] font-semibold">
                      <button type="button" className="text-accent" onClick={() => setEditing(s.id)}>Bearbeiten</button>
                      <DeleteButton onConfirm={() => run(api.bikePlanSessionDelete(s.id))} />
                      <span className="ml-auto hidden font-normal text-muted sm:inline">ziehen zum Verschieben</span>
                    </div>} />
                </div>
              ) : (
                <NewSession templates={templates} onCreate={(copy) => run(api.bikePlanSessionCreate(d.date, copy))} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DeleteButton({ onConfirm }: { onConfirm: () => void }) {
  const [ask, setAsk] = useState(false);
  return ask
    ? <span className="flex gap-2"><button type="button" className="text-bad" onClick={onConfirm}>Wirklich löschen</button><button type="button" className="font-normal text-muted" onClick={() => setAsk(false)}>Nein</button></span>
    : <button type="button" className="text-muted" onClick={() => setAsk(true)}>Löschen</button>;
}

function uniqueTemplates(data: BikePlanOverview): { id: number; label: string }[] {
  const seen = new Map<string, { id: number; label: string }>();
  for (const s of (data.weeks ?? []).flatMap((w) => w.sessions)) {
    if (!seen.has(s.title)) seen.set(s.title, { id: s.id, label: `${s.title} · ${de0(s.duration_min)} min` });
  }
  return [...seen.values()];
}

function NewSession({ templates, onCreate }: { templates: { id: number; label: string }[]; onCreate: (copy: number | null) => void }) {
  const [pick, setPick] = useState("");
  return (
    <div className="flex flex-wrap items-center gap-2 py-2 text-[11px] text-muted">
      <span>Ruhetag</span>
      <select value={pick} onChange={(e) => setPick(e.target.value)} className={input} aria-label="Vorlage für neue Einheit">
        <option value="">leere Z2-Einheit</option>
        {templates.map((t) => <option key={t.id} value={t.id}>wie {t.label}</option>)}
      </select>
      <button type="button" className="font-semibold text-accent" onClick={() => onCreate(pick ? Number(pick) : null)}>+ Einheit</button>
    </div>
  );
}

// ---- Eine Einheit bearbeiten ----
const toInput = (s: BikeSession): BikeStepInput[] =>
  s.steps.map((st) => ({ label: st.label, duration_min: st.duration_min, power_pct: st.power_pct, cadence: st.cadence }));
const num = (v: string): number | null => (v.trim() === "" ? null : Number(v.replace(",", ".")));

function SessionEditor({ s, data, onCancel, onSaved }: { s: BikeSession; data: BikePlanOverview; onCancel: () => void; onSaved: (o: BikePlanOverview) => void }) {
  const [f, setF] = useState({
    day: s.date, title: s.title, kind: s.kind, steering: s.steering ?? "heart_rate",
    hr_min: s.hr?.[0] ?? null as number | null, hr_max: s.hr?.[1] ?? null as number | null,
    run_alternative: s.run_alternative ?? "", note: s.note ?? "",
  });
  const [steps, setSteps] = useState<BikeStepInput[]>(toInput(s));
  const [block, setBlock] = useState({ reps: 4, work: 4, workLo: 106, workHi: 112, rest: 3 });
  const [err, setErr] = useState<string | null>(null);
  const ftp = data.ftp?.watts ?? s.ftp;
  const total = steps.reduce((a, st) => a + (st.duration_min ?? 0), 0);
  const set = (i: number, patch: Partial<BikeStepInput>) => setSteps((xs) => xs.map((x, k) => (k === i ? { ...x, ...patch } : x)));
  const move = (i: number, by: number) => setSteps((xs) => {
    const j = i + by; if (j < 0 || j >= xs.length) return xs;
    const c = [...xs]; [c[i], c[j]] = [c[j], c[i]]; return c;
  });
  const addBlock = () => {
    const out: BikeStepInput[] = [];
    for (let r = 0; r < block.reps; r++) {
      out.push({ label: "Intervall", duration_min: block.work, power_pct: [block.workLo, block.workHi], cadence: [90, null] });
      out.push({ label: "Pause", duration_min: block.rest, power_pct: [50, 55], cadence: [90, null] });
    }
    const cool = steps.length && steps[steps.length - 1].label.toLowerCase().startsWith("ausrollen") ? steps.length - 1 : steps.length;
    setSteps([...steps.slice(0, cool), ...out, ...steps.slice(cool)]);
  };
  const save = async () => {
    try {
      onSaved(await api.bikePlanSessionUpdate(s.id, {
        ...f, optional: f.kind === "z2_optional", hr_min: f.steering === "heart_rate" ? f.hr_min : null,
        hr_max: f.steering === "heart_rate" ? f.hr_max : null, steps,
      }));
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };
  const preview = steps.map((st) => ({ ...st, watts: st.power_pct ? [Math.round(st.power_pct[0] * ftp / 100), Math.round(st.power_pct[1] * ftp / 100)] as [number, number] : null }));
  return (
    <form className="grid gap-2 rounded-lg border border-accent bg-surface p-3 text-xs" onSubmit={(e) => { e.preventDefault(); save(); }}>
      <div className="grid grid-cols-2 gap-2">
        <label className="col-span-2 grid gap-0.5 text-[11px] text-muted">Titel<input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} className={input} /></label>
        <label className="grid gap-0.5 text-[11px] text-muted">Tag<input type="date" value={f.day} min={data.plan?.start} max={data.plan?.end} onChange={(e) => setF({ ...f, day: e.target.value })} className={input} /></label>
        <label className="grid gap-0.5 text-[11px] text-muted">Art<select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })} className={input}>{KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        <label className="grid gap-0.5 text-[11px] text-muted">Steuerung<select value={f.steering} onChange={(e) => setF({ ...f, steering: e.target.value })} className={input}><option value="heart_rate">nach Puls</option><option value="power_erg">nach Watt (ERG)</option></select></label>
        {f.steering === "heart_rate" && <div className="grid gap-0.5 text-[11px] text-muted">Puls von–bis
          <span className="flex gap-1"><input inputMode="numeric" value={f.hr_min ?? ""} onChange={(e) => setF({ ...f, hr_min: num(e.target.value) })} className={`${input} w-16`} aria-label="Puls von" />
            <input inputMode="numeric" value={f.hr_max ?? ""} onChange={(e) => setF({ ...f, hr_max: num(e.target.value) })} className={`${input} w-16`} aria-label="Puls bis" /></span></div>}
      </div>
      {f.day !== s.date && <p className="text-[11px] text-muted">Ist {dm(f.day)} belegt, tauschen die beiden Einheiten den Tag.</p>}

      <div className="grid gap-1">
        <div className="flex items-baseline justify-between"><span className="font-semibold">Schritte</span><span className="text-[11px] text-muted">{de0(total)} min · Watt bei FTP {de0(ftp)} W</span></div>
        <StepProfile steps={preview} height={32} />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[440px] tabular-nums">
            <thead><tr className="text-left text-[10px] text-muted"><th className="font-medium">Schritt</th><th className="font-medium">min</th><th className="font-medium">% FTP</th><th className="font-medium">Watt</th><th className="font-medium">U/min</th><th /></tr></thead>
            <tbody>
              {steps.map((st, i) => (
                <tr key={i}>
                  <td className="py-0.5 pr-1"><input value={st.label} onChange={(e) => set(i, { label: e.target.value })} className={`${input} w-full`} aria-label={`Schritt ${i + 1} Bezeichnung`} /></td>
                  <td className="py-0.5 pr-1"><input inputMode="decimal" value={st.duration_min ?? ""} onChange={(e) => set(i, { duration_min: num(e.target.value) })} className={`${input} w-12`} aria-label={`Schritt ${i + 1} Minuten`} /></td>
                  <td className="py-0.5 pr-1"><span className="flex gap-0.5">
                    <input inputMode="numeric" value={st.power_pct?.[0] ?? ""} onChange={(e) => { const v = num(e.target.value); set(i, { power_pct: v == null ? null : [v, st.power_pct?.[1] ?? v] }); }} className={`${input} w-11`} aria-label={`Schritt ${i + 1} Prozent von`} />
                    <input inputMode="numeric" value={st.power_pct?.[1] ?? ""} onChange={(e) => { const v = num(e.target.value); set(i, { power_pct: v == null ? null : [st.power_pct?.[0] ?? v, v] }); }} className={`${input} w-11`} aria-label={`Schritt ${i + 1} Prozent bis`} />
                  </span></td>
                  <td className="py-0.5 pr-1 text-[11px] text-muted">{preview[i].watts ? `${preview[i].watts![0]}–${preview[i].watts![1]}` : "–"}</td>
                  <td className="py-0.5 pr-1"><input inputMode="numeric" value={st.cadence?.[0] ?? ""} onChange={(e) => set(i, { cadence: num(e.target.value) == null ? null : [num(e.target.value), st.cadence?.[1] ?? null] })} className={`${input} w-11`} aria-label={`Schritt ${i + 1} Trittfrequenz`} /></td>
                  <td className="whitespace-nowrap py-0.5 text-muted">
                    <button type="button" onClick={() => move(i, -1)} aria-label="nach oben" className="px-1">↑</button>
                    <button type="button" onClick={() => move(i, 1)} aria-label="nach unten" className="px-1">↓</button>
                    <button type="button" onClick={() => setSteps(steps.filter((_, k) => k !== i))} aria-label="Schritt entfernen" className="px-1">✕</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          <button type="button" className="font-semibold text-accent" onClick={() => setSteps([...steps, { label: "Grundlage", duration_min: 10, power_pct: [55, 64], cadence: [85, 90] }])}>+ Schritt</button>
          <span className="text-muted">·</span>
          <span className="flex flex-wrap items-center gap-1 text-muted">Block
            <input inputMode="numeric" value={block.reps} onChange={(e) => setBlock({ ...block, reps: Number(e.target.value) || 1 })} className={`${input} w-10`} aria-label="Wiederholungen" />×
            <input inputMode="decimal" value={block.work} onChange={(e) => setBlock({ ...block, work: Number(e.target.value.replace(",", ".")) || 1 })} className={`${input} w-10`} aria-label="Intervall Minuten" />min @
            <input inputMode="numeric" value={block.workLo} onChange={(e) => setBlock({ ...block, workLo: Number(e.target.value) || 0 })} className={`${input} w-11`} aria-label="Intervall Prozent von" />–
            <input inputMode="numeric" value={block.workHi} onChange={(e) => setBlock({ ...block, workHi: Number(e.target.value) || 0 })} className={`${input} w-11`} aria-label="Intervall Prozent bis" />%, Pause
            <input inputMode="decimal" value={block.rest} onChange={(e) => setBlock({ ...block, rest: Number(e.target.value.replace(",", ".")) || 1 })} className={`${input} w-10`} aria-label="Pause Minuten" />min
          </span>
          <button type="button" className="font-semibold text-accent" onClick={addBlock}>+ Block</button>
        </div>
      </div>

      <label className="grid gap-0.5 text-[11px] text-muted">Lauf-Variante<input value={f.run_alternative} onChange={(e) => setF({ ...f, run_alternative: e.target.value })} className={input} /></label>
      <label className="grid gap-0.5 text-[11px] text-muted">Notiz<input value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} className={input} /></label>
      {err && <p role="alert" className="text-bad">{err}</p>}
      <div className="flex gap-3">
        <button type="submit" className="rounded-md border border-accent bg-accent px-3 py-1 font-semibold text-white">Speichern</button>
        <button type="button" className="text-muted" onClick={onCancel}>Abbrechen</button>
      </div>
    </form>
  );
}
