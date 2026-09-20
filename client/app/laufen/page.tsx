"use client";

import { useEffect, useState } from "react";
import { api, type RunWeekOverview, type VolPoint, type BestEfforts, type Achievements } from "@/lib/api";
import { Card, CardTitle, PageTitle, Loading, ApiError } from "@/components/ui";
import { Bars } from "@/components/charts";
import { AchievementsSummary, AchievementsGrid } from "@/components/Achievements";
import { StandardizedRunHr } from "@/components/StandardizedRunHr";
import { RunAnalysisSettings } from "@/components/RunAnalysisSettings";
import { RunningFitness } from "@/components/RunningFitness";
import { RunningMoreAnalyses } from "@/components/RunningMoreAnalyses";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
import { de, de0, dm, dur } from "@/lib/format";

type Panel = "analyses" | "achievements" | "records" | null;
const linkClass = "py-2 text-xs text-muted underline underline-offset-4";
const delta = (current: number, previous: number, digits = 0) => `${current > previous ? "+" : ""}${de(current - previous, digits)}`;

export default function Laufen() {
  const [week, setWeek] = useState<RunWeekOverview | null>(null);
  const [vol, setVol] = useState<VolPoint[] | null>(null);
  const [best, setBest] = useState<BestEfforts | null>(null);
  const [ach, setAch] = useState<Achievements | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [extrasError, setExtrasError] = useState(false);
  const [panel, setPanel] = useState<Panel>(null);
  useEffect(() => {
    api.runWeekOverview().then(setWeek).catch((e) => setErr(String(e)));
    api.runVolume(12).then(setVol).catch(() => setExtrasError(true));
    api.runBestEfforts().then(setBest).catch(() => setExtrasError(true));
    api.runAchievements().then(setAch).catch(() => setExtrasError(true));
  }, []);
  if (err) return <><PageTitle title="Laufen" /><ApiError error={err} /></>;
  if (!week) return <><PageTitle title="Laufen" /><Loading /></>;
  const { current, previous } = week;
  return <>
    <PageTitle title="Laufen" sub="Training, Fitness & Bestleistungen" />
    <section aria-labelledby="running-training">
      <h2 id="running-training" className="mb-3 font-display text-lg font-extrabold">Training</h2>
      <Card>
        <p className="text-xs text-muted">Diese Woche · seit {dm(week.week_start)}</p>
        <div className="mt-3 grid grid-cols-3 gap-3 tabular-nums">
          {[
            { label: "Kilometer", value: de(current.km, 1), change: `${delta(current.km, previous.km, 1)} km` },
            { label: "Läufe", value: de0(current.runs), change: `${delta(current.runs, previous.runs)} Läufe` },
            { label: "Laufzeit", value: `${de0(current.minutes)} min`, change: `${delta(current.minutes, previous.minutes)} min` },
          ].map((item) => <div key={item.label}><p className="text-xs text-muted">{item.label}</p><p className="mt-1 font-display text-xl font-extrabold sm:text-3xl">{item.value}</p><p className="mt-1 text-xs text-muted">{item.change}</p></div>)}
        </div>
        <p className="mt-3 text-[11px] text-muted">Veränderung gegenüber der gesamten Vorwoche · aktuelle Woche noch laufend</p>
        <div className="mt-5 border-t border-line pt-4">
          <CardTitle title="Wochenkilometer" sub="Letzte 12 Kalenderwochen" />
          {vol ? <Bars data={Array.from({ length: 12 }, (_, i) => {
            const date = new Date(`${week.week_start}T12:00:00Z`);
            date.setUTCDate(date.getUTCDate() - (11 - i) * 7);
            const key = date.toISOString().slice(0, 10);
            return { label: dm(key), value: vol.find((v) => v.week === key)?.km ?? 0 };
          })} unit="km" height={150} /> : <p className="text-xs text-muted">{extrasError ? "Wochenkilometer nicht verfügbar." : "Wochenkilometer werden geladen …"}</p>}
        </div>
      </Card>
    </section>

    <section className="mt-6" aria-labelledby="running-fitness">
      <h2 id="running-fitness" className="font-display text-lg font-extrabold">Fitness</h2>
      <div className="grid items-start gap-4 xl:grid-cols-2 [&>div]:min-w-0 [&>div]:mt-3">
        <RunningFitness />
        <StandardizedRunHr />
      </div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4">
        <button className={linkClass} onClick={() => setPanel("analyses")}>Weitere Analysen</button>
        <RunAnalysisSettings />
      </div>
    </section>

    <section className="mt-6" aria-labelledby="running-records">
      <h2 id="running-records" className="mb-3 font-display text-lg font-extrabold">Bestleistungen</h2>
      <Card>
        <div className="mb-3 flex items-center justify-between gap-3"><h3 className="text-sm font-semibold">Bestzeiten</h3><button className={linkClass} onClick={() => setPanel("records")}>Rekorddetails</button></div>
        {best?.distances.some((d) => d.entries.length > 0) ? <>
            <table className="w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-line text-xs text-muted">
                  <th scope="col" className="pb-2 text-left font-medium">Reichweite</th>
                  <th scope="col" className="pb-2 text-right font-medium">Zeit</th>
                  <th scope="col" className="pb-2 text-right font-medium">Datum</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {best.distances.filter((d) => d.entries.length > 0).map((d) => {
                  const entry = d.entries[0];
                  return (
                    <tr key={d.distance_m}>
                      <th scope="row" className="py-2 text-left font-semibold">{d.label}</th>
                      <td className="py-2 text-right font-semibold text-accent">{dur(Math.round(entry.seconds))}</td>
                      <td className="py-2 text-right text-muted">{dm(entry.date)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
        </> : <p className="text-xs text-muted">Noch keine Bestzeiten verfügbar.</p>}
        <p className="mt-2 text-[11px] text-muted">Schnellster Abschnitt innerhalb eines Laufs</p>
        {ach && <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
          <p className="text-sm"><strong>{ach.summary.earned} Erfolge</strong><span className="text-muted"> · {ach.summary.title} · {de0(ach.summary.points)} Punkte</span></p>
          <button className={linkClass} onClick={() => setPanel("achievements")}>Alle Erfolge</button>
        </div>}
      </Card>
    </section>
    {extrasError && <p role="status" className="mt-3 text-xs text-muted">Einige Zusatzdaten konnten nicht geladen werden. Bitte die Seite neu laden.</p>}
    {panel === "analyses" && <RunAnalysisDialog title="Weitere Laufanalysen" onClose={() => setPanel(null)}><RunningMoreAnalyses /></RunAnalysisDialog>}
    {panel === "achievements" && ach && <RunAnalysisDialog title="Alle Erfolge" onClose={() => setPanel(null)}><AchievementsSummary data={ach} /><div className="mt-5"><AchievementsGrid data={ach} /></div></RunAnalysisDialog>}
    {panel === "records" && <RunAnalysisDialog title="Rekorddetails" onClose={() => setPanel(null)}>
      <dl className="space-y-4 text-sm">
        <div><dt className="text-muted">Längster Lauf</dt><dd>{best?.records?.longest_run ? `${de(best.records.longest_run.km, 1)} km · ${dm(best.records.longest_run.date)}` : "Noch kein Wert"}</dd></div>
        <div><dt className="text-muted">Größte Woche</dt><dd>{best?.records?.biggest_week ? `${de(best.records.biggest_week.km, 1)} km · ${best.records.biggest_week.runs} Läufe · Woche vom ${dm(best.records.biggest_week.week)}` : "Noch kein Wert"}</dd></div>
        <div><dt className="text-muted">Beste aerobe Effizienz</dt><dd>{best?.records?.best_ef ? `${de(best.records.best_ef.ef, 2)} m/Herzschlag · ${dm(best.records.best_ef.date)}` : "Noch kein Wert"}</dd></div>
      </dl>
    </RunAnalysisDialog>}
  </>;
}
