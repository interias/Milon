"use client";

import { useEffect, useState } from "react";
import { api, type Egym } from "@/lib/api";
import { Card } from "@/components/ui";
import { dm } from "@/lib/format";

// eGym als Pauschale: ein Knopf für heute, vergessene Tage lassen sich nachtragen.
export function EgymCard() {
  const [data, setData] = useState<Egym | null>(null);
  const [day, setDay] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    api.egym().then((value) => { if (active) setData(value); }).catch(() => { if (active) setError("Daten konnten nicht geladen werden."); });
    return () => { active = false; };
  }, []);
  const run = (call: Promise<Egym>) => {
    setBusy(true);
    setError(null);
    call.then(setData).catch((e: Error) => setError(e.message || "Das hat nicht geklappt.")).finally(() => setBusy(false));
  };

  return <Card>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 className="text-sm font-semibold">eGym</h2>
        <p className="mt-1 text-xs text-muted">{data ? `Pauschal je Training: ${data.minutes} min · ${data.kcal} kcal · bisher ${data.total}` : "Wird geladen …"}</p>
      </div>
      {data && (data.done_today
        ? <div className="flex items-center gap-3 text-sm"><span className="font-semibold text-good">✓ Heute eingetragen</span><button type="button" disabled={busy} className="text-xs text-muted underline" onClick={() => run(api.egymRemove(data.today))}>Rückgängig</button></div>
        : <button type="button" disabled={busy} className="rounded bg-accent px-4 py-2 text-sm font-semibold text-white disabled:opacity-60" onClick={() => run(api.egymAdd())}>Heute eGym gemacht</button>)}
    </div>
    {data && <details className="mt-3 text-xs text-muted">
      <summary className="cursor-pointer">Tag nachtragen oder entfernen</summary>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input type="date" aria-label="Tag des eGym-Trainings" value={day} max={data.today} onChange={(e) => setDay(e.target.value)} className="rounded border border-line bg-surface px-2 py-1.5 text-base text-ink sm:text-sm" />
        <button type="button" disabled={busy || !day} className="rounded border border-line px-3 py-2 text-sm disabled:opacity-60" onClick={() => { run(api.egymAdd(day)); setDay(""); }}>Eintragen</button>
      </div>
      {data.days.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">
        {data.days.map((d) => <button key={d} type="button" disabled={busy} aria-label={`Eintrag vom ${dm(d)} entfernen`} className="rounded border border-line px-2 py-1 tabular-nums" onClick={() => run(api.egymRemove(d))}>{dm(d)} ×</button>)}
      </div>}
    </details>}
    {error && <p className="mt-2 text-xs text-bad" role="alert">{error}</p>}
  </Card>;
}
