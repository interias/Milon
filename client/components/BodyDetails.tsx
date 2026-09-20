"use client";

import { useEffect, useState } from "react";
import { api, type WeeklyWeight, type Forecast, type LeanMass, type CompositionForecast } from "@/lib/api";
import { RunTrendChart } from "@/components/RunTrendChart";
import { de, dm } from "@/lib/format";
const signed = (value: number | null | undefined) => value == null ? "–" : `${value > 0 ? "+" : ""}${de(value, 2)}`;
const epoch = (date: string) => Date.parse(`${date.slice(0, 10)}T12:00:00Z`);

export function BodyDetails() {
  const [weekly, setWeekly] = useState<WeeklyWeight[] | null>(null);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [composition, setComposition] = useState<CompositionForecast | null>(null);
  const [mass, setMass] = useState<LeanMass | null>(null);
  const [massMetric, setMassMetric] = useState<"ffm" | "fat">("ffm");
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
  const massLabel = massMetric === "ffm" ? "Fettfreie Masse" : "Fettmasse";
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
      <p className="mt-1 text-xs text-muted">Gewicht und Waagen-Körperfett aus denselben sieben Kalendertagen, mit mindestens drei gemeinsamen Messtagen. Fettfreie Masse umfasst auch Wasser, Knochen und Organe; sie ist keine Messung der Muskelmasse.</p>
      {mass?.trend?.length ? <>
        <div className="mt-3 flex flex-wrap gap-2" aria-label="Darstellung der Körperzusammensetzung">
          {(["ffm", "fat"] as const).map((metric) => <button key={metric} type="button" aria-pressed={massMetric === metric} onClick={() => setMassMetric(metric)} className={`rounded border px-3 py-1.5 text-xs ${massMetric === metric ? "border-accent bg-accent/5 text-accent" : "border-line text-muted"}`}>{metric === "ffm" ? "Fettfreie Masse" : "Fettmasse"}</button>)}
        </div>
        <RunTrendChart label={`${massLabel} (geschätzt)`} unit="kg" showPoints={false} points={mass.trend.map((p) => ({ date: p.date, value: p[massMetric], detail: `${p.paired_days} gemeinsame Messtage im 7-Tage-Fenster` }))} />
        <p className="mt-3 text-xs text-muted">{mass.summary.to_date ? `Stand ${dm(mass.summary.to_date)} · ` : ""}Fettfreie Masse: {de(mass.summary.ffm, 1)} kg · Fettmasse: {de(mass.summary.fat, 1)} kg</p>
        {mass.summary.from_date && mass.summary.to_date && <p className="mt-1 text-xs text-muted">Änderung {dm(mass.summary.from_date)}–{dm(mass.summary.to_date)} ({mass.summary.days} Kalendertage, {mass.summary.measurement_days} gemeinsame Messtage): fettfreie Masse {signed(mass.summary.ffm_delta)} kg · Fettmasse {signed(mass.summary.fat_delta)} kg</p>}
        <p className="mt-2 text-xs text-muted">Messlücken bleiben sichtbar. Veränderungen der fettfreien Masse sind kein Nachweis für Muskelaufbau oder Muskelverlust.</p>
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
        <p className="mt-3 text-xs text-muted">Lineare Fortsetzung des bisherigen geglätteten Gewichtsverlaufs, kein Ziel und keine sichere Vorhersage.</p>
      </> : <p className="mt-2 text-xs text-muted" role="status">{forecast?.available === false ? forecast.reason ?? "Fortschreibung pausiert: noch nicht genügend Messdaten." : state("forecast", forecast != null)}</p>}
      {forecast?.observed_days != null && <p className="mt-2 text-xs text-muted">Basis: {forecast.observed_days} Messtage über {forecast.span_days ?? 0} verstrichene Tage im letzten {forecast.fit_days ?? 30}-Tage-Fenster. Diese Abdeckungsregeln sind keine Genauigkeitsgarantie.</p>}
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
      </> : <p className="mt-2 text-xs text-muted" role="status">{composition?.available === false ? composition.reason ?? "Szenarien pausiert: die gemeinsame Datenbasis reicht noch nicht aus." : state("composition", composition != null)}</p>}
    </section>
  </div>;
}
