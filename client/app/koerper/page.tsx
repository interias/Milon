"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type BodySummary, type WeightPoint, type BodyFatPoint } from "@/lib/api";
import { Card, PageTitle } from "@/components/ui";
import { RunTrendChart } from "@/components/RunTrendChart";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
import { BodyDetails } from "@/components/BodyDetails";
import { EnergyBalance } from "@/components/EnergyBalance";
import { de, dm } from "@/lib/format";

export default function Koerper() {
  const [summary, setSummary] = useState<BodySummary | null>(null);
  const [weight, setWeight] = useState<WeightPoint[] | null>(null);
  const [fat, setFat] = useState<BodyFatPoint[] | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [rawWeight, setRawWeight] = useState(false);
  const [rawFat, setRawFat] = useState(false);
  const [details, setDetails] = useState(false);
  useEffect(() => {
    let active = true;
    const failed = (key: string) => { if (active) setErrors((previous) => [...previous, key]); };
    api.bodySummary().then((value) => { if (active) setSummary(value); }).catch(() => failed("summary"));
    api.bodyWeight(180).then((value) => { if (active) setWeight(value); }).catch(() => failed("weight"));
    api.bodyFat(180).then((value) => { if (active) setFat(value); }).catch(() => failed("fat"));
    return () => { active = false; };
  }, []);
  const lastFat = fat?.filter((p) => p.pct != null).at(-1);
  const delta = summary?.weight_delta7;
  const state = (key: string) => errors.includes(key) ? "Daten konnten nicht geladen werden. Bitte Seite neu laden." : "Wird geladen …";
  return <>
    <PageTitle title="Körper" sub="Gewicht & Körperzusammensetzung" />
    <div className="grid items-start gap-4 xl:grid-cols-2">
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
      <Card className="min-w-0">
        <h2 className="text-sm font-semibold">Körperfett-Schätzung</h2>
        <p className="mt-1 text-xs text-muted">Bioimpedanz-Waage · 7-Tage-Mittel</p>
        {fat ? <>
          <p className="mt-3 font-display text-3xl font-extrabold">{de(lastFat?.avg7, 1)} <span className="text-sm font-normal text-muted">%</span></p>
          <p className="mt-2 text-xs text-muted">{lastFat ? `Letzter Waagenwert: ${de(lastFat.pct, 1)} % · ${dm(lastFat.date)}` : "Noch keine Körperfettwerte"}</p>
          <p className="mt-2 text-xs text-muted">Wasserhaushalt und Messbedingungen beeinflussen die Schätzung.</p>
          <RunTrendChart label="Körperfett-Schätzung · 7-Tage-Mittel" unit="%" showPoints={false}
            points={fat.map((p) => ({ date: p.date, value: p.avg7, detail: "Geglättete BIA-Schätzung" }))}
            observations={rawFat ? fat.map((p) => ({ date: p.date, value: p.pct, detail: "Waagen-Schätzwert" })) : []} />
        </> : <p role="status" className="mt-3 text-xs text-muted">{state("fat")}</p>}
        <div className="mt-2 flex flex-wrap justify-between gap-3 text-xs text-muted"><span>Bis zu 180 Tage</span><label className="flex items-center gap-2"><input type="checkbox" checked={rawFat} onChange={(e) => setRawFat(e.target.checked)} />Rohwerte</label></div>
      </Card>
    </div>
    <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs">
      <button className="py-2 text-accent underline underline-offset-4" onClick={() => setDetails(true)}>Weitere Körperanalysen</button>
      <Link className="py-2 text-muted underline underline-offset-4" href="/fortschritt">Foto-Fortschritt ansehen</Link>
    </div>
    <EnergyBalance compact />
    {details && <RunAnalysisDialog title="Weitere Körperanalysen" onClose={() => setDetails(false)}><BodyDetails /></RunAnalysisDialog>}
  </>;
}
