"use client";

import { useEffect, useRef, useState } from "react";
import { api, type RunningFitnessData } from "@/lib/api";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
import { RunTrendChart } from "@/components/RunTrendChart";
import { Card } from "@/components/ui";
import { de, dm, pace } from "@/lib/format";

type Metric = "vo2" | "hr";
export function RunningFitness() {
  const [data, setData] = useState<RunningFitnessData | null>(null);
  const [metric, setMetric] = useState<Metric>("vo2");
  const [raw, setRaw] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [details, setDetails] = useState(false);
  const request = useRef(0);
  async function refresh() {
    const id = ++request.current;
    setLoading(true); setError(null);
    try { const response = await api.runFitness(); if (id === request.current) setData(response); }
    catch (e) { if (id === request.current) { setData(null); setError(String(e)); } }
    finally { if (id === request.current) setLoading(false); }
  }
  useEffect(() => {
    void refresh();
    const listener = () => { void refresh(); };
    window.addEventListener("run-analysis-updated", listener);
    return () => { ++request.current; window.removeEventListener("run-analysis-updated", listener); };
  }, []);
  const current = data?.points.at(-1);
  const latest = data?.points.filter((p) => (metric === "vo2" ? p.vo2_eq : p.hr) != null).at(-1);
  const value = latest && (metric === "vo2" ? latest.vo2_eq : latest.hr);
  const calibration = data?.calibration;
  return <Card className="mt-6">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-sm font-semibold">Eigener Lauf-Fitness-Trend</h2><span className="rounded-full border border-line px-2 py-0.5 text-[10px] text-muted">Experimentell</span></div>
    <p className="mt-1 text-xs text-muted">{data?.window_days ?? 56} Tage gemeinsam ausgewertet · Referenz {pace((data?.reference_pace_seconds ?? 360) / 60)} /km bei Laufminute {data?.reference_minute ?? 20}</p>
    {loading && <p className="mt-4 text-sm text-muted" role="status">Fitness-Trend wird berechnet …</p>}
    {error && <div className="mt-4 text-xs" role="alert"><p>Der Fitness-Trend konnte nicht geladen werden.</p><p className="break-words text-muted">{error}</p><button className="mt-2 underline" onClick={() => void refresh()}>Erneut versuchen</button></div>}
    {!loading && data && <>
      <div className="mt-4 flex flex-wrap gap-2">{([ ["vo2", "VO₂-Äquivalent"], ["hr", "Standardisierter Puls"] ] as const).map(([key, label]) => <button key={key} aria-pressed={metric === key} onClick={() => setMetric(key)} className={`rounded border px-3 py-2 text-sm ${metric === key ? "border-accent bg-accent/10 text-accent" : "border-line text-muted"}`}>{label}</button>)}</div>
      {latest && <div className="mt-4"><p className="font-display text-3xl font-extrabold">{de(value, 1)} <span className="text-sm font-normal text-muted">{metric === "vo2" ? "ml/kg/min" : "bpm"}</span></p><p className="mt-1 text-xs text-muted">Letzter geeigneter Wert: {dm(latest.date)} · {latest.runs} Läufe, davon {latest.local_runs} nahe Referenz</p></div>}
      <p className="mt-2 text-xs text-muted">{metric === "vo2" ? "Höher = bessere geschätzte Fitness · Vorläufige Schätzung" : "Niedriger = bessere Effizienz bei gleicher Pace"}{latest?.status === "sensitive" ? " · Unsicherer Wert" : ""}</p>
      {current && (metric === "vo2" ? current.vo2_eq : current.hr) == null && <p className="mt-2 text-xs text-muted">Aktuell keine geeignete Schätzung.{latest ? " Angezeigt wird der letzte verfügbare Wert." : ""}</p>}
      <RunTrendChart label={metric === "vo2" ? "Eigener VO₂-Trend" : "Standardisierter Puls"} unit={metric === "vo2" ? "ml/kg/min" : "bpm"}
        points={data.points.map((p) => ({ ...p, value: metric === "vo2" ? p.vo2_eq : p.hr, low: metric === "vo2" ? p.vo2_low : p.ci_low, high: metric === "vo2" ? p.vo2_high : p.ci_high, detail: `${p.runs} Läufe · ${p.local_runs} nahe Referenz` }))}
        observations={raw ? data.observations.map((p) => ({ ...p, value: metric === "vo2" ? p.vo2_eq : p.hr })) : []} />
      <div className="mt-2 flex items-center justify-between gap-3 text-xs text-muted"><span>Band: 95%-Unsicherheit{raw ? " · Einzelwerte eingeblendet" : ""}</span><button className="underline underline-offset-4" onClick={() => setDetails(true)}>Details</button></div>
      {details && <RunAnalysisDialog title="Eigener Lauf-Fitness-Trend · Details" onClose={() => setDetails(false)}>
      {metric === "vo2" && <p className="mt-2 text-xs text-muted">{calibration?.provisional ? `Vorläufige Skala · Ruhepulsannahme ${de(calibration.rest_hr, 0)} bpm, keine Ruhemessung.` : "Persönliches Modelläquivalent, keine gemessene VO₂max."} {calibration?.max_hr == null && "Eine wiederholt erreichte hohe Pulsreferenz fehlt noch; bis dahin steht der Puls-Trend zur Verfügung."}</p>}
      {latest?.status === "sensitive" && <p className="mt-2 text-xs text-muted">Der letzte Wert reagiert empfindlich auf einzelne Läufe und ist entsprechend unsicher.</p>}
      {metric === "vo2" && latest?.vo2_sensitivity_low != null && latest.vo2_sensitivity_high != null && <p className="mt-2 text-xs text-muted">Bei um ±10 bpm veränderten Pulsreferenzen: {de(latest.vo2_sensitivity_low, 1)}–{de(latest.vo2_sensitivity_high, 1)} ml/kg/min. Modell-Szenarien, kein Konfidenzintervall.</p>}
      {current && (metric === "vo2" ? current.vo2_eq : current.hr) == null && <p className="mt-3 text-xs text-muted">Für {dm(current.date)} kein geeigneter Wert. {current.reasons.join(" · ")}</p>}
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={raw} onChange={(e) => setRaw(e.target.checked)} />Einzelne Laufwerte anzeigen</label>
      {raw && <p className="mt-1 text-[11px] text-muted">Helle Punkte: geeignete Abschnitte einzelner Läufe bei deren tatsächlichem Tempo nahe der Referenz. Diese Werte sind nicht auf identische Bedingungen standardisiert.</p>}
      <p className="mt-2 text-[11px] text-muted">Linie: rollierendes Modell. Offene Punkte reagieren empfindlich auf einzelne Läufe. Band: nominale 95%-Intervalle aus Lauf-Bootstrap bei festen Pulsreferenzen; keine gesamte physiologische Unsicherheit. Überlappende Fenster sind keine unabhängigen Bestätigungen. Lücken bleiben offen.</p>
      <section className="mt-4 text-xs"><h3 className="font-semibold">Werte & Datenabdeckung</h3><div className="mt-2 overflow-x-auto"><table className="w-full text-left"><thead><tr className="border-b border-line"><th className="p-2">Datum</th><th className="p-2">Puls</th><th className="p-2">VO₂eq</th><th className="p-2">Läufe / nahe Pace</th><th className="p-2">Hinweise</th></tr></thead><tbody>{data.points.map((p) => <tr key={p.date} className="border-b border-line align-top"><td className="whitespace-nowrap p-2">{dm(p.date)}</td><td className="p-2">{de(p.hr, 1)}</td><td className="p-2">{de(p.vo2_eq, 1)}</td><td className="p-2">{p.runs} / {p.local_runs}</td><td className="min-w-40 p-2 text-muted">{p.reasons.length ? p.reasons.join(" · ") : "Ausreichend vergleichbare Abschnitte"}</td></tr>)}</tbody></table></div></section>
      <p className="mt-4 text-[11px] text-muted">{data.caveat} {metric === "vo2" && "Die hohe Pulsreferenz ist keine gemessene HFmax; Laufkosten und Herzfrequenzreserve sind Näherungen. Das VO₂-Äquivalent ist eine Umrechnung desselben Puls-Signals, keine unabhängige Bestätigung."}</p>
      {!!data.durability?.length && <section className="mt-4 text-xs"><h3 className="font-semibold">Pulsanstieg innerhalb vergleichbarer Läufe</h3><p className="mt-2 text-muted">Laufminute 15–25 gegenüber 30–40 bei ähnlichem Tempo nahe 6:00 /km. Ein zusätzlicher Hinweis auf Ermüdung und Laufbedingungen, keine weitere VO₂-Schätzung.</p><div className="mt-2 overflow-x-auto"><table className="w-full text-left"><thead><tr className="border-b border-line"><th className="p-2">Datum</th><th className="p-2">Früh / spät</th><th className="p-2">Änderung</th></tr></thead><tbody>{data.durability.slice(-5).reverse().map((p) => <tr key={p.external_id} className="border-b border-line"><td className="p-2">{dm(p.date)}</td><td className="p-2">{de(p.early_hr, 1)} / {de(p.late_hr, 1)} bpm</td><td className="p-2">{p.delta_bpm > 0 ? "+" : ""}{de(p.delta_bpm, 1)} bpm</td></tr>)}</tbody></table></div></section>}
      </RunAnalysisDialog>}
    </>}
  </Card>;
}
