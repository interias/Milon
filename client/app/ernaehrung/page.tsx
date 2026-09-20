"use client";

import { useEffect, useState } from "react";
import { api, type NutritionSummary, type ProteinPoint, type KcalPoint } from "@/lib/api";
import { Card, PageTitle } from "@/components/ui";
import { EnergyBalance } from "@/components/EnergyBalance";
import { RunTrendChart } from "@/components/RunTrendChart";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
import { de, de0, dm } from "@/lib/format";

export default function Ernaehrung() {
  const [summary, setSummary] = useState<NutritionSummary | null>(null);
  const [protein, setProtein] = useState<ProteinPoint[] | null>(null);
  const [kcal, setKcal] = useState<KcalPoint[] | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [rawProtein, setRawProtein] = useState(false);
  const [rawKcal, setRawKcal] = useState(false);
  const [details, setDetails] = useState(false);
  useEffect(() => {
    let active = true;
    const failed = (key: string) => { if (active) setErrors((values) => [...values, key]); };
    api.nutritionSummary().then((value) => { if (active) setSummary(value); }).catch(() => failed("summary"));
    api.nutritionProtein(60).then((value) => { if (active) setProtein(value); }).catch(() => failed("protein"));
    api.nutritionKcal(60).then((value) => { if (active) setKcal(value); }).catch(() => failed("kcal"));
    return () => { active = false; };
  }, []);
  const state = (key: string) => errors.includes(key) ? "Daten konnten nicht geladen werden." : "Wird geladen …";
  const target = summary?.protein_target;
  return <>
    <PageTitle title="Ernährung" sub="Protein & geschätzte Energiebilanz" />
    <div className="grid items-start gap-4 xl:grid-cols-2">
      <Card>
        <h2 className="text-sm font-semibold">Protein · 7-Tage-Mittel</h2>
        {summary ? <>
          <p className="mt-3 font-display text-3xl font-extrabold">{de0(summary.protein_avg7)} <span className="text-sm font-normal text-muted">g/Tag</span></p>
          <p className="mt-2 text-sm">{target != null ? `Referenzziel ${de0(target)} g/Tag · ${de(summary.protein_per_kg, 1)} g/kg` : "Kein Referenzziel ohne Gewicht verfügbar"}</p>
          {summary.last_day ? <p className="mt-2 text-xs text-muted">{dm(summary.window_start ?? summary.last_day)}–{dm(summary.last_day)} · {summary.protein_days_7} erfasste Proteintage im 7-Tage-Fenster</p> : <p className="mt-2 text-xs text-muted">Noch keine Ernährungsdaten aus FDDB.</p>}
          <p className="mt-2 text-xs text-muted">Erfasste Tage können unvollständig sein.</p>
        </> : <p className="mt-3 text-xs text-muted" role="status">{state("summary")}</p>}
        <button type="button" onClick={() => setDetails(true)} className="mt-4 rounded border border-line px-3 py-2 text-sm">Makros & Erfassungsdetails</button>
      </Card>
      <EnergyBalance className="min-w-0" />
    </div>
    <div className="mt-4 grid items-start gap-4 xl:grid-cols-2">
      <Card className="min-w-0">
        <h2 className="text-sm font-semibold">Protein · Verlauf</h2>
        {protein ? <RunTrendChart label="Protein · 7-Tage-Mittel" unit="g" showPoints={false} points={protein.map((point) => ({ date: point.date, value: point.avg7, detail: `${point.days7} erfasste Tage im 7-Tage-Fenster` }))} observations={rawProtein ? protein.map((point) => ({ date: point.date, value: point.protein, detail: "Erfasste Tagesmenge" })) : []} /> : <p className="mt-4 text-xs text-muted" role="status">{state("protein")}</p>}
        <div className="mt-2 flex flex-wrap justify-between gap-2 text-xs text-muted"><span>Bis zu 60 Tage · 7-Tage-Mittel</span><label className="flex items-center gap-2"><input type="checkbox" checked={rawProtein} onChange={(event) => setRawProtein(event.target.checked)} />Tageswerte</label></div>
      </Card>
      <Card className="min-w-0">
        <h2 className="text-sm font-semibold">Kalorien · Verlauf</h2>
        {summary && <p className="mt-2 text-xs text-muted">Ø {de0(summary.kcal_avg7)} kcal/Tag · {summary.kcal_days_7} erfasste Kalorientage im 7-Tage-Fenster{summary.last_day ? ` · Stand ${dm(summary.last_day)}` : ""}</p>}
        {kcal ? <RunTrendChart label="Kalorien · 7-Tage-Mittel" unit="kcal" showPoints={false} points={kcal.map((point) => ({ date: point.date, value: point.avg7, detail: `${point.days7} erfasste Tage im 7-Tage-Fenster` }))} observations={rawKcal ? kcal.map((point) => ({ date: point.date, value: point.kcal, detail: "Erfasste Tagesmenge" })) : []} /> : <p className="mt-4 text-xs text-muted" role="status">{state("kcal")}</p>}
        <div className="mt-2 flex flex-wrap justify-between gap-2 text-xs text-muted"><span>Bis zu 60 Tage · 7-Tage-Mittel</span><label className="flex items-center gap-2"><input type="checkbox" checked={rawKcal} onChange={(event) => setRawKcal(event.target.checked)} />Tageswerte</label></div>
      </Card>
    </div>
    {details && <RunAnalysisDialog title="Makros & Erfassungsdetails" onClose={() => setDetails(false)}>
      {summary?.last_day ? <div className="space-y-4 text-sm">
        <p className="text-xs text-muted">{dm(summary.window_start ?? summary.last_day)}–{dm(summary.last_day)} · {summary.recorded_days_7} Tage mit Ernährungseinträgen im 7-Tage-Fenster. Fehlende Tage zählen nicht als null oder als Zielverfehlung.</p>
        <p>Protein zuletzt: <strong>{de0(summary.protein_today)} g</strong> · {dm(summary.last_day)}</p>
        <p>Referenzziel erreicht: <strong>{summary.on_target_days_7 == null ? "nicht berechenbar" : `${summary.on_target_days_7} von ${summary.protein_days_7} erfassten Proteintagen`}</strong></p>
        <section className="border-t border-line pt-4"><h3 className="font-semibold">Makroverteilung · erfasste Tagesmittel</h3>
          {summary.macro_g && summary.macro_split ? <dl className="mt-3 space-y-2">{([["protein", "Protein"], ["carb", "Kohlenhydrate"], ["fat", "Fett"]] as const).map(([key, label]) => <div key={key} className="flex flex-wrap justify-between gap-2"><dt>{label}</dt><dd>{de0(summary.macro_g![key])} g · {de0(summary.macro_split![key])} %</dd></div>)}</dl> : <p className="mt-2 text-xs text-muted">Noch keine vollständige Makroverteilung verfügbar.</p>}
          <p className="mt-3 text-xs text-muted">Anteile an den aus Makros berechneten Kalorien. Ein protokollierter Tag ist kein Nachweis einer vollständigen Erfassung.</p>
        </section>
      </div> : <p className="text-sm text-muted">{summary ? "Noch keine Ernährungsdaten." : state("summary")}</p>}
    </RunAnalysisDialog>}
  </>;
}
