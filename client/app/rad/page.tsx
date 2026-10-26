"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type BikePlanOverview, type CycSummary, type CycCurve, type CycEftp, type CycHrAtPower, type CycEfficiency, type CycZones, type CycWkgHr, type CycRide, type CycWorlds } from "@/lib/api";
import { Card, CardTitle, Kpi, PageTitle, Loading, ApiError } from "@/components/ui";
import { AreaTrend, MultiTrend } from "@/components/charts";
import { TrendBadge } from "@/components/RunningMoreAnalyses";
import { CurveTable, EFTP_SOURCE, Empty, LogCurve, RideRow, WeeklyZones, WkgHrChart, hasPower } from "@/components/Cycling";
import { PlanTodayCard } from "@/components/BikePlan";
import { de, de0, dm } from "@/lib/format";

const LIST_LIMIT = 20;

function weekStart(): number {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d.getTime();
}

export default function Rad() {
  const [summary, setSummary] = useState<CycSummary | null>(null);
  const [rides, setRides] = useState<CycRide[]>([]);
  const [curve, setCurve] = useState<CycCurve | null>(null);
  const [eftp, setEftp] = useState<CycEftp | null>(null);
  const [hrp, setHrp] = useState<CycHrAtPower | null>(null);
  const [eff, setEff] = useState<CycEfficiency | null>(null);
  const [zones, setZones] = useState<CycZones | null>(null);
  const [wkgHr, setWkgHr] = useState<CycWkgHr | null>(null);
  const [plan, setPlan] = useState<BikePlanOverview | null>(null);
  const [worlds, setWorlds] = useState<CycWorlds | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [extrasError, setExtrasError] = useState(false);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    const soft = () => setExtrasError(true);
    api.cycSummary().then(setSummary).catch((e) => setErr(String(e)));
    api.cycRides(0).then(setRides).catch(soft);
    api.cycPowerCurve().then(setCurve).catch(soft);
    api.cycEftp().then(setEftp).catch(soft);
    api.cycHrAtPower().then(setHrp).catch(soft);
    api.cycEfficiency().then(setEff).catch(soft);
    api.cycZones().then(setZones).catch(soft);
    api.cycWkgHr().then(setWkgHr).catch(soft);
    api.bikePlan().then(setPlan).catch(() => setPlan(null));
    api.cycWorlds().then(setWorlds).catch(soft);
  }, []);

  if (err) return <><PageTitle title="Rad" /><ApiError error={err} /></>;
  if (!summary) return <><PageTitle title="Rad" /><Loading /></>;
  if (summary.rides === 0) {
    return <>
      <PageTitle title="Rad" sub="Zwift & Indoor-Training" />
      <Card><Empty height={160}>Noch keine Indoor- oder Zwift-Fahrt. Sobald Garmin Connect eine Fahrt liefert und der Daten-Abgleich gelaufen ist, erscheinen hier Leistung, eFTP und Trainingslast.</Empty></Card>
    </>;
  }

  const ws = weekStart();
  const thisWeek = rides.filter((r) => new Date(r.date).getTime() >= ws);
  const weekMin = thisWeek.reduce((a, r) => a + (r.minutes ?? 0), 0);
  const since = Date.now() - 30 * 86400000;
  const powered = rides.filter((r) => hasPower(r) && r.avg_power != null && new Date(r.date).getTime() >= since);
  const pw = powered.reduce((a, r) => a + (r.minutes ?? 0), 0);
  const avgPower = pw > 0 ? powered.reduce((a, r) => a + (r.avg_power as number) * (r.minutes ?? 0), 0) / pw : null;
  const noPower = summary.rides_with_power === 0;
  const hrSeries = hrp?.series ?? [];
  const effSeries = eff?.series ?? [];
  const eftpSeries = eftp?.series ?? [];
  const listed = showAll ? rides : rides.slice(0, LIST_LIMIT);

  return <>
    <PageTitle title="Rad" sub="Zwift & Indoor-Training — Leistung, Fitness & Last" />

    {plan?.plan ? <Card className="mb-4"><PlanTodayCard data={plan} /></Card>
      : plan && <p className="mb-3 text-xs text-muted">Trainingsplan? <Link href="/rad/plan" className="text-accent underline underline-offset-4">Plan importieren →</Link></p>}

    <section aria-label="Kennzahlen" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Kpi label="eFTP" sub={summary.eftp_source ? `Quelle: ${EFTP_SOURCE[summary.eftp_source] ?? summary.eftp_source}` : "noch nicht bestimmbar"}
        value={de0(summary.eftp)} unit="W" delta={summary.wkg != null ? `${de(summary.wkg, 2)} W/kg` : undefined} deltaKind="muted" />
      <Kpi label="Diese Woche" sub={`seit ${dm(new Date(ws).toISOString())}`} value={String(thisWeek.length)} unit={thisWeek.length === 1 ? "Fahrt" : "Fahrten"}
        delta={`${de(weekMin / 60, 1)} h`} deltaKind="muted" />
      <Kpi label="Ø-Leistung" sub="letzte 30 Tage, zeitgewichtet" value={de0(avgPower)} unit="W"
        delta={noPower ? "keine Fahrt mit Leistung" : `${summary.rides_with_power} Fahrten mit Leistung`} deltaKind="muted" />
      <Kpi label="Trainingslast" sub="TSS aus Leistung" value={de0(summary.tss_7d)} unit="TSS / 7 T"
        delta={`${de0(summary.tss_28d)} TSS / 28 T`} deltaKind="muted" />
    </section>
    {noPower && <p role="status" className="mt-3 text-xs text-muted">Bisher keine Fahrt mit Leistungsdaten — Leistungskurve, eFTP und Zonen erscheinen mit der ersten Fahrt am Trainer.</p>}
    {extrasError && <p role="status" className="mt-3 text-xs text-muted">Einige Daten konnten nicht geladen werden. Bitte die Seite neu laden.</p>}

    <div className="mt-4 grid items-start gap-4 [&>*]:min-w-0">
      <Card>
        <CardTitle title="Leistungskurve" sub={`Beste Leistung je Dauer — letzte ${curve?.window_days ?? 90} Tage gegen die ${curve?.window_days ?? 90} Tage davor; Punkte = Allzeit-Bestwerte`} />
        {curve ? <>
          <LogCurve
            lines={[
              { label: `letzte ${curve.window_days} T`, color: "var(--color-accent)", points: curve.durations.map((d) => ({ seconds: d.seconds, watts: d.recent })) },
              { label: `${curve.window_days} T davor`, color: "var(--color-accent-2)", dash: "4 3", width: 1.6, points: curve.durations.map((d) => ({ seconds: d.seconds, watts: d.previous })) },
            ]}
            dots={{ label: "Allzeit-Bestwert", color: "#b53415", points: curve.durations.map((d) => ({ seconds: d.seconds, watts: d.best, date: d.best_date })) }}
          />
          {curve.durations.length > 0 && <CurveTable curve={curve} />}
        </> : <Loading />}
      </Card>

      <Card>
        <CardTitle title="eFTP-Verlauf" sub="Wochenwerte der automatischen eFTP (90-Tage-Fenster) in Watt" />
        {eftp ? <>
          {eftpSeries.filter((p) => p.eftp != null).length >= 2
            ? <AreaTrend values={eftpSeries.map((p) => p.eftp)} labels={eftpSeries.map((p) => dm(p.week))} unit="W" format={(n) => de0(n)} height={170} smooth />
            : <Empty height={120}>zu wenig Wochen für einen Verlauf</Empty>}
          {eftp.setting ? <p className="mt-2 text-[11px] text-muted">Eingestellte FTP {de0(eftp.setting)} W übersteuert die aktuelle eFTP; der Verlauf zeigt die automatische Schätzung.</p> : null}
          {eftp.caveat && <p className="mt-2 text-[11px] text-muted">{eftp.caveat}</p>}
        </> : <Loading />}
      </Card>

      <div className="grid items-start gap-4 [&>*]:min-w-0 lg:grid-cols-2">
        <Card>
          <div className="mb-3 flex items-start justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold">Puls bei Referenzleistung</h3>
              <p className="text-[11px] text-muted">{hrp?.ref_power ? `Puls bei ca. ${de0(hrp.ref_power)} W je Fahrt — niedriger = fitter` : "Puls bei gleicher Leistung — niedriger = fitter"}</p>
            </div>
            <TrendBadge t={hrp?.trend} />
          </div>
          {hrp ? <>
            {hrSeries.length >= 2 ? <MultiTrend height={170} format={(n) => de0(n)} unit="bpm" labels={hrSeries.map((p) => dm(p.date))}
              series={[
                { values: hrSeries.map((p) => p.hr), label: "je Fahrt", color: "var(--color-accent-2)" },
                { values: hrSeries.map((p) => p.smooth), label: "geglättet (EWMA)", color: "var(--color-accent)", smooth: true },
              ]} /> : <Empty height={130}>noch zu wenige Fahrten mit gültigem Puls und Leistung (ab 6)</Empty>}
            {hrp.trend?.delta_bpm != null && hrp.trend.verdict !== "wenig_daten" && <p className="mt-2 text-[11px] text-muted">Δ {de(hrp.trend.delta_bpm, 1)} bpm über {hrp.trend.days} Tage · {hrp.trend.n} Fahrten</p>}
            {hrp.caveat && <p className="mt-1 text-[11px] text-muted">{hrp.caveat}</p>}
          </> : <Loading />}
        </Card>

        <Card>
          <div className="mb-3 flex items-start justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold">Effizienz NP / Puls</h3>
              <p className="text-[11px] text-muted">Watt je Herzschlag-Minute (NP ÷ Ø-HF) je Fahrt + EWMA — höher = fitter</p>
            </div>
            <TrendBadge t={eff?.trend} />
          </div>
          {eff ? <>
            {effSeries.length >= 2 ? <MultiTrend height={170} format={(n) => de(n, 2)} labels={effSeries.map((p) => dm(p.date))}
              series={[
                { values: effSeries.map((p) => p.ef), label: "je Fahrt", color: "var(--color-accent-2)", width: 1 },
                { values: effSeries.map((p) => p.smooth), label: "geglättet (EWMA)", color: "var(--color-accent)", smooth: true, width: 2.4 },
              ]} /> : <Empty height={130}>erst ab zwei Fahrten mit gültigem Puls</Empty>}
            {eff.trend?.delta != null && eff.trend.verdict !== "wenig_daten" && <p className="mt-2 text-[11px] text-muted">Δ {de(eff.trend.delta, 2)} W/bpm über {eff.trend.days} Tage · {eff.rides} Fahrten</p>}
            <div className="mt-3 border-t border-line pt-3">
              <h4 className="text-xs font-semibold">Entkopplung (Pw:HR) <span className="font-normal text-muted">· letzte 8 gleichmäßige Fahrten</span></h4>
              {(eff.decoupling ?? []).length ? <ul className="mt-1 divide-y divide-line text-xs tabular-nums">
                {eff.decoupling!.slice(-8).reverse().map((d) => (
                  <li key={d.activity_id} className="flex items-baseline justify-between gap-3 py-1.5">
                    <span className="min-w-0 truncate text-muted">{dm(d.date)} · {d.title ?? "Fahrt"} · {de0(d.minutes)} min</span>
                    <span className={`shrink-0 font-semibold ${d.decoupling_pct < 5 ? "text-good" : "text-ink"}`}>{de(d.decoupling_pct, 1)} %</span>
                  </li>
                ))}
              </ul> : <p className="mt-1 text-[11px] text-muted">Noch keine gleichmäßige Fahrt ≥ 20 min mit gültigem Puls.</p>}
            </div>
            {eff.caveat && <p className="mt-2 text-[11px] text-muted">{eff.caveat}</p>}
          </> : <Loading />}
        </Card>
      </div>

      <Card>
        <CardTitle title="Puls je W/kg" sub="Welcher Puls bei welcher Leistung pro kg? Hintergrund = Leistungszonen (aktuelle eFTP), gestrichelt = Puls-Zonen — tiefer bzw. weiter rechts = fitter" />
        {wkgHr ? <>
          <WkgHrChart data={wkgHr} />
          {wkgHr.caveat && <p className="mt-2 text-[11px] text-muted">{wkgHr.caveat}</p>}
        </> : <Loading />}
      </Card>

      <Card>
        <CardTitle title="Zeit in Leistungszonen" sub="Minuten je Woche, letzte 12 Wochen — Zonen nach Coggan, bezogen auf die eFTP am Fahrttag" />
        {zones ? <>
          <WeeklyZones data={zones} />
          {zones.unzoned_rides > 0 && <p className="mt-2 text-[11px] text-muted">{zones.unzoned_rides} {zones.unzoned_rides === 1 ? "Fahrt" : "Fahrten"} ohne Leistungsdaten oder eFTP sind hier nicht enthalten.</p>}
        </> : <Loading />}
      </Card>

      <Card>
        <CardTitle title="Fahrten" sub={`${summary.rides} insgesamt · ${de(summary.hours, 1)} h · ${de0(summary.km)} km (virtuell) · ${de0(summary.kj)} kJ`} />
        {rides.length ? <>
          <div className="divide-y divide-line">{listed.map((r) => <RideRow key={r.activity_id} r={r} />)}</div>
          {rides.length > LIST_LIMIT && <button type="button" className="mt-2 py-2 text-xs text-muted underline underline-offset-4" onClick={() => setShowAll(!showAll)}>{showAll ? "Weniger anzeigen" : `Alle ${rides.length} Fahrten anzeigen`}</button>}
        </> : <Empty height={80}>Fahrtenliste nicht verfügbar</Empty>}
      </Card>

      <Card>
        <CardTitle title="Zwift-Welten & Routen" sub="Gefahrene Welten und Routen — ohne Karte, nur Zähler" />
        {worlds ? (worlds.worlds.length ? <div className="divide-y divide-line">
          {worlds.worlds.map((w) => (
            <details key={w.world} className="py-2">
              <summary className="flex cursor-pointer items-baseline justify-between gap-3 text-sm">
                <span className="min-w-0 truncate font-semibold">{w.world}</span>
                <span className="shrink-0 text-xs tabular-nums text-muted">{w.rides} {w.rides === 1 ? "Fahrt" : "Fahrten"} · {de(w.km, 1)} km · {de0(w.elevation_m)} Hm · {de(w.hours, 1)} h</span>
              </summary>
              <ul className="mt-2 space-y-1 pl-3 text-xs tabular-nums text-muted">
                {w.routes.map((r) => <li key={r.route} className="flex justify-between gap-3"><span className="min-w-0 truncate">{r.route === "–" ? "ohne Route" : r.route}</span><span className="shrink-0">{r.rides}× · {de(r.km, 1)} km · {de0(r.elevation_m)} Hm · zuletzt {dm(r.last)}</span></li>)}
              </ul>
            </details>
          ))}
          {worlds.other_rides > 0 && <p className="pt-2 text-xs text-muted">+ {worlds.other_rides} {worlds.other_rides === 1 ? "Fahrt" : "Fahrten"} ohne Welt (z. B. Workouts)</p>}
        </div> : <Empty height={80}>Noch keine Fahrt in einer Zwift-Welt.</Empty>) : <Loading />}
      </Card>
    </div>
  </>;
}
