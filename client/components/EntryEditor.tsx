"use client";

// Editierbare Karte für einen Fortschritts-Eintrag — NEU oder BEARBEITEN (initial gesetzt):
// Datum + Notiz + bis zu 5 Ansichten (Foto wählen/ziehen, im Edit-Modus behalten/ersetzen/
// entfernen). Speichern legt an (POST) bzw. aktualisiert (PUT) und schließt die Karte.
import { useState } from "react";
import { api, mediaUrl, type ProgressEntry } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { PhotoPicker } from "@/components/PhotoPicker";

const VIEWS = [
  ["front", "Vorne"],
  ["side", "Seite"],
  ["back", "Hinten"],
  ["pose1", "Pose 1"],
  ["pose2", "Pose 2"],
] as const;

// Pool klassischer Bodybuilder-Posen — für Pose 1 & 2 werden zwei davon zufällig vorgeschlagen.
const POSE_GUIDES = [
  "front-double-biceps", "front-lat-spread", "side-chest", "side-triceps", "back-double-biceps",
  "back-lat-spread", "abs-and-thighs", "most-muscular", "hands-on-hips", "victory",
].map((n) => `/img/silhouette/poses/${n}.png`);

function pick2(arr: string[]): [string, string] {
  if (arr.length < 2) return [arr[0] ?? "", arr[0] ?? ""];
  const a = Math.floor(Math.random() * arr.length);
  let b = Math.floor(Math.random() * arr.length);
  while (b === a) b = Math.floor(Math.random() * arr.length);
  return [arr[a], arr[b]];
}

export function EntryEditor({ initial, onSaved, onCancel }: { initial?: ProgressEntry | null; onSaved: () => void; onCancel: () => void }) {
  const isEdit = !!initial;
  const [date, setDate] = useState(initial?.taken_on ?? new Date().toISOString().slice(0, 10));
  const [note, setNote] = useState(initial?.note ?? "");
  const [blobs, setBlobs] = useState<Record<string, Blob | null>>({});
  const [cleared, setCleared] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [poses, setPoses] = useState<[string, string]>(() => pick2(POSE_GUIDES));

  const guideFor = (v: string) => (v === "pose1" ? poses[0] : v === "pose2" ? poses[1] : `/img/silhouette/${v}.png`);

  function onSlot(v: (typeof VIEWS)[number][0]) {
    return (b: Blob | null) => {
      setBlobs((s) => ({ ...s, [v]: b }));
      setCleared((c) => {
        const n = new Set(c);
        if (b === null && initial?.photos[v]) n.add(v);
        else n.delete(v);
        return n;
      });
    };
  }

  // verbleibende Fotos = neu hochgeladene + behaltene bestehende
  const remaining = VIEWS.filter(([v]) => blobs[v] instanceof Blob || (initial?.photos[v] && !cleared.has(v))).length;

  async function save() {
    if (!date) { setErr("Bitte ein Datum wählen."); return; }
    if (remaining < 1) { setErr("Mindestens ein Foto."); return; }
    setSaving(true);
    setErr(null);
    try {
      const fd = new FormData();
      fd.append("taken_on", date);
      fd.append("note", note);
      for (const [v] of VIEWS) {
        const b = blobs[v];
        if (b instanceof Blob) fd.append(v, b, `${v}.jpg`);
      }
      if (isEdit) {
        if (cleared.size) fd.append("cleared", [...cleared].join(","));
        await api.progressUpdate(initial!.id, fd);
      } else {
        await api.progressCreate(fd);
      }
      onSaved();
    } catch (e) {
      setErr(String(e));
      setSaving(false);
    }
  }

  return (
    <Card className="border-accent/40">
      <CardTitle
        title={isEdit ? "Eintrag bearbeiten" : "Neuer Eintrag"}
        sub="Datum & Notiz setzen · Fotos wählen/ziehen (behalten · ersetzen · entfernen), mit Pan + Zoom auf 3:4"
      />
      <div className="mb-3 flex flex-wrap gap-3">
        <label className="text-sm">
          <span className="mb-1 block text-[11px] text-muted">Datum</span>
          <input
            type="date" value={date} onChange={(e) => setDate(e.target.value)}
            className="rounded-lg border border-line bg-surface-alt px-3 py-2 text-base text-ink sm:text-sm"
          />
        </label>
        <label className="min-w-[12rem] flex-1 text-sm">
          <span className="mb-1 block text-[11px] text-muted">Notiz</span>
          <input
            type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder="kurzer Freitext …"
            className="w-full rounded-lg border border-line bg-surface-alt px-3 py-2 text-base text-ink placeholder:text-muted focus:border-accent focus:outline-none sm:text-sm"
          />
        </label>
      </div>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-[11px] text-muted">Schablonen als Ausrichthilfe · Pose 1 &amp; 2 zufällig</span>
        <button type="button" onClick={() => setPoses(pick2(POSE_GUIDES))} className="text-[11px] font-medium text-accent hover:underline">
          🎲 andere Posen
        </button>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {VIEWS.map(([v, lbl]) => (
          <PhotoPicker
            key={v}
            label={lbl}
            guide={guideFor(v)}
            initialUrl={initial?.photos[v] ? mediaUrl(initial.photos[v]!) : undefined}
            onChange={onSlot(v)}
          />
        ))}
      </div>
      {err && <p className="mt-2 text-xs text-bad">{err}</p>}
      <div className="mt-3 flex gap-2">
        <button
          type="button" onClick={save} disabled={saving}
          className="rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
        >
          {saving ? "speichert …" : isEdit ? "Änderungen speichern" : "Eintrag speichern"}
        </button>
        <button
          type="button" onClick={onCancel} disabled={saving}
          className="rounded-lg border border-line bg-surface-alt px-4 py-2.5 text-sm font-medium text-ink hover:border-accent disabled:opacity-60"
        >
          Abbrechen
        </button>
      </div>
    </Card>
  );
}
