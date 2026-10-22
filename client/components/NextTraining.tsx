"use client";

import { useEffect, useState } from "react";
import { api, type NextTraining as Data, type PlanExercise } from "@/lib/api";
import { Card } from "@/components/ui";
import { de, dm } from "@/lib/format";

const ACTION: Record<PlanExercise["action"], [string, string]> = {
  increase: ["↑ schwerer", "border-good text-good"],
  hold: ["= halten", "border-line text-muted"],
  decrease: ["↓ leichter", "border-warn text-warn"],
  deload: ["↓ neu aufbauen", "border-warn text-warn"],
  pause: ["↓ nach Pause", "border-warn text-warn"],
  start: ["Start", "border-accent text-accent"],
  new: ["neu", "border-accent text-accent"],
};
const rir = (rpe: number | null) => rpe == null ? "" : rpe >= 10 ? "Versagen" : `${de(10 - rpe, 0)} RIR`;
const kg = (value: number | null) => value == null ? "– kg" : `${de(value, value % 1 ? 1 : 0)} kg`;

function ExerciseRow({ ex }: { ex: PlanExercise }) {
  const warmup = ex.sets.filter((set) => set.type === "warmup");
  const work = ex.sets.filter((set) => set.type === "normal");
  const [label, tone] = ACTION[ex.action];
  const delta = ex.action === "increase" && ex.last ? ex.reason.match(/\+[\d,]+ kg/)?.[0] : null;
  return <div className="py-2.5">
    <div className="flex items-baseline justify-between gap-3">
      <p className="min-w-0 truncate text-sm font-semibold">{ex.name}</p>
      <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[11px] font-semibold ${tone}`}>{delta ?? label}</span>
    </div>
    <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1 tabular-nums">
      <span className="font-display text-xl font-extrabold text-accent">{kg(ex.weight_kg)}</span>
      <span className="text-sm">{work.map((set) => set.reps).join(" / ")} Wdh.</span>
      <span className="text-xs text-muted">{work.map((set) => rir(set.rpe)).join(" · ")}</span>
    </div>
    {warmup.length > 0 && <p className="mt-0.5 text-xs text-muted">Aufwärmen {warmup.map((set) => `${kg(set.weight_kg)} × ${set.reps}`).join(", ")}</p>}
    <p className="mt-1 text-xs text-muted">{ex.reason}</p>
  </div>;
}

export function NextTraining() {
  const [data, setData] = useState<Data | null>(null);
  const [failed, setFailed] = useState(false);
  const [tab, setTab] = useState<string | null>(null);
  const [writing, setWriting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    api.strengthPlan().then((value) => { if (active) setData(value); }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, []);

  async function write() {
    setWriting(true);
    setMessage(null);
    try {
      await api.writeHevyRoutines();
      setMessage("In Hevy aktualisiert: Ordner „Milon“.");
    } catch (error) {
      setMessage(`Schreiben fehlgeschlagen${error instanceof Error ? `: ${error.message}` : "."}`);
    } finally {
      setWriting(false);
    }
  }

  if (!data) return <Card><h2 className="text-sm font-semibold">Nächstes Training</h2><p className="mt-2 text-sm text-muted" role="status">{failed ? "Plan konnte nicht geladen werden." : "Wird geladen …"}</p></Card>;
  const active = data.plans.find((plan) => plan.key === (tab ?? data.next ?? "ok")) ?? data.plans[0];
  // Übungen in Blöcke fassen: Supersatz-Partner stehen zusammen.
  const blocks: PlanExercise[][] = [];
  for (const ex of active.exercises) {
    const prev = blocks.at(-1);
    if (ex.superset != null && prev?.[0].superset === ex.superset) prev.push(ex);
    else blocks.push([ex]);
  }

  return <Card>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="text-sm font-semibold">Nächstes Training</h2>
        <p className="mt-1 text-xs text-muted">Woche ab {dm(data.week_start)}: {data.plans.map((plan) => `${plan.name} ${plan.done}/${plan.per_week}`).join(" · ")}</p>
      </div>
      <div className="flex gap-1" role="tablist" aria-label="Trainingsplan">
        {data.plans.map((plan) => <button key={plan.key} type="button" role="tab" aria-selected={active.key === plan.key} onClick={() => setTab(plan.key)}
          className={`rounded border px-3 py-1.5 text-xs font-semibold ${active.key === plan.key ? "border-accent bg-accent text-white" : "border-line text-muted"}`}>
          {plan.name}{plan.key === data.next && <span className="ml-1.5 rounded-sm bg-white/90 px-1 text-[10px] text-accent">dran</span>}
        </button>)}
      </div>
    </div>
    <p className="mt-3 text-xs text-muted">~{active.duration_min} min{active.last_date ? ` · zuletzt ${dm(active.last_date)}` : ""} · Sätze 1–2 mit 2 Wdh. im Tank, letzter Satz 1 (Isolation: bis zum Versagen)</p>
    <div className="mt-2 divide-y divide-line">
      {blocks.map((block) => block.length > 1
        ? <div key={block[0].key} className="py-1">
          <p className="pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-accent">Supersatz · {block[0].sets.filter((set) => set.type === "normal").length} Runden</p>
          <div className="border-l-2 border-accent-2 pl-3">{block.map((ex) => <ExerciseRow key={ex.key} ex={ex} />)}</div>
        </div>
        : <ExerciseRow key={block[0].key} ex={block[0]} />)}
    </div>
    <div className="mt-3 flex flex-wrap items-center gap-3">
      <button type="button" onClick={write} disabled={writing} className="rounded border border-line px-3 py-2 text-sm disabled:opacity-60">{writing ? "Schreibe …" : "Jetzt nach Hevy schreiben"}</button>
      <p className="text-xs text-muted" role="status">{message ?? "Wird nach jedem Hevy-Sync automatisch als Routine „Milon OK/UK“ gesetzt."}</p>
    </div>
  </Card>;
}
