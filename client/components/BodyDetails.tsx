"use client";

import { useEffect, useState } from "react";
import { api, type WeeklyWeight, type Forecast, type LeanMass, type CompositionForecast } from "@/lib/api";
import { MultiTrend } from "@/components/charts";
import { de, dm } from "@/lib/format";
const signed = (value: number | null | undefined) => value == null ? "–" : `${value > 0 ? "+" : ""}${de(value, 2)}`;
const epoch = (date: string) => Date.parse(`${date.slice(0, 10)}T12:00:00Z`);

export function BodyDetails() {
  const [weekly, setWeekly] = useState<WeeklyWeight[] | null>(null);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [composition, setComposition] = useState<CompositionForecast | null>(null);
  const [mass, setMass] = useState<LeanMass | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  useEffect(() => {
    let active = true;
    const failed = (key: string) => { if (active) setErrors((values) => [...values, key]); };
    api.bodyWeeklyWeight(12).then((v) => { if (active) setWeekly(v); }).catch(() => failed("weekly"));
    api.bodyWeightForecast().then((v) => { if (active) setForecast(v); }).catch(() => failed("forecast"));
    api.bodyCompositionForecast().then((v) => { if (active) setComposition(v); }).catch(() => failed("composition"));
    api.bodyLeanMass(180).then((v) => { if (active) setMass(v); }).catch(() => failed("mass"));
    return () => { active = false; };
  }, []);
  const state = (key: string, loaded: boolean) => errors.includes(key) ? "Daten konnten nicht geladen werden." : loaded ? "Noch nicht genügend Daten." : "Wird geladen …";
  const lastMass = mass?.trend?.at(-1);
  return <div className="space-y-6 text-sm">
    <section>
      <h3 className="font-semibold">Wochenmittel · Gewicht</h3>
      <p className="mt-1 text-xs text-muted">Wochenende ist Sonntag. Veränderung nur gegenüber einer direkt angrenzenden Kalenderwoche.</p>
      {weekly?.length ? <table className="mt-3 w-full text-left tabular-nums"><thead><tr className="border-b border-line text-xs text-muted"><th className="py-2">Woche bis</th><th>Gewicht</th><th className="text-right">Änderung</th></tr></thead><tbody>{[...weekly].reverse().map((w, i, rows) => {
        const previous = rows[i + 1];
        const adjacent = previous && epoch(w.week) - epoch(previous.week) === 7 * 86400000;
        return <tr key={w.week} className="border-b border-line"><td className="py-2">{dm(w.week)}</td><td>{de(w.weight, 2)} kg</td><td className="text-right text-muted">{adjacent ? `${signed(w.weight - previous.weight)} kg` : "–"}</td></tr>;
      })}</tbody></table> : <p className="mt-2 text-xs text-muted">{state("weekly", weekly != null)}</p>}
    </section>
    <section className="border-t border-line pt-4">
      <h3 className="font-semibold">Fettmasse & fettfreie Masse · Schätzwerte</h3>
      <p className="mt-1 text-xs text-muted">Aus geglättetem Gewicht und Waagen-Körperfett abgeleitet. Fettfreie Masse umfasst auch Wasser, Knochen und Organe; sie ist keine Messung der Muskelmasse.</p>
      {mass?.trend?.length ? <>
        <div className="mt-4"><MultiTrend labels={mass.trend.map((p) => dm(p.date))} unit="kg" height={220} series={[
          { values: mass.trend.map((p) => p.fat), label: "Fettmasse (geschätzt)", color: "#d9a441" },
          { values: mass.trend.map((p) => p.ffm), label: "Fettfreie Masse (geschätzt)", color: "var(--color-accent)" },
        ]} /></div>
        <p className="mt-3 text-xs text-muted">{lastMass ? `Stand ${dm(lastMass.date)} · ` : ""}Fettfreie Masse: {de(mass.summary.ffm, 1)} kg · Fettmasse: {de(mass.summary.fat, 1)} kg</p>
        <p className="mt-1 text-xs text-muted">Änderung im separaten {mass.summary.days}-Tage-Vergleich: fettfreie Masse {signed(mass.summary.ffm_delta)} kg · Fettmasse {signed(mass.summary.fat_delta)} kg</p>
        <p className="mt-2 text-xs text-muted">Das bestehende Modell interpoliert Messlücken. Ein ruhiger Verlauf ist deshalb kein Nachweis für Muskelerhalt oder vollständige Messabdeckung.</p>
      </> : <p className="mt-2 text-xs text-muted">{state("mass", mass != null)}</p>}
    </section>
    <section className="border-t border-line pt-4">
      <h3 className="font-semibold">Gewicht · Fortschreibung um 30 Tage</h3>
      {forecast?.current != null ? <>
        <div className="mt-3 grid grid-cols-3 gap-3 tabular-nums">
          <div><p className="text-xs text-muted">{forecast.from_date ? `Stand ${dm(forecast.from_date)}` : "Ausgangswert"}</p><p className="mt-1 font-semibold">{de(forecast.current, 1)} kg</p></div>
          <div><p className="text-xs text-muted">+7 Tage</p><p className="mt-1 font-semibold">{de(forecast.per_week == null ? null : forecast.current + forecast.per_week, 1)} kg</p></div>
          <div><p className="text-xs text-muted">+{forecast.horizon_days ?? 30} Tage</p><p className="mt-1 font-semibold">{de(forecast.projected, 1)} kg</p></div>
        </div>
        <p className="mt-3 text-xs text-muted">Lineare Fortsetzung des bisherigen geglätteten Gewichtsverlaufs, kein Ziel und keine sichere Vorhersage. Auch dieses Modell interpoliert Messlücken.</p>
      </> : <p className="mt-2 text-xs text-muted">{state("forecast", forecast != null)}</p>}
    </section>
    <section className="border-t border-line pt-4">
      <h3 className="font-semibold">Körperzusammensetzung · Rechenszenarien</h3>
      {composition?.scenarios?.length ? <>
        <p className="mt-1 text-xs text-muted">{composition.from_date ? `Ausgangspunkt ${dm(composition.from_date)} · ` : ""}+{composition.horizon_days} Tage. Gleichrangige Annahmen, keine Wahrscheinlichkeiten und kein Unsicherheitsintervall.</p>
        <div className="mt-3 space-y-3">{composition.scenarios.map((s) => <div key={s.key} className="rounded border border-line p-3">
          <p className="font-semibold">{s.label}</p>
          <p className="mt-1 text-xs text-muted">Angenommener Anteil der Gewichtsänderung als fettfreie Masse: {de(s.p * 100, 0)} %</p>
          <p className="mt-2">{de(s.bf_pct, 1)} % Körperfett · {de(s.weight, 1)} kg Gewicht</p>
          <p className="mt-1 text-xs text-muted">Fettmasse {signed(s.fat_delta)} kg · fettfreie Masse {signed(s.ffm_delta)} kg</p>
          {s.note && <p className="mt-1 text-xs text-muted">{s.note}</p>}
        </div>)}</div>
        <p className="mt-3 text-xs text-muted">{composition.note} Die 15%-Annahme wurde nicht anhand deiner tatsächlichen Proteinzufuhr oder deines Trainings validiert.</p>
        {forecast?.from_date && composition.from_date && forecast.from_date !== composition.from_date && <p className="mt-2 text-xs text-muted">Gewichtsfortschreibung und Zusammensetzung verwenden unterschiedliche Ausgangstage. Ihre Endwerte sind nicht direkt vergleichbar.</p>}
      </> : <p className="mt-2 text-xs text-muted">{state("composition", composition != null)}</p>}
    </section>
  </div>;
}
