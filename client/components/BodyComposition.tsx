"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type BodyComposition as Composition } from "@/lib/api";
import { Card } from "@/components/ui";
import { RunTrendChart } from "@/components/RunTrendChart";
import { de, dm } from "@/lib/format";

export function BodyComposition({ revision = 0 }: { revision?: number }) {
  const [data, setData] = useState<Composition | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    api.bodyComposition().then((value) => { if (active) setData(value); }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [revision]);
  const c = data?.current;
  return <Card className="mt-4 min-w-0">
    <h2 className="text-sm font-semibold">Körperzusammensetzung</h2>
    <p className="mt-1 text-xs text-muted">Aus dem Taillenumfang · als Spanne, keine Messung</p>
    {c ? <>
      <div className="mt-3 flex flex-wrap items-baseline gap-x-8 gap-y-3">
        <div><p className="text-xs text-muted">Körperfett</p>
          <p className="font-display text-3xl font-extrabold">{de(c.bf_low, 0)}–{de(c.bf_high, 0)} <span className="text-sm font-normal text-muted">%</span></p></div>
        <div><p className="text-xs text-muted">Fettfreie Masse</p>
          <p className="text-lg font-semibold">{c.ffm_low != null ? `${de(c.ffm_low, 1)}–${de(c.ffm_high, 1)} kg` : "–"}</p></div>
        <div><p className="text-xs text-muted">Taille / Größe</p>
          <p className="text-lg font-semibold">{de(c.whtr, 3)}
            {data?.whtr_delta != null && data.first && data.first.date !== c.date && <span className="ml-2 text-xs font-normal text-muted">{data.whtr_delta > 0 ? "+" : ""}{de(data.whtr_delta, 3)} seit {dm(data.first.date)}</span>}</p></div>
      </div>
      <p className="mt-2 text-xs text-muted">Stand {dm(c.date)} · Taille {de(c.waist, 1)} cm{c.weight != null ? ` · Gewicht ${de(c.weight, 1)} kg · Fettmasse ${de(c.fat_low, 1)}–${de(c.fat_high, 1)} kg` : ""}</p>
      {data!.series.length > 1 && <RunTrendChart label="Körperfett · Spanne je Taillenmessung" unit="%" intervalLabel="Spanne Fotobewertung–Taillenformel" maxGapDays={Infinity}
        points={data!.series.map((p) => ({ date: p.date, value: p.bf_mid, low: p.bf_low, high: p.bf_high, detail: `Taille ${de(p.waist, 1)} cm · Taille/Größe ${de(p.whtr, 3)}` }))} />}
      <p className="mt-3 text-xs text-muted">{data!.caveat} Belastbarer als das Niveau ist der Verlauf der Taille.</p>
    </> : <p role="status" className="mt-3 text-xs text-muted">{error ? "Daten konnten nicht geladen werden." : data ? <>{data.reason} {data.reason?.includes("Größe") && <Link className="text-accent underline" href="/einstellungen">Einstellungen</Link>}</> : "Wird geladen …"}</p>}
  </Card>;
}
