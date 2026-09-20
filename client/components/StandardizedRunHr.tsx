"use client";

import { useEffect, useState } from "react";
import { api, type StandardizedHr, type StandardizedHrPoint } from "@/lib/api";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
import { RunTrendChart } from "@/components/RunTrendChart";
import { Card } from "@/components/ui";
import { de, dm, pace } from "@/lib/format";

const monthLabel = (month: string) => new Date(`${month.length > 7 ? month : month + "-01"}T12:00:00`).toLocaleDateString("de-DE", { day: "2-digit", month: "short", year: "2-digit" });
const usable = (p: StandardizedHrPoint) => (p.status === "ok" || p.status === "provisional" || p.status === "sensitive") && p.hr != null;
const STATUS = { ok: "auswertbar", sensitive: "empfindlich gegenüber einzelnen Läufen", provisional: "vorläufig", insufficient: "zu wenig Daten", unstable: "instabil" };
export function StandardizedRunHr() {
  const [data, setData] = useState<StandardizedHr | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [details, setDetails] = useState(false);

  async function refresh() {
    setLoading(true);
    setError(null);
    try { setData(await api.runStandardizedHr()); }
    catch (e) { setData(null); setError(String(e)); }
    finally { setLoading(false); }
  }
  useEffect(() => {
    const listener = () => { void refresh(); };
    void refresh();
    window.addEventListener("run-analysis-updated", listener);
    return () => window.removeEventListener("run-analysis-updated", listener);
  }, []);

  const series = data?.pace_series.find((s) => s.pace_seconds === selected)
    ?? data?.pace_series.find((s) => s.pace_seconds === 360) ?? data?.pace_series[0];
  const latest = series?.points.at(-1);
  const comparison = series?.comparison;
  return <Card className="mt-6">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-sm font-semibold">Puls bei gleicher Pace</h2>
      <span className="rounded-full border border-line px-2 py-0.5 text-[10px] text-muted">Experimentell</span>
    </div>
    <p className="mt-1 text-xs text-muted">Standardisiert auf Laufminute {data?.reference_minute ?? 30} · Rollierende 8 Wochen aus gleichmäßigen Laufabschnitten</p>
    {loading && <p className="mt-4 text-sm text-muted" role="status">Laufanalyse wird berechnet …</p>}
    {error && <div className="mt-4 text-sm" role="alert"><p>Die Laufanalyse konnte nicht geladen werden.</p><p className="break-words text-xs text-muted">{error}</p><button onClick={() => void refresh()} className="mt-2 underline">Erneut versuchen</button></div>}
    {!loading && data && <>
      {!series ? <p className="mt-4 text-sm text-muted">{data.empty_reason || "Noch keine Pace mit ausreichend vergleichbaren Laufdaten verfügbar."}</p> : <>
        <div className="mt-4 flex flex-wrap gap-2" aria-label="Referenzpace">
          {data.pace_series.map((s) => <button key={s.pace_seconds} aria-pressed={series.pace_seconds === s.pace_seconds} onClick={() => setSelected(s.pace_seconds)} className={`rounded border px-3 py-2 text-sm ${series.pace_seconds === s.pace_seconds ? "border-accent bg-accent/10 text-accent" : "border-line text-muted"}`}>{pace(s.pace_seconds / 60)} /km</button>)}
        </div>
        {latest && usable(latest) && <div className="mt-4">
          <p className="font-display text-3xl font-extrabold">{de(latest.hr, 1)} <span className="text-sm font-normal text-muted">bpm</span></p>
          <p className="text-xs text-muted">Fenster bis: {monthLabel(latest.month)} · {STATUS[latest.status]}</p>
        </div>}
        {latest && !usable(latest) && <p className="mt-4 text-sm text-muted">Aktuell keine ausreichend gestützte Schätzung: {latest.reasons.join(" · ")}</p>}
        <p className="mt-2 text-xs text-muted">Niedriger = bessere Effizienz bei gleicher Pace</p>
        <RunTrendChart key={series.pace_seconds} label="Puls bei gleicher Pace" unit="bpm" points={series.points.map((p) => ({ ...p, date: p.month, value: usable(p) ? p.hr : null, low: p.ci_low, high: p.ci_high, detail: `${p.runs} Läufe · ${p.local_runs} nahe Referenz` }))} />
        <div className="mt-2 flex items-center justify-between gap-3 text-xs text-muted"><span>Band: 95%-Unsicherheit</span><button className="underline underline-offset-4" onClick={() => setDetails(true)}>Details</button></div>
        {details && <RunAnalysisDialog title="Puls bei gleicher Pace · Details" onClose={() => setDetails(false)}>
        <p className="text-[11px] text-muted">Band: nominales 95%-Intervall aus Lauf-Bootstrap. Überlappende Fenster sind keine unabhängigen Messungen. Lücken: nicht ausreichend auswertbar.</p>
        {comparison && <p className="mt-3 text-xs">{monthLabel(comparison.from_month)} → {monthLabel(comparison.to_month)}: {comparison.delta > 0 ? "+" : ""}{de(comparison.delta, 1)} bpm (95%-Intervall {de(comparison.ci_low, 1)} bis {de(comparison.ci_high, 1)}). {comparison.verdict === "unclear" ? "Unterschied unklar." : comparison.verdict === "lower" ? "Standardisierter Puls niedriger." : "Standardisierter Puls höher."}</p>}
        <section className="mt-4 text-xs"><h3 className="font-semibold">Datenabdeckung & Details</h3>
          <p className="my-2 text-muted">„Nahe Referenz“ zählt Läufe mit passenden Abschnitten nahe Pace und Laufminute.</p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead><tr className="border-b border-line"><th className="p-2">Fenster bis</th><th className="p-2">Puls / 95%-Intervall</th><th className="p-2">Läufe / nahe Referenz</th><th className="p-2">Einordnung</th></tr></thead>
              <tbody>{series.points.map((p) => <tr key={p.month} className="border-b border-line align-top">
                <td className="whitespace-nowrap p-2">{monthLabel(p.month)}</td>
                <td className="p-2">{usable(p) ? `${de(p.hr, 1)} (${de(p.ci_low, 1)}–${de(p.ci_high, 1)}) bpm` : p.exploratory_hr != null ? `${de(p.exploratory_hr, 1)} bpm · explorativ` : "—"}</td>
                <td className="p-2">{p.runs} / {p.local_runs}</td>
                <td className="min-w-40 p-2">{STATUS[p.status]}{p.reasons.length > 0 && <p className="text-muted">{p.reasons.join(" · ")}</p>}</td>
              </tr>)}</tbody>
            </table>
          </div>
        </section>
        <p className="mt-4 text-xs text-muted">{data.caveat}</p>
        </RunAnalysisDialog>}
      </>}
    </>}
  </Card>;
}
