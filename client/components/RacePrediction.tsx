"use client";

import { useEffect, useState } from "react";
import { api, type RacePrediction as Prediction } from "@/lib/api";
import { dur } from "@/lib/format";

/** Wettkampf-Prognose unter den Bestzeiten: Untergrenze aus Bestzeiten + Puls-Hochrechnung
 *  je HFmax-Annahme (Zeit ± Unsicherheit und nötiger Ø-Puls). */
export function RacePrediction() {
  const [data, setData] = useState<Prediction | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => { api.runRacePrediction().then(setData).catch(() => setFailed(true)); }, []);
  if (failed) return <p className="mt-4 text-xs text-muted">Prognose nicht verfügbar.</p>;
  if (!data) return null;
  if (!data.distances?.length) return <p className="mt-4 text-xs text-muted">Für eine Prognose fehlen noch Läufe mit Puls.</p>;
  const scenarios = data.scenarios ?? [];
  return (
    <div className="mt-4 border-t border-line pt-3">
      <h3 className="text-sm font-semibold">Prognose Wettkampf</h3>
      <p className="mt-0.5 text-[11px] text-muted">Geschätzt aus deinem Training, nicht aus Rennen · Zeit ± Unsicherheit · Ø-Puls, den du halten müsstest</p>
      <table className="mt-2 w-full text-sm tabular-nums">
        <thead>
          <tr className="border-b border-line text-xs text-muted">
            <th scope="col" className="pb-2 text-left font-medium">Strecke</th>
            <th scope="col" className="pb-2 text-right font-medium">Bisher</th>
            {scenarios.map((s) => <th key={s} scope="col" className="pb-2 text-right font-medium">HFmax {s}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {data.distances.map((d) => (
            <tr key={d.label} className={d.reliable ? "" : "text-muted"} title={d.note ?? undefined}>
              <th scope="row" className="py-2 text-left align-top font-semibold">
                {d.label}{!d.reliable && <span className="block text-[11px] font-normal">ohne Grundlage</span>}
              </th>
              <td className="py-2 text-right align-top">
                {d.floor ? <>{dur(d.floor.seconds)}<span className="block text-[11px] text-muted">{d.floor.measured ? "gelaufen" : `aus ${d.floor.from}`}</span></> : "–"}
              </td>
              {scenarios.map((s, i) => {
                const c = d.cells[i];
                return (
                  <td key={s} className="py-2 text-right align-top">
                    {c ? <>
                      <span className={d.reliable ? "font-semibold text-accent" : "font-semibold"}>{dur(c.seconds)}</span>
                      <span className="block text-[11px] text-muted">{c.at_floor ? "wie bisher" : `± ${dur(c.pm)}`}</span>
                      <span className="block text-[11px] text-muted" title={c.beyond_bpm > 0 ? `${c.beyond_bpm} bpm über deinem bisher höchsten Ø-Puls im Training` : undefined}>
                        Ø {c.race_hr} bpm{c.beyond_bpm > 0 && " ↑"}
                      </span>
                    </> : "–"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {data.distances.some((d) => !d.reliable) && <p className="mt-2 text-[11px] text-muted">
        {data.distances.find((d) => !d.reliable)?.note}</p>}
      <details className="mt-2 text-[11px] text-muted">
        <summary className="cursor-pointer py-1">So wird gerechnet</summary>
        <ul className="mt-1 list-disc space-y-1 pl-4">
          <li><strong>Bisher:</strong> deine Bestzeit der letzten 90 Tage, mit der Riegel-Formel auf andere Strecken umgerechnet. Das hast du im Training schon geschafft.</li>
          <li><strong>HFmax {scenarios.join(" / ")}:</strong> der Puls, den du im Rennen halten müsstest (5 km 95 %, 10 km 92 %, Halbmarathon 88 %, Marathon 83 % von HFmax). Die zweite Spalte ist vorsichtiger: weniger Puls, den du halten kannst.</li>
          <li>Die Zeit ist das Mittel aus zwei Rechnungen: (1) aus {data.model?.runs} Läufen gelernt, wie schnell du bei welchem Puls bist ({data.model?.hr_lo}–{data.model?.hr_hi} bpm), und (2) deine beste 5-/10-km-Zeit, um den Puls-Unterschied zum Renn-Puls hochgerechnet. Allein lag (1) im Rückblick 3 % zu langsam, (2) 4 % zu schnell, das Mittel traf auf 1 % genau.</li>
          <li>± = eine Standardabweichung, rund zwei von drei Läufen liegen darin. „wie bisher“ = bei diesem Puls nicht schneller als deine Bestzeit. ↑ = mehr Puls als in deinem Training, dort ist die Hochrechnung ungeprüft.</li>
        </ul>
      </details>
    </div>
  );
}
