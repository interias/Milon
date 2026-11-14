"use client";

import { useEffect, useState } from "react";
import { api, type MacroPoint, type NutritionFoods, type NutritionFood, type NutritionMeals, type NutritionToday } from "@/lib/api";
import { Card } from "@/components/ui";
import { RunTrendChart } from "@/components/RunTrendChart";
import { de0, dm } from "@/lib/format";

const COLOR = { kcal: "var(--color-ink)", protein: "#00917d", carb: "#ab7f00", fat: "#2a78d6" } as const;
const LABEL = { kcal: "Kalorien", protein: "Protein", carb: "Kohlenhydrate", fat: "Fett" } as const;
type Macro = keyof typeof LABEL;
const MACROS: Macro[] = ["kcal", "protein", "carb", "fat"];
const SOURCE = { biss: "BISS", fddb: "FDDB" } as const;

function Bar({ share, color, over = false }: { share: number; color: string; over?: boolean }) {
  return <div className="h-2.5 overflow-hidden rounded-full bg-line">
    <div className="h-full rounded-full" style={{ width: `${Math.min(1, Math.max(0, share)) * 100}%`, background: over ? "var(--color-bad)" : color }} />
  </div>;
}

/** Makros des laufenden Tages gegen die Ziele aus dem Tagebuch; fragt jede Minute neu. */
export function MacrosToday() {
  const [data, setData] = useState<NutritionToday | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    const load = () => api.nutritionToday().then((value) => { if (active) { setData(value); setError(false); } }).catch(() => { if (active) setError(true); });
    load();
    const timer = setInterval(load, 60_000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  if (!data) return <Card><h2 className="text-sm font-semibold">Heute gegessen</h2><p className="mt-3 text-xs text-muted" role="status">{error ? "Daten konnten nicht geladen werden." : "Wird geladen …"}</p></Card>;
  return <Card>
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="text-sm font-semibold">Heute gegessen · {dm(data.date)}</h2>
      <p className="text-xs text-muted">{data.entries ? `${data.entries} Einträge · zuletzt ${data.last_entry} Uhr` : "noch nichts eingetragen"} · {SOURCE[data.source]}</p>
    </div>
    <div className="mt-4 grid gap-x-8 gap-y-4 sm:grid-cols-2 xl:grid-cols-4">
      {MACROS.map((key) => {
        const value = data[key] ?? 0, goal = data.goal?.[key] ?? null, unit = key === "kcal" ? "kcal" : "g";
        const left = goal != null ? goal - value : null;
        return <div key={key} className="min-w-0">
          <p className="text-xs text-muted">{LABEL[key]}{key !== "kcal" && data.split ? ` · ${data.split[key]} % der kcal` : ""}</p>
          <p className="mt-1"><strong className="font-display text-2xl">{de0(value)}</strong> <span className="text-xs text-muted">{goal != null ? `/ ${de0(goal)} ${unit}` : unit}</span></p>
          {goal != null && <div className="mt-2" role="img" aria-label={`${de0(value)} von ${de0(goal)} ${unit}`}><Bar share={value / goal} color={COLOR[key]} over={key !== "protein" && value > goal * 1.05} /></div>}
          <p className="mt-1.5 text-xs text-muted">
            {left != null ? (left >= 0 ? `noch ${de0(left)} ${unit}` : `${de0(-left)} ${unit} drüber`) : "kein Ziel"}
            {data.avg7?.[key] != null ? ` · Ø 7 T ${de0(data.avg7[key])}` : ""}
          </p>
        </div>;
      })}
    </div>
    <p className="mt-4 text-xs text-muted">
      Ziele aus dem Tagebuch{data.protein_target != null ? ` · Milon-Referenz für Protein ${de0(data.protein_target)} g` : ""}
      {data.source === "biss" ? " · der Tag endet wie in BISS um 04:00 Uhr" : ""}
      {data.avg7_days ? ` · Ø aus ${data.avg7_days} erfassten Tagen davor` : ""}
    </p>
  </Card>;
}

/** Kohlenhydrate und Fett als 7-Tage-Mittel, gebaut wie die Protein-Karte. */
export function MacroTrend({ macro }: { macro: "carb" | "fat" }) {
  const [points, setPoints] = useState<MacroPoint[] | null>(null);
  const [error, setError] = useState(false);
  const [raw, setRaw] = useState(false);
  useEffect(() => { api.nutritionMacro(macro, 60).then(setPoints).catch(() => setError(true)); }, [macro]);
  return <Card className="min-w-0">
    <h2 className="text-sm font-semibold">{LABEL[macro]} · Verlauf</h2>
    {points ? <RunTrendChart label={`${LABEL[macro]} · 7-Tage-Mittel`} unit="g" showPoints={false}
      points={points.map((point) => ({ date: point.date, value: point.avg7, detail: `${point.days7} erfasste Tage im 7-Tage-Fenster` }))}
      observations={raw ? points.map((point) => ({ date: point.date, value: point.value, detail: "Erfasste Tagesmenge" })) : []} />
      : <p className="mt-4 text-xs text-muted" role="status">{error ? "Daten konnten nicht geladen werden." : "Wird geladen …"}</p>}
    <div className="mt-2 flex flex-wrap justify-between gap-2 text-xs text-muted"><span>Bis zu 60 Tage · 7-Tage-Mittel</span>
      <label className="flex items-center gap-2"><input type="checkbox" checked={raw} onChange={(event) => setRaw(event.target.checked)} />Tageswerte</label></div>
  </Card>;
}

const TABS = [["favorites", "Am häufigsten"], ["protein", "Protein"], ["carb", "Kohlenhydrate"], ["fat", "Fett"], ["kcal", "Kalorien"]] as const;
type Tab = typeof TABS[number][0];
const PERIODS = [[7, "7 T"], [30, "30 T"], [90, "90 T"]] as const;

/** Lieblingslebensmittel und die größten Quellen je Makro. */
export function FoodInsights() {
  const [days, setDays] = useState<number>(30);
  const [tab, setTab] = useState<Tab>("favorites");
  const [data, setData] = useState<NutritionFoods | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => { let active = true; api.nutritionFoods(days).then((value) => { if (active) setData(value); }).catch(() => { if (active) setError(true); }); return () => { active = false; }; }, [days]);
  const rows: NutritionFood[] = data?.[tab] ?? [];
  const most = Math.max(1, ...rows.map((row) => tab === "favorites" ? row.count : row.share ?? 0));
  const chip = (on: boolean) => `rounded border px-2.5 py-1 text-xs ${on ? "border-accent bg-accent text-white" : "border-line"}`;
  return <Card className="min-w-0">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-sm font-semibold">Lieblingslebensmittel & Quellen</h2>
      <div className="flex gap-1">{PERIODS.map(([value, label]) => <button key={value} type="button" aria-pressed={days === value} onClick={() => setDays(value)} className={chip(days === value)}>{label}</button>)}</div>
    </div>
    <div className="mt-3 flex flex-wrap gap-1">{TABS.map(([key, label]) => <button key={key} type="button" aria-pressed={tab === key} onClick={() => setTab(key)} className={chip(tab === key)}>{label}</button>)}</div>
    {!data ? <p className="mt-4 text-xs text-muted" role="status">{error ? "Daten konnten nicht geladen werden." : "Wird geladen …"}</p>
      : rows.length === 0 ? <p className="mt-4 text-xs text-muted">Noch keine Einträge in diesem Zeitraum.</p>
      : <ol className="mt-4 space-y-3">{rows.map((row) => {
        const value = tab === "favorites" ? `${row.count}×` : `${de0(row[tab])} ${tab === "kcal" ? "kcal" : "g"}`;
        return <li key={row.name} className="min-w-0">
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 truncate" title={row.name}>{row.name}{row.brand ? <span className="text-muted"> · {row.brand}</span> : null}</span>
            <span className="shrink-0 font-semibold tabular-nums">{value}{tab !== "favorites" && row.share != null ? <span className="font-normal text-muted"> · {row.share} %</span> : null}</span>
          </div>
          <div className="mt-1"><Bar share={(tab === "favorites" ? row.count : row.share ?? 0) / most} color={tab === "favorites" ? "var(--color-accent)" : COLOR[tab]} /></div>
          <p className="mt-1 text-xs text-muted">{tab === "favorites" ? `an ${row.days} Tagen · ${de0(row.kcal)} kcal · ${de0(row.protein)} g Protein gesamt` : `${row.count}× an ${row.days} Tagen`}</p>
        </li>;
      })}</ol>}
    {data && rows.length > 0 && <p className="mt-4 text-xs text-muted">{data.recorded_days} erfasste Tage{tab !== "favorites" ? " · Anteil an der Gesamtmenge im Zeitraum" : ""} · Namen aus FDDB und BISS werden nicht zusammengeführt.</p>}
  </Card>;
}

