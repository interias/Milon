"use client";

import { useState } from "react";
import { api, type StrengthRule } from "@/lib/api";

export const RULES_EVENT = "milon:strength-rules";

type Rule = Pick<StrengthRule, "key" | "min_reps" | "target_reps" | "default" | "custom">;

// Progressionsregel einer Planübung: Ziel-Wdh. (alle Sätze → schwerer) und Mindest-Wdh. (darunter → leichter).
export function RuleEditor({ rule, sets, onSaved }: { rule: Rule; sets: number | null; onSaved?: (rule: StrengthRule) => void }) {
  const [target, setTarget] = useState(String(rule.target_reps));
  const [min, setMin] = useState(String(rule.min_reps));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const t = Number(target), m = Number(min);
  const valid = Number.isInteger(t) && Number.isInteger(m) && m >= 1 && m <= t && t <= 50;
  const changed = t !== rule.target_reps || m !== rule.min_reps;

  async function run(action: () => Promise<StrengthRule>, done: string) {
    setBusy(true);
    setMessage(null);
    try {
      const saved = await action();
      setTarget(String(saved.target_reps));
      setMin(String(saved.min_reps));
      setMessage(done);
      onSaved?.(saved);
      window.dispatchEvent(new Event(RULES_EVENT));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Speichern fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  }

  const field = "w-16 rounded border border-line bg-surface-alt px-2 py-1.5 text-base tabular-nums sm:text-sm";
  return <div className="text-xs">
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1"><span className="text-muted">Ziel-Wdh.</span>
        <input type="number" inputMode="numeric" min={1} max={50} value={target} onChange={(e) => setTarget(e.target.value)} className={field} /></label>
      <label className="flex flex-col gap-1"><span className="text-muted">Mindest-Wdh.</span>
        <input type="number" inputMode="numeric" min={1} max={50} value={min} onChange={(e) => setMin(e.target.value)} className={field} /></label>
      <button type="button" disabled={!valid || !changed || busy} onClick={() => run(() => api.setStrengthRule(rule.key, m, t), "Gespeichert.")}
        className="rounded border border-accent bg-accent px-3 py-1.5 font-semibold text-white disabled:opacity-50">Speichern</button>
      {rule.custom && <button type="button" disabled={busy} onClick={() => run(() => api.resetStrengthRule(rule.key), "Auf Standard zurückgesetzt.")}
        className="rounded border border-line px-3 py-1.5 text-muted">Standard (Ziel {rule.default[1]}, min. {rule.default[0]})</button>}
    </div>
    <p className="mt-2 text-muted">
      {valid ? `${sets ? `Alle ${sets} Sätze` : "Alle Sätze"} ≥ ${t} Wdh. → nächstes Mal schwerer. Ein Satz unter ${m} Wdh. → leichter. Dazwischen bleibt das Gewicht.`
        : "Mindest-Wdh. muss zwischen 1 und der Ziel-Wdh. liegen (höchstens 50)."}
    </p>
    {message && <p className="mt-1" role="status">{message}</p>}
  </div>;
}

export const ruleChip = (rule: Pick<StrengthRule, "min_reps" | "target_reps" | "custom">) =>
  `Ziel ${rule.target_reps} · unter ${rule.min_reps} leichter${rule.custom ? " · eigene Regel" : ""}`;
