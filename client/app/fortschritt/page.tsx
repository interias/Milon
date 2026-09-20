"use client";

import { useEffect, useState } from "react";
import { api, mediaUrl, type ProgressEntry } from "@/lib/api";
import { Card, PageTitle, Loading, ApiError } from "@/components/ui";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
import { EntryEditor } from "@/components/EntryEditor";

const VIEWS = [
  ["front", "Vorne"],
  ["side", "Seite"],
  ["back", "Hinten"],
  ["pose1", "Pose 1"],
  ["pose2", "Pose 2"],
] as const;

const entryDate = (date: string) => new Date(`${date}T12:00:00`).toLocaleDateString("de-DE", { day: "2-digit", month: "long", year: "numeric" });

function PhotoViewer({ entry, initial, onClose }: { entry: ProgressEntry; initial: string; onClose: () => void }) {
  const photos = VIEWS.filter(([view]) => entry.photos[view]);
  const [index, setIndex] = useState(() => Math.max(0, photos.findIndex(([view]) => view === initial)));
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      setIndex((value) => (value + (event.key === "ArrowRight" ? 1 : -1) + photos.length) % photos.length);
      setFailed(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [photos.length]);
  const [view, label] = photos[index];
  const move = (offset: number) => { setIndex((value) => (value + offset + photos.length) % photos.length); setFailed(false); };
  return <RunAnalysisDialog title={entryDate(entry.taken_on)} onClose={onClose}>
    <div className="flex items-center justify-between gap-2 text-sm">
      <button type="button" aria-label="Vorheriges Foto" disabled={photos.length < 2} onClick={() => move(-1)} className="rounded border border-line px-3 py-2 disabled:opacity-40">←</button>
      <p aria-live="polite">{label} · {index + 1}/{photos.length}</p>
      <button type="button" aria-label="Nächstes Foto" disabled={photos.length < 2} onClick={() => move(1)} className="rounded border border-line px-3 py-2 disabled:opacity-40">→</button>
    </div>
    {failed ? <p role="alert" className="py-8 text-center text-sm text-muted">Foto konnte nicht geladen werden.</p> :
      // eslint-disable-next-line @next/next/no-img-element
      <img key={view} src={mediaUrl(entry.photos[view]!)} alt={`${label} · ${entryDate(entry.taken_on)}`} onError={() => setFailed(true)} className="mt-3 max-h-[60dvh] w-full rounded object-contain" />}
    {entry.note && <p className="mt-3 whitespace-pre-wrap break-words text-sm text-muted">{entry.note}</p>}
  </RunAnalysisDialog>;
}

export default function Fortschritt() {
  const [entries, setEntries] = useState<ProgressEntry[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // null = kein Editor offen · {} = neuer Eintrag · {entry} = bearbeiten
  const [editor, setEditor] = useState<{ entry?: ProgressEntry } | null>(null);

  const [viewer, setViewer] = useState<{ entry: ProgressEntry; view: string } | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);

  useEffect(() => {
    api.progressList().then(setEntries).catch((e) => setErr(String(e)));
  }, []);

  async function refresh() {
    try { setEntries(await api.progressList()); }
    catch { setActionErr("Die Einträge konnten nicht neu geladen werden. Bitte lade die Seite erneut."); }
  }

  async function remove(entry: ProgressEntry) {
    if (deleting !== null || !window.confirm(`Eintrag vom ${entryDate(entry.taken_on)} mit allen Fotos endgültig löschen?`)) return;
    setDeleting(entry.id);
    setActionErr(null);
    try {
      await api.progressDelete(entry.id);
      setEntries((items) => items ? items.filter((item) => item.id !== entry.id) : items);
    } catch { setActionErr("Löschen fehlgeschlagen. Der Eintrag bleibt erhalten. Bitte versuche es erneut."); }
    finally { setDeleting(null); }
  }

  if (err) return (<><PageTitle title="Fortschritt" /><ApiError error={err} /></>);
  if (!entries) return (<><PageTitle title="Fortschritt" /><Loading /></>);

  const sorted = [...entries].sort((a, b) => b.taken_on.localeCompare(a.taken_on));
  const close = () => setEditor(null);
  const saved = async () => { setEditor(null); await refresh(); };

  return (
    <>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <PageTitle title="Fortschritt" sub="Deine Fotos im Zeitverlauf" />
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

      {actionErr && <p role="alert" className="mb-4 rounded border border-bad/30 bg-bad/5 p-3 text-sm text-bad">{actionErr}</p>}
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
                      {entryDate(e.taken_on)}
                    </div>
                    {e.note && <div className="line-clamp-2 break-words text-sm text-muted">{e.note}</div>}
                  </div>
                  {!editor && (
                    <details className="relative shrink-0">
                      <summary aria-label={`Aktionen für ${entryDate(e.taken_on)}`} className="cursor-pointer list-none rounded border border-line px-3 py-1 text-lg">⋯</summary>
                      <div className="absolute right-0 z-10 mt-1 min-w-36 rounded border border-line bg-surface p-1 shadow-lg">
                        <button type="button" disabled={deleting !== null} onClick={() => setEditor({ entry: e })} className="block w-full px-3 py-2 text-left text-sm hover:bg-surface-alt disabled:opacity-50">Bearbeiten</button>
                        <button type="button" disabled={deleting !== null} onClick={() => remove(e)} className="block w-full px-3 py-2 text-left text-sm text-bad hover:bg-surface-alt disabled:opacity-50">{deleting === e.id ? "Löscht …" : "Löschen"}</button>
                      </div>
                    </details>
                  )}
                </div>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                  {VIEWS.filter(([view]) => e.photos[view]).map(([view, label]) => (
                    <button type="button" key={view} onClick={() => setViewer({ entry: e, view })} aria-label={`${label} vom ${entryDate(e.taken_on)} vergrößern`} className="block min-w-0 rounded-lg text-left focus-visible:outline-accent">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={mediaUrl(e.photos[view]!)} alt={label} loading="lazy" className="aspect-[3/4] w-full rounded-lg object-cover" />
                      <span className="mt-1 block text-center text-xs text-muted">{label}</span>
                    </button>
                  ))}
                </div>
              </Card>
            )
          )
        )}
      </div>
      {viewer && <PhotoViewer entry={viewer.entry} initial={viewer.view} onClose={() => setViewer(null)} />}
    </>
  );
}
