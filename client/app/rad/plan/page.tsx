"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, type BikeCheckpoints, type BikePlanOverview } from "@/lib/api";
import { Card, CardTitle, Loading, ApiError, PageTitle } from "@/components/ui";
import { CheckpointTable, FTP_SOURCE, SessionCard, Warnings } from "@/components/BikePlan";
import { WeekEditor } from "@/components/BikePlanEditor";
import { de, de0, dm } from "@/lib/format";

function ImportCard({ onDone, replace }: { onDone: () => void; replace?: boolean }) {
  const ref = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const upload = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true); setMsg(null);
    try {
      const r = await api.bikePlanImport(file);
      setMsg(`„${r.name}“ übernommen: ${r.weeks} Wochen, ${r.sessions} Einheiten.`);
      onDone();
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); if (ref.current) ref.current.value = ""; }
  };
  return (
    <div className="grid gap-2">
      <p className="text-xs text-muted">{replace ? "Ein neuer Plan ersetzt den aktiven (der alte bleibt gespeichert, aber inaktiv)." : "Plan als JSON oder als HTML-Datei mit eingebettetem Datensatz (#agent-context) hochladen. Er wird nur lokal gespeichert."}</p>
      <label className="justify-self-start cursor-pointer rounded-md border border-accent px-3 py-1.5 text-xs font-semibold text-accent">
        {busy ? "lädt …" : "Plan-Datei wählen"}
        <input ref={ref} type="file" accept=".json,.html,.htm,application/json,text/html" className="sr-only" disabled={busy} onChange={(e) => upload(e.target.files?.[0])} />
      </label>
      {msg && <p role="status" className="text-xs">{msg}</p>}
    </div>
  );
}

