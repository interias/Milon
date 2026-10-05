"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { monthLabel, monthlyRecap, type MonthlyRecapData } from "@/lib/overview-history";
import { buildMonthlySvg } from "@/lib/monthly-recap";
import styles from "./MonthlyRecap.module.css";

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob), link = document.createElement("a");
  link.href = url; link.download = name; document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export function MonthlyRecap({ months, selectedMonth }: { months: string[]; selectedMonth: string }) {
  const [open, setOpen] = useState(false), [month, setMonth] = useState(selectedMonth);
  const [data, setData] = useState<MonthlyRecapData | null>(null), [error, setError] = useState("");
  const [illustration, setIllustration] = useState(""), [weight, setWeight] = useState(false), [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null), trigger = useRef<HTMLButtonElement>(null), title = useId();
  useEffect(() => {
    if (!open) return;
    dialog.current?.showModal();
    return () => { dialog.current?.close(); trigger.current?.focus(); };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setData(null); setError(""); setWeight(false);
    monthlyRecap(month, controller.signal).then(value => { if (!controller.signal.aborted) setData(value); })
      .catch(() => { if (!controller.signal.aborted) setError("Der Monatsrückblick konnte nicht geladen werden."); });
    return () => controller.abort();
  }, [open, month]);
  useEffect(() => {
    if (!open || illustration) return;
    const controller = new AbortController();
    fetch("/img/activity/progress.png", { signal: controller.signal }).then(response => response.ok ? response.blob() : Promise.reject()).then(blob => {
      const reader = new FileReader(); reader.onload = () => { if (!controller.signal.aborted) setIllustration(String(reader.result)); }; reader.readAsDataURL(blob);
    }).catch(() => { /* The data poster remains usable without decoration. */ });
    return () => controller.abort();
  }, [open, illustration]);
  const preview = useMemo(() => data ? buildMonthlySvg(data, illustration, weight, true) : "", [data, illustration, weight]);
  async function exportPoster(format: "svg" | "png") {
    if (!data) return;
    setBusy(true); setError("");
    const svg = buildMonthlySvg(data, illustration, weight);
    try {
      const blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
      if (format === "svg") download(blob, `milon-monat-${month}.svg`);
      else {
        const url = URL.createObjectURL(blob);
        try {
          const image = new Image(); image.src = url; await image.decode();
          const canvas = document.createElement("canvas"); canvas.width = canvas.height = 1024;
          const context = canvas.getContext("2d"); if (!context) throw new Error(); context.drawImage(image, 0, 0);
          const png = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, "image/png"));
          if (!png) throw new Error(); download(png, `milon-monat-${month}.png`);
        } finally { URL.revokeObjectURL(url); }
      }
    } catch { setError("Export fehlgeschlagen. Bitte versuche das andere Format."); }
    finally { setBusy(false); }
  }
  return <>
    <button ref={trigger} type="button" className={styles.trigger} onClick={() => { setMonth(selectedMonth); setOpen(true); }}>Monatsrückblick ↗</button>
    <dialog ref={dialog} className={styles.dialog} aria-labelledby={title} onCancel={() => setOpen(false)} onClose={() => setOpen(false)}>{open && <div className={styles.inner}>
      <header><div><h2 id={title}>Dein Monat als Poster</h2><p>1024 × 1024 · SVG oder PNG · lokal exportieren</p></div><button type="button" aria-label="Monatsrückblick schließen" onClick={() => setOpen(false)}>×</button></header>
      <div className={styles.content}><div className={styles.preview}>{data ? <>{/* eslint-disable-next-line @next/next/no-img-element */}<img src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(preview)}`} alt={`Monatsrückblick ${monthLabel(month)} mit Streckenkonturen und Trainingsbilanz`} /></> : <p role="status">{error || "Dein Monat wird zusammengestellt …"}</p>}</div>
        <div className={styles.options}><label>Monat<select value={month} onChange={event => setMonth(event.target.value)}>{[...months].reverse().map(value => <option key={value} value={value}>{monthLabel(value)}</option>)}</select></label>
          {data && <><p className={styles.summary}>{data.partial ? `Laufender Monat · bis ${data.to_date.split("-").reverse().join(".")}` : "Abgeschlossener Monat"}</p>
            <p>{data.runs} Läufe · {data.strength_sessions} Gym-Einheiten<br />{data.training_days} erfasste Trainingstage</p>
            <label className={styles.check}><input type="checkbox" checked={weight} disabled={data.weight_delta_kg == null} onChange={event => setWeight(event.target.checked)} />Gewichtsverlauf einblenden</label>
            {data.weight_delta_kg == null && <p className={styles.note}>Für den Gewichtsvergleich braucht es getrennte Start-/Endfenster mit je mindestens drei Messtagen.</p>}
            <details><summary>Datenbasis</summary><p>{data.note} Bis zu zwölf Konturen bleiben auf dem Poster einzeln lesbar; die Bilanz enthält alle erfassten Einheiten.</p></details>
          </>}
          {error && <p role="alert" className={styles.error}>{error}</p>}
          <div className={styles.exports}><button type="button" disabled={!data || busy} onClick={() => void exportPoster("png")}>{busy ? "Exportiert …" : "PNG speichern"}</button><button type="button" disabled={!data || busy} onClick={() => void exportPoster("svg")}>SVG speichern</button></div>
        </div>
      </div>
    </div>}</dialog>
  </>;
}
