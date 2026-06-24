"use client";

import { useEffect, useState } from "react";
import { api, type NutritionSummary, type ProteinPoint, type KcalPoint, type MacroSplit } from "@/lib/api";
import { Card, CardTitle, Kpi, PageTitle, Loading, ApiError } from "@/components/ui";
import { MultiTrend } from "@/components/charts";
import { de, de0, dm, isToday } from "@/lib/format";

const MUT = "var(--color-muted)";
const ACC = "var(--color-accent)";
const ACC2 = "var(--color-accent-2)";
const GOLD = "#d9a441";

function MacroBar({ split, g }: { split: MacroSplit; g: MacroSplit }) {
  const seg: [string, number, number, string][] = [
    ["Protein", split.protein, g.protein, ACC],
    ["Kohlenhydrate", split.carb, g.carb, ACC2],
    ["Fett", split.fat, g.fat, GOLD],
  ];
  return (
    <div>
      <div className="flex h-4 w-full overflow-hidden rounded-full border border-line">
        {seg.map(([l, pct, , c]) => (
          <div key={l} style={{ width: `${pct}%`, background: c }} title={`${l}: ${pct}%`} />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
        {seg.map(([l, pct, gr, c]) => (
          <span key={l} className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: c }} />
            {l} <b className="text-ink">{pct}%</b> · {gr} g
          </span>
        ))}
      </div>
    </div>
  );
}

export default function Ernaehrung() {
  const [sum, setSum] = useState<NutritionSummary | null>(null);
  const [protein, setProtein] = useState<ProteinPoint[]>([]);
  const [kcal, setKcal] = useState<KcalPoint[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.nutritionSummary().then(setSum).catch((e) => setErr(String(e)));
    api.nutritionProtein(60).then(setProtein).catch(() => {});
    api.nutritionKcal(60).then(setKcal).catch(() => {});
  }, []);

  if (err) return (<><PageTitle title="Ernährung" /><ApiError error={err} /></>);
  if (!sum) return (<><PageTitle title="Ernährung" /><Loading /></>);
  if (!sum.days) return (<><PageTitle title="Ernährung" /><Card><p className="text-sm text-muted">Noch keine Ernährungsdaten aus FDDB.</p></Card></>);

  const target = sum.protein_target;
  const proteinHit = target != null && (sum.protein_avg7 ?? 0) >= target;
  const deficit = sum.tdee != null && sum.kcal_avg7 != null ? sum.tdee - sum.kcal_avg7 : null;

  return (
    <>
      <PageTitle title="Ernährung" sub="Kalorien & Makros aus FDDB · Protein vs. Ziel" />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Kpi
          label="Protein Ø/Tag" sub={target ? `Ziel ${de0(target)} g · ${de(sum.protein_per_kg, 1)} g/kg` : "7-Tage-Mittel"}
          value={de0(sum.protein_avg7)} unit="g"
          delta={proteinHit ? "Ziel erreicht ✓" : target ? `${de0(target - (sum.protein_avg7 ?? 0))} g unter Ziel` : undefined}
          deltaKind={proteinHit ? "good" : "bad"}
        />
        <Kpi
          label="Kalorien Ø/Tag" sub={sum.tdee ? `TDEE ~${de0(sum.tdee)} kcal` : "7-Tage-Mittel"}
          value={de0(sum.kcal_avg7)} unit="kcal"
          delta={deficit != null ? `${deficit >= 0 ? "−" : "+"}${de0(Math.abs(deficit))} kcal/Tag` : undefined}
          deltaKind={deficit != null && deficit >= 0 ? "good" : "muted"}
        />
        <Kpi label={isToday(sum.last_day) ? "Protein heute" : "Protein zuletzt"} sub={sum.last_day ? `Stand ${dm(sum.last_day)}` : ""} value={de0(sum.protein_today)} unit="g" />
        <Kpi label="Ziel-Tage" sub="Protein ≥ Ziel · 7 T" value={sum.on_target_days_7 != null ? `${sum.on_target_days_7}/7` : "–"} />
      </div>

      <Card className="mt-4">
        <CardTitle title="Makro-Verteilung" sub="Ø der letzten 7 Tage" />
        {sum.macro_split && sum.macro_g
          ? <MacroBar split={sum.macro_split} g={sum.macro_g} />
          : <p className="text-sm text-muted">–</p>}
      </Card>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <CardTitle title="Protein · 60 Tage" sub={target ? `Tageswert · 7-Tage-Ø · Ziel ${de0(target)} g (gold)` : "Tageswert · 7-Tage-Ø"} />
          <MultiTrend
            labels={protein.map((p) => dm(p.date))} unit="g" height={190} format={(n) => de0(n)}
            series={[
              { values: protein.map((p) => p.protein), label: "Tag", color: MUT },
              ...(target ? [{ values: protein.map(() => target), label: "Ziel", color: GOLD }] : []),
              { values: protein.map((p) => p.avg7), label: "7-Tage-Ø", color: ACC },
            ]}
          />
        </Card>
        <Card>
          <CardTitle title="Kalorien vs. TDEE · 60 Tage" sub={sum.tdee ? "unter der TDEE-Linie = Defizit" : "Tageswert · 7-Tage-Ø"} />
          <MultiTrend
            labels={kcal.map((p) => dm(p.date))} unit="kcal" height={190} format={(n) => de0(n)}
            series={[
              { values: kcal.map((p) => p.kcal), label: "Tag", color: MUT },
              ...(sum.tdee ? [{ values: kcal.map(() => sum.tdee as number), label: "TDEE", color: GOLD }] : []),
              { values: kcal.map((p) => p.avg7), label: "7-Tage-Ø", color: ACC },
            ]}
          />
        </Card>
      </div>
    </>
  );
}
