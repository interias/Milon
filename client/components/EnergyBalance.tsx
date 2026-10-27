"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Tdee, type TdeePoint } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { MultiTrend } from "@/components/charts";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
import { de0, dm } from "@/lib/format";

export function EnergyBalance({ compact = false, className = "mt-4" }: { compact?: boolean; className?: string }) {
  const [data, setData] = useState<Tdee | null>(null);
  const [trend, setTrend] = useState<TdeePoint[] | null>(null);
  const [error, setError] = useState(false);
  const [trendError, setTrendError] = useState(false);
  const [details, setDetails] = useState(false);
  useEffect(() => {
    let active = true;
    api.bodyTdee().then((value) => { if (active) setData(value); }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!details) return;
    let active = true;
    setTrendError(false);
    api.bodyTdeeTrend(14, 180).then((value) => { if (active) setTrend(value); }).catch(() => { if (active) setTrendError(true); });
    return () => { active = false; };
  }, [details]);
  const balance = data?.deficit_per_day;
  const parts = data?.parts;
  return <Card className={className}>
    <div id={compact ? undefined : "energiebilanz"} className="scroll-mt-20">
      <CardTitle title="Energiebilanz" sub={compact ? undefined : "Lernendes Modell aus Waage, protokollierter Ernährung und gemessener Bewegung"} />
      {data?.tdee != null ? <>
        <div className={`flex flex-wrap items-baseline ${compact ? "gap-x-5 gap-y-2 text-sm" : "gap-x-8 gap-y-3"}`}>
          <p><span className="text-xs text-muted">Verbrauch (typischer Tag) </span><strong>{de0(data.tdee)} kcal/Tag</strong>
            {data.tdee_sd != null && <span className="text-xs text-muted"> ± {de0(data.tdee_sd)}</span>}</p>
          {!compact && <p><span className="text-xs text-muted">Erfasste Zufuhr Ø </span><strong>{de0(data.avg_intake)} kcal/Tag</strong></p>}
          {balance != null && <p><span className="text-xs text-muted">{balance >= 0 ? "Geschätztes Defizit" : "Geschätzter Überschuss"} </span><strong>{de0(Math.abs(balance))} kcal/Tag</strong></p>}
        </div>
        {!compact && parts && <Breakdown parts={parts} total={data.tdee} />}
        {data.tdee_today != null && <div className={`mt-3 border-t border-line pt-3 ${compact ? "text-sm" : ""}`}>
          <p><span className="text-xs text-muted">Verbrauch heute </span><strong>{de0(data.tdee_today)} kcal</strong>
            <span className="text-xs text-muted"> = Grundverbrauch + Verdauung {de0(data.tdee_base)} + Bewegung heute {de0(data.active_kcal_today)}</span></p>
          {!compact && data.intake_today != null && <p className="mt-1"><span className="text-xs text-muted">Bilanz heute bisher </span><strong>{de0(Math.abs(data.tdee_today - data.intake_today))} kcal {data.tdee_today >= data.intake_today ? "Defizit" : "Überschuss"}</strong><span className="text-xs text-muted"> (gegessen {de0(data.intake_today)} kcal)</span></p>}
        </div>}
        <p className="mt-2 text-xs text-muted">{data.from_date ? `Stand ${dm(data.from_date)} · ` : ""}{data.estimate_days != null ? `gelernt aus ${de0(data.estimate_days)} Wiegetagen${data.provisional ? " · vorläufig" : ""}` : "Modellschätzung, keine direkte Messung."}</p>
      </> : <p className="text-xs text-muted" role="status">{error ? "Energiebilanz konnte nicht geladen werden." : data ? data.reason ?? "Noch keine Schätzung verfügbar." : "Energiebilanz wird geladen …"}</p>}
      {compact ? <Link className="mt-3 inline-block text-xs font-semibold text-accent" href="/ernaehrung#energiebilanz">Energiebilanz unter Ernährung ansehen →</Link> : <button type="button" onClick={() => setDetails(true)} className="mt-4 rounded border border-line px-3 py-2 text-sm">Energieverlauf & Details</button>}
      {details && <RunAnalysisDialog title="Energieverlauf & Details" onClose={() => setDetails(false)}>
        <p className="mt-3 text-xs text-muted">Defizit = geschätzter Verbrauch minus erfasste Zufuhr. Änderungen werden ohne festgelegtes Körperziel neutral dargestellt.</p>
        <p className="mt-2 text-xs text-muted">So rechnet das Modell: Jeden Tag schätzt es dein „wahres“ Gewicht ohne Wasserschwankung und deinen Grundverbrauch. Die Waage korrigiert beides, je nachdem wie gut Essen, Bewegung und Gewicht zusammenpassen. 1 kg Gewichtsänderung = 7.700 kcal, Verdauung = 10 % der Zufuhr, Bewegung = Milons aktive kcal. Im Rückblick sagte es dein Gewicht 4 Wochen voraus auf ~0,5 kg genau (altes Verfahren ~0,8 kg). Ein systematischer Fehler beim Eintragen des Essens lässt sich vom Verbrauch nicht trennen.</p>
        <div className="mt-5"><CardTitle title="Verbrauch & Zufuhr · Verlauf" sub="Modellstand je Tag · bis zu 180 Tage" />
          {trend?.length ? <MultiTrend labels={trend.map((p) => dm(p.date))} unit="kcal" height={240} format={de0} series={[
            { values: trend.map((p) => p.intake_avg), label: "Zufuhr (14-Tage-Mittel)", color: "var(--color-muted)" },
            { values: trend.map((p) => p.tdee_avg), label: "Verbrauch (typischer Tag)", color: "var(--color-accent)" },
          ]} /> : <p className="text-xs text-muted" role="status">{trendError ? "Verlauf konnte nicht geladen werden." : trend ? "Noch nicht genügend Daten für einen Verlauf." : "Verlauf wird geladen …"}</p>}
        </div>
        <p className="mt-3 text-xs text-muted">Der Verbrauch an einem Tag kennt nur Daten bis zu diesem Tag. Typischer Tag = Grundverbrauch + Verdauung und Bewegung im Mittel der letzten 14 Tage.</p>
      </RunAnalysisDialog>}
    </div>
  </Card>;
}