/** Ø je Mahlzeit und erfasstem Tag — vor allem: wie verteilt sich das Protein? */
export function MealSplit() {
  const [data, setData] = useState<NutritionMeals | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => { api.nutritionMeals(30).then(setData).catch(() => setError(true)); }, []);
  return <Card className="min-w-0">
    <h2 className="text-sm font-semibold">Mahlzeiten · Ø je Tag</h2>
    {!data ? <p className="mt-4 text-xs text-muted" role="status">{error ? "Daten konnten nicht geladen werden." : "Wird geladen …"}</p>
      : data.meals.length === 0 ? <p className="mt-4 text-xs text-muted">Mahlzeiten kennt nur BISS. Sobald dort Einträge liegen, erscheint hier die Verteilung.</p>
      : <>
        <ul className="mt-4 space-y-3">{data.meals.map((meal) => <li key={meal.meal}>
          <div className="flex items-baseline justify-between gap-3 text-sm"><span>{meal.label}</span>
            <span className="font-semibold tabular-nums">{de0(meal.protein)} g Protein<span className="font-normal text-muted"> · {meal.protein_share ?? 0} %</span></span></div>
          <div className="mt-1"><Bar share={(meal.protein_share ?? 0) / 100} color={COLOR.protein} /></div>
          <p className="mt-1 text-xs text-muted">{de0(meal.kcal)} kcal · {de0(meal.carb)} g KH · {de0(meal.fat)} g Fett</p>
        </li>)}</ul>
        <p className="mt-4 text-xs text-muted">{data.recorded_days} {data.recorded_days === 1 ? "erfasster Tag" : "erfasste Tage"} aus BISS, letzte 30 Tage · Balken = Anteil am Tages-Protein. BISS ordnet die Mahlzeit nach der Uhrzeit zu.</p>
      </>}
  </Card>;
}
