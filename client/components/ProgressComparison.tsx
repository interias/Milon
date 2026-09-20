"use client";

import { useRef, useState, type PointerEvent } from "react";
import { mediaUrl, type ProgressEntry } from "@/lib/api";
import { Card } from "@/components/ui";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";

const VIEWS = [["front", "Vorne"], ["side", "Seite"], ["back", "Hinten"], ["pose1", "Pose 1"], ["pose2", "Pose 2"]] as const;
type Photo = { key: string; url: string; date: string; label: string };
type Alignment = { zoom: number; x: number; y: number };
const initialAlignment = (): Alignment => ({ zoom: 1, x: 0, y: 0 });
const dateLabel = (date: string) => new Date(`${date}T12:00:00`).toLocaleDateString("de-DE");
const buttonClass = "rounded border border-line px-3 py-2 text-sm disabled:opacity-40";

function AlignedPhoto({ photo, alignment, onChange, editable }: { photo: Photo; alignment: Alignment; onChange: (value: Alignment) => void; editable: boolean }) {
  const drag = useRef<{ x: number; y: number; start: Alignment } | null>(null);
  const [failed, setFailed] = useState(false);
  function move(event: PointerEvent<HTMLDivElement>) {
    if (!drag.current) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    onChange({ ...alignment,
      x: Math.max(-50, Math.min(50, drag.current.start.x + (event.clientX - drag.current.x) / bounds.width * 100)),
      y: Math.max(-50, Math.min(50, drag.current.start.y + (event.clientY - drag.current.y) / bounds.height * 100)),
    });
  }
  return <div className={`relative h-full w-full overflow-hidden bg-surface-alt ${editable ? "touch-none cursor-move" : ""}`}
    onPointerDown={(event) => { if (!editable) return; event.currentTarget.setPointerCapture(event.pointerId); drag.current = { x: event.clientX, y: event.clientY, start: alignment }; }}
    onPointerMove={move} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
    {failed ? <p role="alert" className="p-3 text-sm">Foto nicht verfügbar.</p> :
      // eslint-disable-next-line @next/next/no-img-element
      <img src={photo.url} alt={`${photo.label} · ${dateLabel(photo.date)}`} draggable={false} onError={() => setFailed(true)} className="h-full w-full select-none object-contain" style={{ transform: `translate(${alignment.x}%, ${alignment.y}%) scale(${alignment.zoom})` }} />}
  </div>;
}

function ComparisonPair({ photos }: { photos: [Photo, Photo] }) {
  const [alignments, setAlignments] = useState<[Alignment, Alignment]>([initialAlignment(), initialAlignment()]);
  const [adjust, setAdjust] = useState(false);
  const [slider, setSlider] = useState(false);
  const [split, setSplit] = useState(50);
  const [expanded, setExpanded] = useState(false);
  const update = (index: number, value: Alignment) => setAlignments((current) => current.map((item, i) => i === index ? value : item) as [Alignment, Alignment]);
  const photo = (index: number, editable: boolean) => <AlignedPhoto key={photos[index].key} photo={photos[index]} alignment={alignments[index]} onChange={(value) => update(index, value)} editable={editable} />;
  const content = <>
    <div className="mb-3 flex flex-wrap gap-2">
      <button type="button" aria-pressed={!slider} onClick={() => setSlider(false)} className={buttonClass}>Nebeneinander</button>
      <button type="button" aria-pressed={slider} onClick={() => { setSlider(true); setAdjust(false); }} className={buttonClass}>Schieberegler</button>
      <button type="button" aria-pressed={adjust} onClick={() => { setAdjust(!adjust); setSlider(false); }} className={buttonClass}>Ausrichten</button>
      {!expanded && <button type="button" onClick={() => setExpanded(true)} className={buttonClass}>Vergrößern</button>}
    </div>
    <div className="mb-2 grid grid-cols-2 gap-3 text-center text-xs text-muted">
      {photos.map((item, index) => <p key={index}>{index === 0 ? "A" : "B"} · {dateLabel(item.date)} · {item.label}</p>)}
    </div>
    {slider ? <div className="mx-auto max-w-sm">
      <div className="relative aspect-[3/4] overflow-hidden rounded">
        <div className="absolute inset-0">{photo(1, false)}</div>
        <div className="absolute inset-0" style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}>{photo(0, false)}</div>
        <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-white shadow" style={{ left: `${split}%` }} />
      </div>
      <label className="mt-3 block text-xs text-muted">Bildanteil A / B
        <input aria-label="Bildanteil A / B" type="range" min="0" max="100" value={split} onChange={(event) => setSplit(Number(event.target.value))} className="mt-2 w-full" />
      </label>
    </div> : <div className={`mx-auto grid ${expanded ? "max-w-none" : "max-w-3xl"} grid-cols-2 gap-3`}>
      {photos.map((item, index) => <div key={item.key + index} className="aspect-[3/4] min-w-0 overflow-hidden rounded">{photo(index, adjust)}</div>)}
    </div>}
    {adjust && <>
      <p className="mt-3 text-xs text-muted">Bilder ziehen oder Regler nutzen. Nur die Vergleichsansicht wird verändert.</p>
      <div className="mt-3 grid grid-cols-2 gap-4">{alignments.map((alignment, index) => <fieldset key={index} className="min-w-0 space-y-2">
        <legend className="text-sm font-semibold">Bild {index === 0 ? "A" : "B"}</legend>
        {([['zoom', 'Zoom', 1, 3, 0.05], ['x', 'Horizontal', -50, 50, 1], ['y', 'Vertikal', -50, 50, 1]] as const).map(([key, label, min, max, step]) => <label key={key} className="block text-xs text-muted">{label}
          <input aria-label={`${label} Bild ${index === 0 ? "A" : "B"}`} type="range" min={min} max={max} step={step} value={alignment[key]} onChange={(event) => update(index, { ...alignment, [key]: Number(event.target.value) })} className="block w-full" />
        </label>)}
        <button type="button" onClick={() => update(index, initialAlignment())} className={buttonClass}>Zurücksetzen</button>
      </fieldset>)}</div>
    </>}
  </>;
  return expanded ? <><button type="button" onClick={() => setExpanded(false)} className={buttonClass}>Vergleich geöffnet</button><RunAnalysisDialog wide title="Fotovergleich" onClose={() => setExpanded(false)}>{content}</RunAnalysisDialog></> : content;
}

