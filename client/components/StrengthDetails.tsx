"use client";

import { useEffect, useState } from "react";
import { api, type RpePoint, type StrengthEnergy, type StrengthIndex, type TonnagePoint } from "@/lib/api";
import { AreaTrend, Bars, DualAxisTrend, MultiTrend } from "@/components/charts";
import { de, de0, dm } from "@/lib/format";

const signed = (value: number) => `${value > 0 ? "+" : ""}${de(value, 1)}`;
const correlation = (value: number | null) => value == null ? "nicht berechenbar" : `r = ${de(value, 2)}`;

export function StrengthDetails({ index }: { index: StrengthIndex | null }) {
  const [rpe, setRpe] = useState<RpePoint[] | null>(null);
  const [tonnage, setTonnage] = useState<TonnagePoint[] | null>(null);
  const [energy, setEnergy] = useState<StrengthEnergy | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  useEffect(() => {
    let active = true;
    const failed = (key: string) => { if (active) setErrors((values) => [...values, key]); };
    api.strengthRpe(12).then((value) => { if (active) setRpe(value); }).catch(() => failed("rpe"));
    api.strengthTonnage(12).then((value) => { if (active) setTonnage(value); }).catch(() => failed("tonnage"));
    api.strengthEnergy().then((value) => { if (active) setEnergy(value); }).catch(() => failed("energy"));
    return () => { active = false; };
  }, []);
  const state = (key: string, loaded: boolean) => errors.includes(key) ? "Daten konnten nicht geladen werden." : loaded ? "Noch nicht genügend Daten." : "Wird geladen …";
  return <div className="space-y-6 text-sm">
    <section>
      <h3 className="font-semibold">Gesamtstärke · Berechnung & gesamter Verlauf</h3>
      <p className="mt-1 text-xs text-muted">Der Index vergleicht geschätzte Maximalkraft (e1RM) derselben Übungen zwischen Monaten, mit ausgeglichenem Gewicht je Muskelgruppe. Last und Wiederholungen fließen ein; Trainingsvolumen und RPE nicht. Maschinenwerte sind keine gemessene Maximalkraft.</p>
      {index?.series?.length ? <div className="mt-4"><MultiTrend height={240} labels={index.series.map((point) => dm(point.week))} format={(value) => de(value, 1)} series={[
        { values: index.series.map((point) => point.raw), label: "Woche (ungeglättet)", color: "var(--color-muted)" },
        { values: index.series.map((point) => point.anchor), label: "Monatsanker", color: "#bd7b1a" },
        { values: index.series.map((point) => point.smoothed), label: "Wochentrend", color: "var(--color-accent)" },
      ]} /></div> : <p className="mt-2 text-xs text-muted">Kein Index verfügbar.</p>}
      <p className="mt-2 text-xs text-muted">Hauptwert und Veränderung stammen aus dem Monatsindex. Die Wochenkurve wird am Monatsindex ausgerichtet und geglättet; schwach belegte Wochen werden rechnerisch ergänzt. Auch die ungeglättete Wochenlinie ist ein Modellwert. Programm- und Gerätewechsel können die Vergleichbarkeit einschränken.</p>
    </section>
    <section className="border-t border-line pt-4">
      <h3 className="font-semibold">Bewegte Last · letzte 12 erfasste Trainingswochen</h3>
      {tonnage?.length ? <div className="mt-3"><Bars data={tonnage.map((point) => ({ label: dm(point.week), value: point.tonnage_kg / 1000 }))} unit="t" height={220} /></div> : <p className="mt-2 text-xs text-muted">{state("tonnage", tonnage != null)}</p>}
      <p className="mt-2 text-xs text-muted">Summe aus Gewicht × Wiederholungen. Trainingsfreie Wochen fehlen. Mehr Tonnage bedeutet mehr bewegte Last, aber nicht automatisch mehr Kraft.</p>
    </section>
    <section className="border-t border-line pt-4">
      <h3 className="font-semibold">Anstrengung · letzte 12 Wochen mit RPE</h3>
      {rpe?.length ? <div className="mt-3"><AreaTrend values={rpe.map((point) => point.rpe)} labels={rpe.map((point) => dm(point.week))} height={220} /></div> : <p className="mt-2 text-xs text-muted">{state("rpe", rpe != null)}</p>}
      <p className="mt-2 text-xs text-muted">Durchschnitt der dokumentierten Satzbewertungen. RPE beschreibt die selbst eingeschätzte Anstrengung; allein daraus lässt sich keine Ermüdung ableiten.</p>
    </section>
    <section className="border-t border-line pt-4">
      <h3 className="font-semibold">Stärke & geschätzte Energiebilanz</h3>
      {energy?.series?.length ? <>
        <p className="mt-2 text-xs text-muted">Letzte {energy.recent_weeks} gemeinsame Wochen: Index {signed(energy.recent_index_delta)} Punkte bei geschätzt Ø {de0(Math.abs(energy.recent_deficit_avg))} kcal/Tag {energy.recent_deficit_avg >= 0 ? "Defizit" : "Überschuss"}.</p>
        <div className="mt-4"><DualAxisTrend height={240} labels={energy.series.map((point) => dm(point.week))}
          left={{ values: energy.series.map((point) => point.index), label: "Stärkeindex", color: "var(--color-accent)", format: (value) => de(value, 1) }}
          right={{ values: energy.series.map((point) => point.deficit), label: "Defizit (+) / Überschuss (−), kcal/Tag", color: "#bd7b1a" }} /></div>
        <div className="mt-3 space-y-1 text-xs text-muted">
          <p>Indexänderung gegenüber der vorherigen erfassten Woche vs. Energiebilanz: {correlation(energy.corr_change_deficit)}</p>
          <p>Indexniveau vs. Energiebilanz: {correlation(energy.corr_index_deficit)}</p>
        </div>
        <p className="mt-2 text-xs text-muted">{energy.n_weeks} gemeinsame Wochen · zwei unterschiedliche Y-Skalen. Die Korrelationen beschreiben Zusammenhänge, keine Ursache. Zeittrends, Glättung, Programmwechsel und unvollständige Ernährungseinträge können sie beeinflussen. Ein steigender Index im Defizit belegt keine Veränderung der Körperzusammensetzung.</p>
      </> : <p className="mt-2 text-xs text-muted">{state("energy", energy != null)}</p>}
    </section>
  </div>;
}
