"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type BodySummary, type WeightPoint } from "@/lib/api";
import { Card, PageTitle } from "@/components/ui";
import { RunTrendChart } from "@/components/RunTrendChart";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
import { BodyDetails } from "@/components/BodyDetails";
import { EnergyBalance } from "@/components/EnergyBalance";
import { BodyCircumferences } from "@/components/BodyCircumferences";
import { BodyProgress } from "@/components/BodyProgress";
import { BodyComposition } from "@/components/BodyComposition";
import { de, dm } from "@/lib/format";

export default function Koerper() {
  const [summary, setSummary] = useState<BodySummary | null>(null);
  const [weight, setWeight] = useState<WeightPoint[] | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [rawWeight, setRawWeight] = useState(false);
  const [details, setDetails] = useState(false);
  const [measurementsRevision, setMeasurementsRevision] = useState(0);
  useEffect(() => {
    let active = true;
    const failed = (key: string) => { if (active) setErrors((previous) => [...previous, key]); };
    api.bodySummary().then((value) => { if (active) setSummary(value); }).catch(() => failed("summary"));
    api.bodyWeight(180).then((value) => { if (active) setWeight(value); }).catch(() => failed("weight"));
    return () => { active = false; };
  }, []);
  const delta = summary?.weight_delta7;
  const state = (key: string) => errors.includes(key) ? "Daten konnten nicht geladen werden. Bitte Seite neu laden." : "Wird geladen …";
  return <>
    <PageTitle title="Körper" sub="Körpermaße, Gewicht & Zusammensetzung" />
    <BodyProgress revision={measurementsRevision} />
    <div className="mb-5"><BodyCircumferences onChange={() => setMeasurementsRevision(value => value + 1)} /></div>
    <Card className="min-w-0">
      <h2 className="text-sm font-semibold">Gewicht</h2>
      <p className="mt-1 text-xs text-muted">7-Tage-Mittel · neutral bewertet</p>
      {summary ? <>
        <p className="mt-3 font-display text-3xl font-extrabold">{de(summary.weight_avg7, 1)} <span className="text-sm font-normal text-muted">kg</span></p>
        <p className="mt-2 text-sm">{delta == null ? "Kein Vergleich verfügbar" : `${delta > 0 ? "+" : ""}${de(delta, 2)} kg gegenüber 7 Tagen zuvor`}</p>
        <p className="mt-2 text-xs text-muted">{summary.weight_date ? `Letzte Messung: ${de(summary.weight_kg, 1)} kg · ${dm(summary.weight_date)}` : "Noch keine Gewichtsmessung"}</p>
        {summary.weight_date && <p className="mt-1 text-xs text-muted">{summary.weight_days7}/7 Messtage · Vergleichsfenster {summary.previous_weight_days7}/7</p>}
      </> : <p role="status" className="mt-3 text-xs text-muted">{state("summary")}</p>}
      {weight ? <RunTrendChart label="Gewicht · 7-Tage-Mittel" unit="kg" showPoints={false}
        points={weight.map((p) => ({ date: p.date, value: p.avg7, detail: "7-Tage-Mittel aus vorhandenen Messungen" }))}
        observations={rawWeight ? weight.map((p) => ({ date: p.date, value: p.weight, detail: "Einzelmesswert" })) : []} /> : <p role="status" className="mt-4 text-xs text-muted">{state("weight")}</p>}
      <div className="mt-2 flex flex-wrap justify-between gap-3 text-xs text-muted"><span>Bis zu 180 Tage · Lücken bleiben sichtbar</span><label className="flex items-center gap-2"><input type="checkbox" checked={rawWeight} onChange={(e) => setRawWeight(e.target.checked)} />Rohwerte</label></div>
    </Card>
    <BodyComposition revision={measurementsRevision} />
    <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs">
      <button className="py-2 text-accent underline underline-offset-4" onClick={() => setDetails(true)}>Weitere Körperanalysen</button>
      <Link className="py-2 text-muted underline underline-offset-4" href="/fortschritt">Foto-Fortschritt ansehen</Link>
    </div>
    <EnergyBalance compact />
    {details && <RunAnalysisDialog title="Weitere Körperanalysen" onClose={() => setDetails(false)}><BodyDetails /></RunAnalysisDialog>}
  </>;
}
