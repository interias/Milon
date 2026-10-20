"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, type CycCurve, type CycEfficiency, type CycRideDetail } from "@/lib/api";
import { Card, CardTitle, Loading, ApiError } from "@/components/ui";
import { AreaTrend } from "@/components/charts";
import { Empty, LogCurve, RideZoneBar, fmtWhen, hasPower, rideTitle } from "@/components/Cycling";
import { de, de0 } from "@/lib/format";

function Stat({ label, value, unit, sub }: { label: string; value: string; unit?: string; sub?: string }) {
  return (
    <div className="min-w-0 rounded-card border border-line bg-surface p-3">
      <p className="text-[11px] text-muted">{label}</p>
      <p className="mt-1 font-display text-xl font-extrabold tabular-nums">{value}{unit && <span className="ml-1 text-xs font-semibold text-muted">{unit}</span>}</p>
      {sub && <p className="mt-0.5 text-[10px] text-muted">{sub}</p>}
    </div>
  );
}

export default function RideDetailPage() {
  const params = useParams();
  const raw = Array.isArray(params.id) ? params.id[0] : (params.id ?? "");
  let id = raw;
  try { id = decodeURIComponent(raw); } catch { /* Route-Text lesbar lassen. */ }
  const [ride, setRide] = useState<CycRideDetail | null>(null);
  const [curve, setCurve] = useState<CycCurve | null>(null);
  const [eff, setEff] = useState<CycEfficiency | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setRide(null); setError(null);
    api.cycRide(id).then((v) => { if (active) setRide(v); }).catch((e) => { if (active) setError(String(e)); });
    api.cycPowerCurve().then((v) => { if (active) setCurve(v); }).catch(() => {});
    api.cycEfficiency().then((v) => { if (active) setEff(v); }).catch(() => {});
    return () => { active = false; };
  }, [id]);

  const back = <Link href="/rad" className="text-xs font-semibold text-accent hover:underline">← Rad</Link>;
  if (error) return <>{back}<div className="mt-3">{error.includes("404") ? <Card><Empty height={100}>Diese Fahrt wurde nicht gefunden.</Empty></Card> : <ApiError error={error} />}</div></>;
  if (!ride) return <>{back}<div className="mt-3"><Loading /></div></>;

  const power = hasPower(ride);
  const s = ride.series ?? [];
  const labels = s.map((p) => `${de0(p.t / 60)} min`);
  const col = (k: "power_w" | "hr_bpm" | "cadence_rpm") => s.map((p) => (p[k] != null && (k !== "power_w" || p[k]! >= 0) ? (p[k] as number) : null));
  const watts = col("power_w"), bpm = col("hr_bpm"), rpm = col("cadence_rpm");
  const some = (v: (number | null)[]) => v.filter((x) => x != null).length >= 2;
  const decoupling = eff?.decoupling?.find((d) => d.activity_id === ride.activity_id);
  const bests = curve?.durations ?? [];

  return <>
    <header className="mb-5">
      {back}
      <h1 className="mt-1 break-words font-display text-2xl font-extrabold tracking-tight">{rideTitle(ride)}</h1>
      <p className="mt-1 text-sm text-muted">{fmtWhen(ride.date)} · {ride.type === "virtual_ride" ? "Zwift / virtuell" : "Indoor"}{ride.world ? ` · ${ride.world}` : ""}{ride.route ? ` · ${ride.route}` : ""}</p>
    </header>

    {!power && <p role="status" className="mb-4 rounded-card border border-line bg-surface-alt p-3 text-xs text-muted">Diese Fahrt hat keine Leistungsdaten (kein Powermeter bzw. Smart-Trainer). Leistungskurve, Zonen und Last entfallen; Dauer, Strecke und Puls stehen unten.</p>}
    {ride.avg_hr != null && !ride.hr_valid && <p role="status" className="mb-4 rounded-card border border-warn/40 bg-warn/10 p-3 text-xs text-ink">Der Puls dieser Fahrt ist nicht plausibel (Ø unter 60 bpm oder viele Aussetzer{ride.hr_dropout != null ? `, ${de0(ride.hr_dropout * 100)} % ohne Wert` : ""}). Er wird nicht gezeigt und fließt in keine Puls-Kennzahl ein.</p>}

    {ride.avg_hr == null && !ride.hr_valid && <p role="status" className="mb-4 text-xs text-muted">Kein Puls aufgezeichnet — Puls-Kennzahlen entfallen.</p>}

    <section aria-label="Kennzahlen" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      <Stat label="Dauer" value={de0(ride.minutes)} unit="min" sub={ride.km != null ? `${de(ride.km, 1)} km virtuell` : undefined} />
      {power && <>
        <Stat label="Ø-Leistung" value={de0(ride.avg_power)} unit="W" sub={ride.max_power != null ? `max ${de0(ride.max_power)} W` : undefined} />
        <Stat label="Normalized Power" value={de0(ride.np)} unit="W" />
        <Stat label="Intensität (IF)" value={de(ride.if, 2)} sub={ride.eftp != null ? `bei eFTP ${de0(ride.eftp)} W` : "eFTP fehlt"} />
        <Stat label="TSS" value={de0(ride.tss)} />
        <Stat label="Arbeit" value={de0(ride.kj)} unit="kJ" />
        <Stat label="Entkopplung" value={decoupling ? `${de(decoupling.decoupling_pct, 1)} %` : "–"} sub={decoupling ? (decoupling.decoupling_pct < 5 ? "stabile aerobe Basis" : "Puls driftet gegen Leistung") : "nur gleichmäßige Fahrten ≥ 20 min mit Puls"} />
      </>}
      {ride.hr_valid && ride.avg_hr != null && <Stat label="Ø-Puls" value={de0(ride.avg_hr)} unit="bpm" sub={ride.max_hr != null ? `max ${de0(ride.max_hr)} bpm` : undefined} />}
      {ride.cadence != null && <Stat label="Trittfrequenz" value={de0(ride.cadence)} unit="rpm" />}
      {ride.elevation_m != null && ride.elevation_m > 0 && <Stat label="Höhenmeter" value={de0(ride.elevation_m)} unit="m" sub="virtuell" />}
      {ride.aerobic_te != null && <Stat label="Trainingseffekt" value={de(ride.aerobic_te, 1)} sub={`aerob${ride.anaerobic_te != null ? ` · anaerob ${de(ride.anaerobic_te, 1)}` : ""}`} />}
    </section>

    <div className="mt-4 grid items-start gap-4 [&>*]:min-w-0">
      <Card>
        <CardTitle title="Verlauf" sub="Leistung, Puls und Trittfrequenz über die Fahrzeit" />
        {s.length < 2 ? <Empty height={100}>keine Sekunden-Daten gespeichert</Empty> : <div className="space-y-5">
          {some(watts) && <div><p className="mb-1 text-xs font-semibold">Leistung</p><AreaTrend values={watts} labels={labels} unit="W" format={(n) => de0(n)} height={130} /></div>}
          {ride.hr_valid && some(bpm) && <div><p className="mb-1 text-xs font-semibold">Puls</p><AreaTrend values={bpm} labels={labels} unit="bpm" format={(n) => de0(n)} height={110} className="text-bad" /></div>}
          {some(rpm) && <div><p className="mb-1 text-xs font-semibold">Trittfrequenz</p><AreaTrend values={rpm} labels={labels} unit="rpm" format={(n) => de0(n)} height={110} className="text-accent-2" /></div>}
          {!some(watts) && !some(bpm) && !some(rpm) && <Empty height={80}>weder Leistung noch Puls in der Serie</Empty>}
        </div>}
      </Card>

      <div className="grid items-start gap-4 [&>*]:min-w-0 lg:grid-cols-2">
        <Card>
          <CardTitle title="Leistungskurve der Fahrt" sub="Beste Leistung dieser Fahrt je Dauer gegen deine Allzeit-Bestwerte" />
          {power ? <LogCurve height={200}
            lines={[
              { label: "diese Fahrt", color: "var(--color-accent)", points: ride.power_curve },
              { label: "Allzeit-Bestwerte", color: "var(--color-accent-2)", dash: "4 3", width: 1.6, points: bests.map((d) => ({ seconds: d.seconds, watts: d.best })) },
            ]} /> : <Empty height={120}>keine Leistungsdaten</Empty>}
        </Card>
        <Card>
          <CardTitle title="Zeit in Leistungszonen" sub="Coggan-Zonen bezogen auf die eFTP am Fahrttag" />
          <RideZoneBar zones={ride.zones ?? []} />
        </Card>
      </div>
    </div>
  </>;
}