export default function RadPlan() {
  const [data, setData] = useState<BikePlanOverview | null>(null);
  const [cps, setCps] = useState<BikeCheckpoints | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [ftpInput, setFtpInput] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [edit, setEdit] = useState(false);

  const load = () => {
    api.bikePlan().then(setData).catch((e) => setErr(String(e)));
    api.bikePlanCheckpoints().then(setCps).catch(() => setCps(null));
  };
  useEffect(load, []);

  if (err) return <><PageTitle title="Rad-Plan" /><ApiError error={err} /></>;
  if (!data) return <><PageTitle title="Rad-Plan" /><Loading /></>;
  if (!data.plan) {
    return <>
      <PageTitle title="Rad-Plan" sub="Trainingsblock mit Watt aus deiner FTP" />
      <Card><CardTitle title="Plan importieren" /><ImportCard onDone={load} /></Card>
    </>;
  }

  const ftp = data.ftp!;
  const weeks = data.weeks ?? [];
  const progress = data.progress!;
  const bg = data.background ?? {};
  const saveFtp = async () => {
    const w = Number(ftpInput.replace(",", "."));
    if (!Number.isFinite(w) || w < 50) return;
    await api.bikePlanFtp(w); setFtpInput(""); load();
  };

  return <>
    <PageTitle title={data.plan.name} sub={`${dm(data.plan.start)}–${dm(data.plan.end)} · ${weeks.length} Wochen · Watt aus der Plan-FTP`} />
    <p className="-mt-2 mb-4 text-xs"><Link href="/rad" className="text-accent">← Rad</Link></p>

    <div className="grid items-start gap-4 [&>*]:min-w-0 lg:grid-cols-2">
      <Card>
        <CardTitle title="FTP" sub="Grundlage aller Watt im Plan — Ramp-Test wird erkannt (75 % der besten Minute), ein Handwert übersteuert" />
        <p className="text-3xl font-semibold tabular-nums">{de0(ftp.watts)} <span className="text-base font-normal text-muted">W</span>
          {ftp.wkg != null && <span className="ml-2 text-sm font-normal text-muted">{de(ftp.wkg, 2)} W/kg</span>}</p>
        <p className="text-[11px] text-muted">seit {dm(ftp.date)} · {FTP_SOURCE[ftp.source]}</p>
        <ul className="mt-3 divide-y divide-line text-xs tabular-nums">
          {[...ftp.history].reverse().map((e, i) => (
            <li key={`${e.source}-${e.id ?? i}`} className="flex items-center justify-between gap-3 py-1.5">
              <span className="text-muted">{dm(e.date)} · {FTP_SOURCE[e.source]}</span>
              <span className="flex items-center gap-2"><b>{de0(e.watts)} W</b>
                {e.source === "manual" && <button type="button" className="text-muted" title="Handwert löschen" onClick={async () => { await api.bikePlanFtpDelete(Number(e.id)); load(); }}>✕</button>}
                {e.source === "ramp" && e.id && <Link href={`/rad/${encodeURIComponent(String(e.id))}`} className="text-accent">Fahrt →</Link>}
              </span>
            </li>
          ))}
        </ul>
        <form className="mt-3 flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); saveFtp(); }}>
          <input value={ftpInput} onChange={(e) => setFtpInput(e.target.value)} inputMode="numeric" placeholder="z. B. 205"
            className="w-24 rounded-md border border-line bg-surface px-2 py-1 text-base sm:text-sm" aria-label="FTP von Hand ab heute" />
          <button type="submit" className="rounded-md border border-accent px-3 py-1 text-xs font-semibold text-accent">Ab heute setzen</button>
        </form>
      </Card>

      <Card>
        <CardTitle title="Stand" sub="Kern-Einheiten (ohne optionale) erledigt — auf dem Rad oder als Lauf" />
        <p className="text-3xl font-semibold tabular-nums">{progress.core_done}<span className="text-base font-normal text-muted"> / {progress.core}</span></p>
        <div className="mt-2 h-2 overflow-hidden rounded bg-surface-alt"><div className="h-full bg-accent" style={{ width: `${(progress.core_done / Math.max(1, progress.core)) * 100}%` }} /></div>
        <p className="mt-2 text-[11px] text-muted">{progress.optional_done} optionale gefahren · {progress.missed} verpasst</p>
        {(data.zones ?? []).length > 0 && (
          <table className="mt-3 w-full text-xs tabular-nums">
            <tbody className="divide-y divide-line">
              {data.zones!.map((z) => <tr key={z.zone}><td className="py-1">{z.zone}</td><td className="py-1 text-right text-muted">{z.from_pct}–{z.to_pct} %</td><td className="py-1 text-right font-semibold">{z.watts[0]}–{z.watts[1]} W</td></tr>)}
            </tbody>
          </table>
        )}
      </Card>
    </div>

    <section aria-label="Wochen" className="mt-4 grid gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Wochen</h2>
        <button type="button" onClick={() => setEdit(!edit)} aria-pressed={edit}
          className={`rounded-md border px-3 py-1 text-xs font-semibold ${edit ? "border-accent bg-accent text-white" : "border-accent text-accent"}`}>
          {edit ? "Fertig" : "Bearbeiten"}
        </button>
      </div>
      {edit && <p className="text-[11px] text-muted">Einheiten auf einen anderen Tag ziehen (belegter Tag = tauschen), bearbeiten, löschen oder an Ruhetagen neu anlegen. Gym-Tage je Tag festlegen; Krafttrainings aus Hevy zählen für die Regeln automatisch mit.</p>}
      {weeks.map((w) => {
        const done = w.sessions.filter((s) => s.status === "done" || s.status === "run").length;
        return (
          <details key={w.week} open={w.current || undefined} className="rounded-lg border border-line bg-surface">
            <summary className="flex cursor-pointer flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-3">
              <span className="text-base font-semibold">Woche {w.week}</span>
              {w.phase && <span className="rounded-full border border-line px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted">{w.phase}</span>}
              {w.current && <span className="rounded-full bg-accent px-2 py-0.5 text-[10px] font-semibold text-white">aktuell</span>}
              <span className="min-w-0 flex-1 text-xs text-muted">{w.goal}</span>
              <span className="text-[11px] tabular-nums text-muted">{dm(w.start)}–{dm(w.end)} · {done}/{w.sessions.length} · {de0(w.sessions.reduce((a, s) => a + (s.duration_min ?? 0), 0))} min</span>
              {(w.warnings?.length || w.sessions.some((s) => s.warnings?.length)) ? <span className="text-[11px] font-semibold text-warn">⚠ Regel</span> : null}
            </summary>
            {edit ? <WeekEditor week={w} data={data} onData={setData} /> : <>
              {w.warnings?.length ? <div className="px-3 pb-2"><Warnings items={w.warnings} /></div> : null}
              <div className="grid gap-2 px-3 pb-3 sm:grid-cols-2 xl:grid-cols-3">{w.sessions.map((s) => <SessionCard key={s.id} s={s} />)}</div>
            </>}
          </details>
        );
      })}
    </section>

    <div className="mt-4 grid gap-4 [&>*]:min-w-0">
      <Card>
        <CardTitle title="Messpunkte" sub="Start · Woche 4 · Woche 8 — automatisch aus Milon, sobald der Tag erreicht ist" />
        {cps ? (cps.plan ? <CheckpointTable data={cps} onChange={setCps} /> : <p className="text-xs text-muted">–</p>) : <Loading />}
      </Card>

      <Card>
        <details>
          <summary className="cursor-pointer text-sm font-semibold">Hintergrund · Regeln, während der Fahrt, Zwift, Studien</summary>
          <div className="mt-3 grid gap-4 text-xs lg:grid-cols-2">
            {bg.weekly_template?.days && <div>
              <h4 className="mb-1 font-semibold">Wochenschema</h4>
              <ul className="space-y-0.5">{Object.entries(bg.weekly_template.days).map(([d, t]) => <li key={d}><b>{d}</b> · <span className="text-muted">{t}</span></li>)}</ul>
              {bg.weekly_template.rules && <ul className="mt-2 list-disc space-y-0.5 pl-4 text-muted">{bg.weekly_template.rules.map((r) => <li key={r}>{r}</li>)}</ul>}
            </div>}
            {bg.in_ride_rules && <div>
              <h4 className="mb-1 font-semibold">Während der Fahrt</h4>
              <ul className="space-y-1">{bg.in_ride_rules.map((r) => <li key={r.when}><b>{r.when}</b> → <span className="text-muted">{r.then}</span></li>)}</ul>
            </div>}
            {bg.zwift && <div>
              <h4 className="mb-1 font-semibold">Zwift</h4>
              {bg.zwift.setup && <ul className="list-disc space-y-0.5 pl-4 text-muted">{bg.zwift.setup.map((x) => <li key={x}>{x}</li>)}</ul>}
              {bg.zwift.z2_routes && <p className="mt-1 text-muted">Z2-Routen: {bg.zwift.z2_routes.join(", ")}</p>}
              {bg.zwift.erg_spiral && <p className="mt-1 text-muted">ERG-Spirale: {bg.zwift.erg_spiral}</p>}
            </div>}
            {(bg.expectations || bg.open_points) && <div>
              <h4 className="mb-1 font-semibold">Erwartung & offene Punkte</h4>
              {bg.expectations && <ul className="space-y-0.5 text-muted">{Object.values(bg.expectations).map((x) => <li key={x}>{x}</li>)}</ul>}
              {bg.open_points && <ul className="mt-2 list-disc space-y-0.5 pl-4 text-muted">{bg.open_points.map((x) => <li key={x}>{x}</li>)}</ul>}
            </div>}
            {bg.evidence && <div className="lg:col-span-2">
              <h4 className="mb-1 font-semibold">Studien (Zusammenfassungen, vor Übernahme prüfen)</h4>
              <ul className="space-y-1">{bg.evidence.map((e) => <li key={e.claim}><span>{e.claim}</span> <span className="text-muted">— {e.url ? <a href={e.url} target="_blank" rel="noreferrer" className="underline underline-offset-2">{e.source}</a> : e.source}</span></li>)}</ul>
            </div>}
          </div>
        </details>
      </Card>

      <Card>
        <CardTitle title="Plan verwalten" />
        <ImportCard onDone={load} replace />
        <div className="mt-3 border-t border-line pt-3">
          {confirmDelete ? (
            <span className="flex flex-wrap items-center gap-2 text-xs">Plan samt Handwerten löschen?
              <button type="button" className="rounded-md border border-bad px-2 py-1 font-semibold text-bad" onClick={async () => { await api.bikePlanDelete(data.plan!.id); setConfirmDelete(false); load(); }}>Ja, löschen</button>
              <button type="button" className="text-muted" onClick={() => setConfirmDelete(false)}>Abbrechen</button>
            </span>
          ) : <button type="button" className="text-xs text-muted underline underline-offset-4" onClick={() => setConfirmDelete(true)}>Plan löschen</button>}
        </div>
      </Card>
    </div>
  </>;
}
