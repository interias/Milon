"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { projectRunRoute, type RunRouteDetail } from "@/lib/run-routes";
import { buildPosterSvg, POSTER_ASSETS, type PosterStyle } from "@/lib/run-poster";
import styles from "./RunPoster.module.css";

const labels = { easy: "Locker", tempo: "Tempo", long: "Langer Lauf", strength: "Kraft", recovery: "Erholung", progress: "Fortschritt" };
const themes: { value: PosterStyle; label: string }[] = [{ value: "clinical", label: "Klinisch" }, { value: "ink", label: "Ink" }, { value: "teal", label: "Teal" }];

async function imageData(path: string, signal: AbortSignal) {
  const response = await fetch(path, { signal });
  if (!response.ok) throw new Error("Die Illustration konnte nicht geladen werden.");
  const blob = await response.blob();
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsDataURL(blob);
  });
}
function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob), link = document.createElement("a");
  link.href = url; link.download = filename; document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export function RunPoster({ route }: { route: RunRouteDetail }) {
  const [open, setOpen] = useState(false), [theme, setTheme] = useState<PosterStyle>("clinical");
  const [asset, setAsset] = useState<(typeof POSTER_ASSETS)[number] | "none">("easy");
  const [illustration, setIllustration] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null), trigger = useRef<HTMLButtonElement>(null), title = useId();
  const geometry = useMemo(() => projectRunRoute(route.segments, 800, 520, 38), [route]);
  useEffect(() => {
    if (!open) return;
    dialog.current?.showModal();
    return () => { dialog.current?.close(); trigger.current?.focus(); };
  }, [open]);
  useEffect(() => {
    const controller = new AbortController();
    setIllustration(""); setError("");
    if (open && asset !== "none") imageData(`/img/activity/${asset}.png`, controller.signal)
      .catch(() => controller.signal.aborted ? "" : imageData("/img/run-ink-slash.png", controller.signal))
      .then(value => { if (!controller.signal.aborted) setIllustration(value); })
      .catch(() => { if (!controller.signal.aborted) setError("Illustration nicht verfügbar. Das Poster lässt sich auch ohne Motiv exportieren."); });
    return () => controller.abort();
  }, [open, asset]);
  const svg = useMemo(() => geometry ? buildPosterSvg(route, geometry, theme, illustration) : "", [route, geometry, theme, illustration]);
  async function exportPoster(format: "svg" | "png") {
    setBusy(true); setError("");
    const filename = `milon-lauf-${route.activity_id}.${format}`;
    try {
      const blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
      if (format === "svg") download(blob, filename);
      else {
        const url = URL.createObjectURL(blob);
        try {
          const image = new Image(); image.src = url; await image.decode();
          const canvas = document.createElement("canvas"); canvas.width = canvas.height = 1024;
          const context = canvas.getContext("2d");
          if (!context) throw new Error();
          context.drawImage(image, 0, 0);
          const png = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, "image/png"));
          if (!png) throw new Error();
          download(png, filename);
        } finally { URL.revokeObjectURL(url); }
      }
    } catch { setError("Export fehlgeschlagen. Bitte versuche das andere Format."); }
    finally { setBusy(false); }
  }
  if (!geometry?.hasExtent) return null;
  return <>
    <button type="button" ref={trigger} className={styles.trigger} onClick={() => setOpen(true)}>Laufposter gestalten <span aria-hidden="true">↗</span></button>
    <dialog ref={dialog} className={styles.dialog} aria-labelledby={title} onCancel={() => setOpen(false)} onClose={() => setOpen(false)}>
      {open && <div className={styles.inner}>
        <header><div><h2 id={title}>Deine Runde als Poster</h2><p>Echte Strecke & Werte · 1024 × 1024 · lokal exportieren</p></div><button type="button" aria-label="Poster schließen" onClick={() => setOpen(false)}>×</button></header>
        <div className={styles.content}><div className={styles.preview}>{/* eslint-disable-next-line @next/next/no-img-element */}<img src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`} alt="Vorschau deines Laufposters mit GPS-Strecke, Datum, Distanz, Dauer und Pace" /></div>
        <div className={styles.options}><fieldset><legend>Farbstil</legend><div className={styles.themes}>{themes.map(item => <button key={item.value} type="button" aria-pressed={theme === item.value} className={`${styles.theme} ${styles[item.value]}`} onClick={() => setTheme(item.value)}>{item.label}</button>)}</div></fieldset>
        <fieldset><legend>Motiv</legend><div className={styles.assets}><button type="button" aria-pressed={asset === "none"} onClick={() => setAsset("none")}><span className={styles.noAsset}>—</span>Ohne</button>{POSTER_ASSETS.map(item => <button key={item} type="button" aria-pressed={asset === item} onClick={() => setAsset(item)}>{/* eslint-disable-next-line @next/next/no-img-element */}<img src={`/img/activity/${item}.png`} alt="" onError={event => { if (!event.currentTarget.src.endsWith("run-ink-slash.png")) event.currentTarget.src = "/img/run-ink-slash.png"; }} />{labels[item]}</button>)}</div></fieldset>
        <p className={styles.note}>Die Kontur bleibt nach Norden ausgerichtet. Start und Ende sind markiert; Aufzeichnungslücken bleiben getrennt.</p>
        {error && <p role="alert" className={styles.error}>{error}</p>}
        <div className={styles.exports}><button type="button" disabled={busy} onClick={() => void exportPoster("png")}>{busy ? "Exportiert …" : "PNG speichern"}</button><button type="button" disabled={busy} onClick={() => void exportPoster("svg")}>SVG speichern</button></div>
        </div></div>
      </div>}
    </dialog>
  </>;
}