const PARTS = [
  { key: "resting", label: "Ruheumsatz", color: "#8a9a99", note: "Formel nach Cunningham aus deiner Magermasse" },
  { key: "unmeasured", label: "Unerfasste Alltagsbewegung", color: "#5cb8af", note: "Stehen, Hausarbeit, Nachbrenneffekt … – gelernt" },
  { key: "tef", label: "Verdauung", color: "#ab7f00", note: "10 % der Zufuhr" },
  { key: "active", label: "Gemessene Bewegung", color: "#0a6e66", note: "Milons aktive kcal, Ø 14 Tage" },
] as const;

function Breakdown({ parts, total }: { parts: NonNullable<Tdee["parts"]>; total: number }) {
  // Ohne Körperfett (oder wenn die Formel über dem Gelernten liegt) bleibt der Grundverbrauch ein Block.
  const split = parts.resting != null && parts.unmeasured != null && parts.unmeasured > 0;
  const rows = split ? PARTS.map((p) => ({ ...p, value: parts[p.key] as number }))
    : [{ key: "base", label: "Grundverbrauch", color: "#8a9a99", note: "Ruheumsatz + Unerfasstes – gelernt", value: parts.base },
       ...PARTS.slice(2).map((p) => ({ ...p, value: parts[p.key] as number }))];
  return <div className="mt-4">
    <div className="flex h-3 w-full overflow-hidden rounded" role="img" aria-label="Zerlegung des Verbrauchs">
      {rows.map((r) => <div key={r.key} style={{ width: `${Math.max(0, r.value) / total * 100}%`, background: r.color }} title={`${r.label}: ${de0(r.value)} kcal`} />)}
    </div>
    <ul className="mt-3 grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
      {rows.map((r) => <li key={r.key} className="flex items-baseline gap-2">
        <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: r.color }} />
        <span className="min-w-0"><span>{r.label}</span> <strong>{de0(r.value)}</strong>
          <span className="block text-xs text-muted">{r.note}</span></span>
      </li>)}
    </ul>
  </div>;
}
