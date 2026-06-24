"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, type ExerciseDetail } from "@/lib/api";
import { Card, CardTitle, Kpi, StatRow, Loading, ApiError } from "@/components/ui";
import { AreaTrend, Bars } from "@/components/charts";
import { de, de0, dm } from "@/lib/format";

const PERIODS: [string, string][] = [
  ["1m", "1 Monat"],
  ["3m", "3 Monate"],
  ["12m", "12 Monate"],
  ["all", "Gesamt"],
];

const sgn = (n: number, d = 1) => (n > 0 ? "+" : "") + de(n, d);

const STATUS_CLS: Record<string, string> = {
  progress: "border-good/30 bg-good/10 text-good",
  stall: "border-line bg-surface-alt text-muted",
  regress: "border-bad/30 bg-bad/10 text-bad",
  deload: "border-bad/30 bg-bad/10 text-bad",
  new: "border-line bg-surface-alt text-muted",
};
const STATUS_ICON: Record<string, string> = { progress: "📈", stall: "➖", regress: "📉", deload: "🛑", new: "•" };

function Delta({ label, value, kind = "good", sub }: { label: string; value: string; kind?: "good" | "bad" | "muted"; sub?: string }) {
  const cls = kind === "bad" ? "text-bad" : kind === "muted" ? "text-muted" : "text-good";
  return (
    <div>
      <div className="text-[11px] text-muted">{label}</div>
      <div className={`mt-0.5 font-display text-lg font-bold tracking-tight ${cls}`}>{value}</div>
      {sub && <div className="text-[10px] text-muted">{sub}</div>}
    </div>
  );
}

export default function ExerciseDetailPage() {
  const p = useParams();
  const raw = Array.isArray(p.exercise) ? p.exercise[0] : (p.exercise ?? "");
  let name = raw;
  try { name = decodeURIComponent(raw); } catch { /* schon dekodiert */ }

  const [period, setPeriod] = useState("all");
  const [data, setData] = useState<ExerciseDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let ignore = false;
    setLoading(true);
    setErr(null);  // vorherigen Fehler vor jedem neuen Versuch löschen (sonst Dauer-Fehlerscreen)
    api.strengthExercise(name, period)
      .then((d) => { if (!ignore) { setData(d); setLoading(false); } })
      .catch((e) => { if (!ignore) { setErr(String(e)); setLoading(false); } });
    return () => { ignore = true; };  // veraltete Antwort beim schnellen Umschalten verwerfen
  }, [name, period]);

  const header = (
    <header className="mb-5">
      <Link href="/kraft" className="text-xs font-semibold text-accent hover:underline">← Kraft</Link>
      <h1 className="mt-1 font-display text-2xl font-extrabold tracking-tight">{data?.exercise ?? name}</h1>
      <p className="mt-1 text-sm text-muted">{data?.muscle ? `${data.muscle} · ` : ""}e1RM, Gewicht, Tonnage & RPE im Verlauf</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {data?.status?.is_pr && (
          <span className="inline-flex items-center gap-1 rounded-full border border-good/30 bg-good/10 px-2.5 py-1 text-[11px] font-semibold text-good">
            🏆 Aktuelle Bestform
          </span>
        )}
        {data?.status && data.status.status !== "unknown" && data.status.status !== "new" && (
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${STATUS_CLS[data.status.status] ?? "border-line text-muted"}`}
            title={data.status.detail}
          >
            {STATUS_ICON[data.status.status] ?? ""} {data.status.label}
            <span className="hidden font-normal opacity-80 sm:inline">· {data.status.detail}</span>
          </span>
        )}
      </div>
    </header>
  );

  const periodToggle = (
    <div className="mb-4 inline-flex flex-wrap gap-1 rounded-lg border border-line bg-surface p-1">
      {PERIODS.map(([key, lbl]) => (
        <button
          key={key} type="button" onClick={() => setPeriod(key)}
          className={"rounded-md px-3 py-1.5 text-xs font-semibold transition-colors " +
            (period === key ? "bg-accent text-white" : "text-muted hover:text-ink")}
        >
          {lbl}
        </button>
      ))}
    </div>
  );

  if (err) return (<>{header}<ApiError error={err} /></>);

  const stats = data?.stats;
  const deltas = data?.deltas;
  const series = data?.series ?? [];
  const hasRpe = series.some((s) => s.rpe != null);

  return (
    <>
      {header}
      {periodToggle}

      {loading ? (
        <Loading />
      ) : !stats ? (
        <Card><p className="text-sm text-muted">Keine Sätze in diesem Zeitraum. Wähle „Gesamt" für den vollen Verlauf.</p></Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Kpi label="Bestes e1RM" sub={`am ${dm(stats.best_e1rm_date)}`} value={de0(stats.best_e1rm)} unit="kg" />
            <Kpi label="Top-Gewicht" sub={`Best-Satz ${stats.best_set}`} value={de0(stats.top_weight)} unit="kg" />
            <Kpi label="Tonnage" sub={`${de0(stats.sessions)} Sessions · ${de0(stats.sets)} Sätze`} value={de(stats.tonnage_kg / 1000, 1)} unit="t" />
            <Kpi label="RPE Ø" sub="weniger RIR = höher" value={stats.avg_rpe != null ? de(stats.avg_rpe, 1) : "–"} />
          </div>

          {deltas && (
            <Card className="mt-4">
              <CardTitle title="Entwicklung im Zeitraum" sub="erste → letzte Session" />
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Delta label="e1RM" value={`${sgn(deltas.e1rm)} kg`} kind={deltas.e1rm >= 0 ? "good" : "bad"} />
                <Delta label="Top-Gewicht" value={`${sgn(deltas.top_weight)} kg`} kind={deltas.top_weight >= 0 ? "good" : "bad"} />
                <Delta label="Tonnage/Session" value={`${sgn(deltas.tonnage, 0)} kg`} kind={deltas.tonnage >= 0 ? "good" : "bad"} />
                <Delta label="RPE" value={deltas.rpe != null ? sgn(deltas.rpe) : "–"} kind="muted" sub="höher = näher ans Limit" />
              </div>
            </Card>
          )}

          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
            <Card>
              <CardTitle title="e1RM-Verlauf" sub="geschätztes 1RM (Epley), je Session" />
              <AreaTrend values={series.map((s) => s.e1rm)} labels={series.map((s) => dm(s.date))} unit="kg" height={180} />
            </Card>
            <Card>
              <CardTitle title="Top-Gewicht je Session" sub="schwerster Arbeitssatz" />
              <AreaTrend values={series.map((s) => s.top_weight)} labels={series.map((s) => dm(s.date))} unit="kg" height={180} />
            </Card>
            <Card>
              <CardTitle title="Tonnage je Session" sub="bewegte Last (kg)" />
              <Bars data={series.map((s) => ({ label: dm(s.date), value: s.tonnage }))} unit="kg" height={180} />
            </Card>
            <Card>
              <CardTitle title="RPE-Verlauf" sub="Anstrengung · höher = weniger RIR" />
              {hasRpe ? (
                <AreaTrend values={series.map((s) => s.rpe)} labels={series.map((s) => dm(s.date))} height={180} />
              ) : (
                <p className="grid h-[180px] place-items-center text-xs text-muted">Keine RPE-Daten erfasst.</p>
              )}
            </Card>
          </div>

          <p className="mt-4 text-[11px] text-muted">
            Zeitraum {PERIODS.find(([k]) => k === period)?.[1]} · {dm(stats.first_date)} – {dm(stats.last_date)} · Ø {de(stats.avg_reps, 1)} Wdh/Satz
          </p>
        </>
      )}
    </>
  );
}