export function ProgressComparison({ entries }: { entries: ProgressEntry[] }) {
  const [view, setView] = useState("front");
  const [selection, setSelection] = useState<[string, string]>(["", ""]);
  const photos: Photo[] = [...entries].sort((a, b) => a.taken_on.localeCompare(b.taken_on) || a.id - b.id).flatMap((entry) => VIEWS
    .filter(([key]) => entry.photos[key] && (view === "manual" || key === view))
    .map(([key, label]) => ({ key: `${entry.id}:${key}:${entry.photos[key]}`, url: mediaUrl(entry.photos[key]!), date: entry.taken_on, label })));
  const manual = view === "manual";
  const a = photos.find((photo) => photo.key === selection[0]) ?? (manual ? undefined : photos[0]);
  const b = photos.find((photo) => photo.key === selection[1]) ?? (manual ? undefined : photos.length > 1 ? photos[photos.length - 1] : undefined);
  return <Card className="mb-6">
    <h2 className="text-base font-semibold">Direkter Vergleich</h2>
    <div className="my-3 flex flex-wrap gap-2">{[["front", "Vorne"], ["side", "Seite"], ["back", "Hinten"], ["manual", "Manuelle Auswahl / Posen"]].map(([key, label]) =>
      <button key={key} type="button" aria-pressed={view === key} onClick={() => { setView(key); setSelection(["", ""]); }} className={`${buttonClass} ${view === key ? "bg-accent text-white" : ""}`}>{label}</button>)}</div>
    <div className="mb-4 grid grid-cols-2 gap-3">{[a, b].map((selected, index) => <label key={index} className="min-w-0 text-xs text-muted">Bild {index === 0 ? "A" : "B"}
      <select aria-label={`Auswahl Bild ${index === 0 ? "A" : "B"}`} value={selected?.key ?? ""} onChange={(event) => setSelection((current) => current.map((value, i) => i === index ? event.target.value : value) as [string, string])} className="mt-1 w-full rounded border border-line bg-surface p-2 text-base text-ink sm:text-sm">
        <option value="" disabled>Foto auswählen</option>
        {photos.map((photo) => <option key={photo.key} value={photo.key}>{dateLabel(photo.date)}{manual ? ` · ${photo.label}` : ""}</option>)}
      </select>
    </label>)}</div>
    {a && b && a.key !== b.key ? <ComparisonPair key={`${a.key}|${b.key}`} photos={[a, b]} /> : <p className="py-6 text-sm text-muted">{manual ? "Wähle zwei Fotos mit vergleichbarer Pose aus." : photos.length < 2 ? "Für diese Perspektive sind noch keine zwei Fotos vorhanden." : "Wähle zwei unterschiedliche Fotos aus."}</p>}
  </Card>;
}
