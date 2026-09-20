"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Tdee, type TdeePoint } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { MultiTrend } from "@/components/charts";
import { de0, dm } from "@/lib/format";

export function EnergyBalance({ compact = false }: { compact?: boolean }) {
  const [data, setData] = useState<Tdee | null>(null);
  const [trend, setTrend] = useState<TdeePoint[] | null>(null);
  const [error, setError] = useState(false);
  const [trendError, setTrendError] = useState(false);
  useEffect(() => {
    let active = true;
    api.bodyTdee().then((value) => { if (active) setData(value); }).catch(() => { if (active) setError(true); });
    if (!compact) api.bodyTdeeTrend(14, 180).then((value) => { if (active) setTrend(value); }).catch(() => { if (active) setTrendError(true); });
    return () => { active = false; };
  }, [compact]);
  const balance = data?.deficit_per_day;
  return <Card className="mt-4">
    <div id={compact ? undefined : "energiebilanz"} className="scroll-mt-20">
      <CardTitle title="Energiebilanz" sub={compact ? undefined : "Aus Gewicht und protokollierter Ernährung geschätzt"} />
      {data?.tdee != null ? <>
        <div className={`flex flex-wrap items-baseline ${compact ? "gap-x-5 gap-y-2 text-sm" : "gap-x-8 gap-y-3"}`}>
          <p><span className="text-xs text-muted">Energieumsatz (TDEE) </span><strong>{de0(data.tdee)} kcal/Tag</strong></p>
          {!compact && <p><span className="text-xs text-muted">Erfasste Zufuhr Ø </span><strong>{de0(data.avg_intake)} kcal/Tag</strong></p>}
          {balance != null && <p><span className="text-xs text-muted">{balance >= 0 ? "Geschätztes Defizit" : "Geschätzter Überschuss"} </span><strong>{de0(Math.abs(balance))} kcal/Tag</strong></p>}
        </div>
        <p className="mt-2 text-xs text-muted">{data.from_date ? `Stand ${dm(data.from_date)} · ` : ""}Modellschätzung, keine direkte Messung.</p>
      </> : <p className="text-xs text-muted" role="status">{error ? "Energiebilanz konnte nicht geladen werden." : data ? data.reason ?? "Noch keine Schätzung verfügbar." : "Energiebilanz wird geladen …"}</p>}
      {compact ? <Link className="mt-3 inline-block text-xs font-semibold text-accent" href="/ernaehrung#energiebilanz">Energiebilanz unter Ernährung ansehen →</Link> : <>
        <p className="mt-3 text-xs text-muted">Defizit = geschätzter Umsatz minus erfasste Zufuhr. Änderungen werden ohne festgelegtes Körperziel neutral dargestellt.</p>
        <div className="mt-5"><CardTitle title="Energieumsatz & Zufuhr · Verlauf" sub="Geglättete Schätzungen · bis zu 180 Tage" />
          {trend?.length ? <MultiTrend labels={trend.map((p) => dm(p.date))} unit="kcal" height={240} format={de0} series={[
            { values: trend.map((p) => p.intake), label: "Zufuhr im Schätzfenster", color: "var(--color-muted)" },
            { values: trend.map((p) => p.tdee_avg), label: "TDEE (14-Tage-Mittel)", color: "var(--color-accent)" },
          ]} /> : <p className="text-xs text-muted" role="status">{trendError ? "Verlauf konnte nicht geladen werden." : trend ? "Noch nicht genügend Daten für einen Verlauf." : "Verlauf wird geladen …"}</p>}
        </div>
        <p className="mt-3 text-xs text-muted">Die Linien verwenden unterschiedliche Glättungsfenster. Ihr Abstand ist daher keine exakte tägliche Bilanz. Fehlende Ernährungseinträge und kurzfristige Gewichtsänderungen können die Schätzung verschieben.</p>
      </>}
    </div>
  </Card>;
}
