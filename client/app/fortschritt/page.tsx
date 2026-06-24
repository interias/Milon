"use client";

import { useEffect, useState } from "react";
import { api, mediaUrl, type ProgressEntry } from "@/lib/api";
import { Card, PageTitle, Loading, ApiError } from "@/components/ui";
import { EntryEditor } from "@/components/EntryEditor";

const VIEWS = [
  ["front", "Vorne"],
  ["side", "Seite"],
  ["back", "Hinten"],
  ["pose1", "Pose 1"],
  ["pose2", "Pose 2"],
] as const;

export default function Fortschritt() {
  const [entries, setEntries] = useState<ProgressEntry[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // null = kein Editor offen · {} = neuer Eintrag · {entry} = bearbeiten
  const [editor, setEditor] = useState<{ entry?: ProgressEntry } | null>(null);

  useEffect(() => {
    api.progressList().then(setEntries).catch((e) => setErr(String(e)));
  }, []);

  async function refresh() {
    setEntries(await api.progressList().catch(() => entries));
  }

  async function remove(id: number) {
    await api.progressDelete(id).catch(() => {});
    setEntries((es) => (es ? es.filter((e) => e.id !== id) : es));
  }

  if (err) return (<><PageTitle title="Fortschritt" /><ApiError error={err} /></>);
  if (!entries) return (<><PageTitle title="Fortschritt" /><Loading /></>);

  const sorted = [...entries].sort((a, b) => b.taken_on.localeCompare(a.taken_on));
  const close = () => setEditor(null);
  const saved = async () => { setEditor(null); await refresh(); };

  return (
    <>
      <div className="flex items-start justify-between gap-3">
        <PageTitle title="Fortschritt" sub="Optik-Timeline · vorne / seite / hinten + Posen" />
        {!editor && (
          <button
            type="button" onClick={() => setEditor({})}
            className="mt-1 shrink-0 rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white hover:brightness-110"
          >
            + Neuer Eintrag
          </button>
        )}
      </div>

      {editor && !editor.entry && (
        <div className="mb-6">
          <EntryEditor onSaved={saved} onCancel={close} />
        </div>
      )}

      <div className="space-y-4">
        {sorted.length === 0 ? (
          !editor && (
            <div className="grid place-items-center py-8 text-center">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/img/empty.png" alt="" className="h-28 w-28 opacity-80" />
              <p className="mt-2 text-sm text-muted">Noch keine Einträge — leg oben mit „+ Neuer Eintrag" den ersten an.</p>
            </div>
          )
        ) : (
          sorted.map((e) =>
            editor?.entry?.id === e.id ? (
              <EntryEditor key={e.id} initial={e} onSaved={saved} onCancel={close} />
            ) : (
              <Card key={e.id}>
                <div className="mb-2 flex items-start justify-between gap-3">
                  <div>
                    <div className="font-display text-sm font-bold">
                      {new Date(e.taken_on).toLocaleDateString("de-DE", { day: "2-digit", month: "long", year: "numeric" })}
                    </div>
                    {e.note && <div className="text-sm text-muted">{e.note}</div>}
                  </div>
                  {!editor && (
                    <div className="-mr-2 -mt-1 flex shrink-0 items-center gap-1">
                      <button type="button" onClick={() => setEditor({ entry: e })} className="p-2 text-[11px] font-medium text-accent hover:underline">
                        bearbeiten
                      </button>
                      <button type="button" onClick={() => remove(e.id)} className="p-2 text-[11px] text-muted hover:text-bad">
                        löschen
                      </button>
                    </div>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                  {VIEWS.map(([v, lbl]) => {
                    const fn = e.photos[v];
                    return fn ? (
                      <a key={v} href={mediaUrl(fn)} target="_blank" rel="noreferrer" className="block">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={mediaUrl(fn)} alt={lbl} className="aspect-[3/4] w-full rounded-lg object-cover" />
                        <div className="mt-0.5 text-center text-[10px] text-muted">{lbl}</div>
                      </a>
                    ) : (
                      <div key={v} className="grid aspect-[3/4] place-items-center rounded-lg border border-dashed border-line text-[10px] text-muted/50">
                        {lbl}
                      </div>
                    );
                  })}
                </div>
              </Card>
            )
          )
        )}
      </div>
    </>
  );
}
