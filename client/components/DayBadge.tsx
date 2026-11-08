"use client";

// Karte „Heute geschafft“: teilbares Tages-Badge im Story-Format (9:16, 1080 × 1920).
// Gezeichnet wird auf ein Canvas — Vorschau und PNG sind dasselbe Bild.
// Routen kommen vom Server nur als anonyme Linienform (Start/Ende −500 m, ohne Karte und Koordinaten).
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type BadgeShape, type DayBadge } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";

const W = 1080, H = 1920, PAD = 80, ROW_H = 108;
const C = { bg: "#fbfcfc", surface: "#ffffff", alt: "#f4f6f7", ink: "#14201f", muted: "#4d5b5a", line: "#e2e7e8",
  accent: "#0a6e66", accent2: "#5cb8af", run: "#0a6e66", ride: "#ab7f00", zwift: "#2a78d6", gym: "#d4579a", walk: "#b53415" };
const MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];

const n0 = (v: number | null | undefined) => (v == null ? "–" : Math.round(v).toLocaleString("de-DE"));
const n1 = (v: number | null | undefined, d = 1) => (v == null ? "–" : v.toLocaleString("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d }));
const paceS = (s: number | null) => (s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")} /km` : null);
const longDate = (iso: string) => { const [y, m, d] = iso.split("-").map(Number); return `${d}. ${MONTHS[m - 1]} ${y}`; };
const localIso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const join = (parts: (string | number | null | false | undefined)[]) => parts.filter(Boolean).join(" · ");

type Row = { color: string; title: string; detail: string };
type Tile = { color: string; shape: BadgeShape; label: string };

function rowsAndTiles(d: DayBadge): { rows: Row[]; tiles: Tile[] } {
  const rows: Row[] = [], tiles: Tile[] = [];
  for (const r of d.runs) {
    const detail = join([r.km != null && `${n1(r.km, 2)} km`, r.minutes != null && `${n0(r.minutes)} min`, paceS(r.pace_s), r.avg_hr && `Ø ${n0(r.avg_hr)} bpm`]);
    rows.push({ color: C.run, title: "Laufen", detail });
    if (r.shape) tiles.push({ color: C.run, shape: r.shape, label: join(["Lauf", r.km != null && `${n1(r.km, 1)} km`, paceS(r.pace_s)]) });
  }
  for (const r of d.rides) {
    if (r.kind === "indoor") {
      rows.push({ color: C.zwift, title: r.world ? `Zwift · ${r.world}` : "Rad indoor",
        detail: join([r.km != null && `${n1(r.km)} km`, r.minutes != null && `${n0(r.minutes)} min`, r.avg_power_w && `Ø ${n0(r.avg_power_w)} W`, r.elevation_m && `${n0(r.elevation_m)} Hm`]) });
      if (r.shape) tiles.push({ color: C.zwift, shape: r.shape, label: join([r.world ? `Zwift · ${r.world}` : "Zwift", r.km != null && `${n1(r.km)} km`]) });
    } else if (r.kind === "outdoor") {
      rows.push({ color: C.ride, title: "Radfahren", detail: join([r.km != null && `${n1(r.km)} km`, r.minutes != null && `${n0(r.minutes)} min`]) });
      if (r.shape) tiles.push({ color: C.ride, shape: r.shape, label: join(["Rad", r.km != null && `${n1(r.km)} km`]) });
    } else {
      rows.push({ color: C.ride, title: "Radfahren (Uhr erkannt)", detail: `${n0(r.minutes)} min` });
    }
  }
  for (const s of d.strength) rows.push({ color: C.gym, title: s.title || "Krafttraining",
    detail: join([s.exercises > 0 && `${s.exercises} Übungen`, s.sets > 0 && `${s.sets} Sätze`, s.tonnage_kg > 0 && `${n1(s.tonnage_kg / 1000)} t`, s.minutes != null && `${n0(s.minutes)} min`]) });
  for (const w of d.walks) rows.push({ color: C.walk, title: "Laufband",
    detail: join([w.km != null && `${n1(w.km, 2)} km`, w.minutes != null && `${n0(w.minutes)} min`, w.incline_pct ? `${n0(w.incline_pct)} % Steigung` : null]) });
  return { rows, tiles: tiles.slice(0, 4) };
}

function fonts() {
  const css = getComputedStyle(document.documentElement);
  const pick = (v: string, fb: string) => (css.getPropertyValue(v).trim() || fb);
  return { display: pick("--font-inter-tight", "system-ui, sans-serif"), body: pick("--font-inter", "system-ui, sans-serif") };
}

function rr(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath(); ctx.roundRect(x, y, w, h, r);
}

function fitText(ctx: CanvasRenderingContext2D, text: string, max: number) {
  if (ctx.measureText(text).width <= max) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(`${t}…`).width > max) t = t.slice(0, -1);
  return `${t.trimEnd()}…`;
}

function drawShape(ctx: CanvasRenderingContext2D, shape: BadgeShape, x: number, y: number, w: number, h: number, color: string) {
  const s = Math.min(w, h);
  const ox = x + (w - s) / 2, oy = y + (h - s) / 2;
  ctx.save();
  ctx.lineJoin = "round"; ctx.lineCap = "round";
  ctx.beginPath();
  shape.forEach(([px, py], i) => (i ? ctx.lineTo(ox + px * s, oy + py * s) : ctx.moveTo(ox + px * s, oy + py * s)));
  ctx.strokeStyle = `${color}2e`; ctx.lineWidth = Math.max(18, s * 0.06); ctx.stroke();
  ctx.strokeStyle = color; ctx.lineWidth = Math.max(7, s * 0.022); ctx.stroke();
  ctx.restore();
}

function draw(ctx: CanvasRenderingContext2D, d: DayBadge, f: { display: string; body: string }, watermark: HTMLImageElement | null) {
  const { rows, tiles } = rowsAndTiles(d);
  const font = (weight: number, size: number, fam: string) => { ctx.font = `${weight} ${size}px ${fam}`; };
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
  // Akzentfläche oben + Silhouette als Wasserzeichen
  const grad = ctx.createLinearGradient(0, 0, 0, 640);
  grad.addColorStop(0, "#e6f1f0"); grad.addColorStop(1, C.bg);
  ctx.fillStyle = grad; ctx.fillRect(0, 0, W, 640);
  if (watermark) { ctx.globalAlpha = 0.09; ctx.drawImage(watermark, W - 560, 20, 540, 540 * watermark.height / watermark.width); ctx.globalAlpha = 1; }

  ctx.fillStyle = C.accent; font(800, 34, f.display);
  ctx.letterSpacing = "8px"; ctx.fillText("MILON", PAD, 128); ctx.letterSpacing = "0px";
  ctx.fillStyle = C.ink; font(800, 112, f.display);
  ctx.fillText(d.is_today ? "Heute" : d.weekday, PAD, 290);
  ctx.fillText(rows.length ? "geschafft" : "erholt", PAD, 400);
  ctx.fillStyle = C.muted; font(500, 40, f.body);
  ctx.fillText(d.is_today ? `${d.weekday}, ${longDate(d.date)}` : longDate(d.date), PAD, 470);

  // Kennzahlen
  const stats: [string, string, string][] = [
    ["Aktive Minuten", n0(d.active_minutes), "min"],
    ["Aktive Kalorien", n0(d.active_kcal), "kcal"],
    ["Schritte", n0(d.steps), d.steps != null && d.steps >= d.step_goal ? "Ziel ✓" : `von ${n0(d.step_goal)}`],
  ];
  const gap = 24, tw = (W - 2 * PAD - 2 * gap) / 3, ty = 540, th = 230;
  stats.forEach(([label, value, unit], i) => {
    const x = PAD + i * (tw + gap);
    rr(ctx, x, ty, tw, th, 28); ctx.fillStyle = C.surface; ctx.fill(); ctx.strokeStyle = C.line; ctx.lineWidth = 2; ctx.stroke();
    ctx.fillStyle = C.muted; font(600, 28, f.body); ctx.fillText(label, x + 30, ty + 60);
    let size = 76;   // große Zahlen verkleinern statt abschneiden
    do { font(800, size, f.display); size -= 4; } while (size > 40 && ctx.measureText(value).width > tw - 56);
    ctx.fillStyle = C.ink; ctx.fillText(value, x + 30, ty + 150);
    ctx.fillStyle = C.muted; font(500, 26, f.body); ctx.fillText(unit, x + 30, ty + 192);
    if (i === 2 && d.steps != null) {
      const p = Math.min(1, d.steps / d.step_goal);
      rr(ctx, x + 30, ty + th - 22, tw - 60, 8, 4); ctx.fillStyle = C.alt; ctx.fill();
      rr(ctx, x + 30, ty + th - 22, (tw - 60) * p, 8, 4); ctx.fillStyle = C.accent; ctx.fill();
    }
  });

  let y = ty + th + 50;
  const footerY = H - 110;
  if (d.empty || rows.length === 0) {
    // Ruhetag: ruhige Fläche statt leerer Liste
    const cy = y + 420;
    ctx.beginPath(); ctx.arc(W / 2, cy, 300, 0, Math.PI * 2); ctx.fillStyle = "#e6f1f0"; ctx.fill();
    ctx.beginPath(); ctx.arc(W / 2, cy, 300, 0, Math.PI * 2); ctx.strokeStyle = C.accent2; ctx.lineWidth = 4; ctx.setLineDash([2, 18]); ctx.lineCap = "round"; ctx.stroke(); ctx.setLineDash([]);
    ctx.textAlign = "center";
    ctx.fillStyle = C.accent; font(800, 84, f.display); ctx.fillText("Ruhetag", W / 2, cy + 10);
    ctx.fillStyle = C.muted; font(500, 32, f.body); ctx.fillText(d.steps ? "Erholung gehört zum Training." : "Noch keine Aktivität erfasst.", W / 2, cy + 70);
    ctx.textAlign = "left";
  } else {
    // Routen als Linienform
    if (tiles.length) {
      const cols = tiles.length === 1 ? 1 : 2, rowsN = tiles.length <= 2 ? 1 : 2;
      // Kacheln geben den Einheiten-Zeilen Vorrang (bis 5 Zeilen), werden aber nie kleiner als 220 px.
      const free = footerY - 40 - y - 80 - Math.min(rows.length, 5) * ROW_H - (rowsN - 1) * gap;
      const cellH = Math.max(220, Math.min(tiles.length === 1 ? 520 : tiles.length === 2 ? 440 : 330, free / rowsN));
      const cellW = (W - 2 * PAD - (cols - 1) * gap) / cols;
      tiles.forEach((t, i) => {
        const x = PAD + (i % cols) * (cellW + gap), yy = y + Math.floor(i / cols) * (cellH + gap);
        rr(ctx, x, yy, cellW, cellH, 28); ctx.fillStyle = C.surface; ctx.fill(); ctx.strokeStyle = C.line; ctx.lineWidth = 2; ctx.stroke();
        drawShape(ctx, t.shape, x + 50, yy + 40, cellW - 100, cellH - 130, t.color);
        ctx.fillStyle = C.ink; font(700, tiles.length > 2 ? 28 : 32, f.body);
        ctx.fillText(fitText(ctx, t.label, cellW - 60), x + 30, yy + cellH - 36);
      });
      y += rowsN * cellH + (rowsN - 1) * gap + 50;
    }
    // Einheiten
    ctx.fillStyle = C.muted; font(700, 28, f.body); ctx.letterSpacing = "3px";
    ctx.fillText(`${d.sessions} ${d.sessions === 1 ? "EINHEIT" : "EINHEITEN"}`, PAD, y); ctx.letterSpacing = "0px";
    y += 30;
    const rowH = ROW_H, room = Math.floor((footerY - 20 - y) / rowH);
    const shown = rows.length > room ? rows.slice(0, Math.max(0, room - 1)) : rows;
    shown.forEach((r) => {
      rr(ctx, PAD, y, W - 2 * PAD, rowH - 18, 24); ctx.fillStyle = C.surface; ctx.fill(); ctx.strokeStyle = C.line; ctx.lineWidth = 2; ctx.stroke();
      rr(ctx, PAD, y, 12, rowH - 18, 6); ctx.fillStyle = r.color; ctx.fill();
      ctx.fillStyle = C.ink; font(700, 34, f.body); ctx.fillText(fitText(ctx, r.title, W - 2 * PAD - 80), PAD + 44, y + 42);
      ctx.fillStyle = C.muted; font(500, 29, f.body); ctx.fillText(fitText(ctx, r.detail, W - 2 * PAD - 80), PAD + 44, y + 78);
      y += rowH;
    });
    if (shown.length < rows.length) {
      ctx.fillStyle = C.muted; font(600, 30, f.body); ctx.fillText(`+ ${rows.length - shown.length} weitere`, PAD + 44, y + 40);
    }
  }

  // Fuß
  ctx.fillStyle = C.line; ctx.fillRect(PAD, footerY, W - 2 * PAD, 2);
  ctx.fillStyle = C.muted; font(500, 26, f.body);
  ctx.fillText(tiles.length ? `Routen ohne Karte · Start und Ziel um ${d.privacy.trim_m} m gekürzt` : "Mein Tag in Bewegung", PAD, footerY + 58);
  ctx.textAlign = "right"; ctx.fillStyle = C.accent; font(800, 30, f.display); ctx.fillText("milon", W - PAD, footerY + 58); ctx.textAlign = "left";
}

export function DayBadgeCard() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [offset, setOffset] = useState(0);   // 0 = heute, 1 = gestern
  const [data, setData] = useState<DayBadge | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setError(false);
    const day = new Date(); day.setDate(day.getDate() - offset);
    api.dayBadge(offset ? localIso(day) : undefined).then((d) => alive && setData(d)).catch(() => alive && setError(true));
    return () => { alive = false; };
  }, [offset]);

  useEffect(() => {
    const el = canvas.current, ctx = el?.getContext("2d");
    if (!el || !ctx || !data) return;
    let alive = true;
    const f = fonts();
    const img = new Image();
    const wm = new Promise<HTMLImageElement | null>((ok) => { img.onload = () => ok(img); img.onerror = () => ok(null); img.src = "/img/run-ink-slash.png"; });
    const loads = [800, 700, 600, 500].flatMap((w) => [document.fonts.load(`${w} 40px ${f.display}`), document.fonts.load(`${w} 40px ${f.body}`)]);
    Promise.all([wm, Promise.allSettled(loads)]).then(([image]) => { if (alive) draw(ctx, data, f, image); });
    return () => { alive = false; };
  }, [data]);

  const exportPng = useCallback(async () => {
    const el = canvas.current;
    if (!el || !data) return;
    setBusy(true); setNote(null);
    try {
      const blob = await new Promise<Blob | null>((ok) => el.toBlob(ok, "image/png"));
      if (!blob) throw new Error("png");
      const name = `milon-${data.date}.png`;
      const file = new File([blob], name, { type: "image/png" });
      if (typeof navigator.canShare === "function" && navigator.canShare({ files: [file] })) {
        try { await navigator.share({ files: [file], title: "Heute geschafft" }); return; }
        catch (e) { if ((e as Error).name === "AbortError") return; }
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNote("Als PNG gespeichert.");
    } catch {
      setNote("Bild konnte nicht erstellt werden.");
    } finally {
      setBusy(false);
    }
  }, [data]);

  const summary = data && rowsAndTiles(data).rows;
  return (
    <Card className="mt-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <CardTitle title="Heute geschafft" sub="Dein Tag als Story-Bild zum Teilen · Routen nur als Linienform" />
        <div className="flex rounded border border-line text-xs font-semibold" role="group" aria-label="Tag wählen">
          {["Heute", "Gestern"].map((label, i) => (
            <button key={label} onClick={() => setOffset(i)} aria-pressed={offset === i}
              className={`px-3 py-1.5 ${offset === i ? "bg-accent text-white" : "text-muted"} ${i ? "border-l border-line" : ""}`}>{label}</button>
          ))}
        </div>
      </div>
      <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
        <div className="mx-auto w-full max-w-[260px] shrink-0 sm:mx-0 sm:w-[240px]">
          <canvas ref={canvas} width={W} height={H} aria-label="Vorschau des Tages-Badges"
            className="block aspect-[9/16] w-full rounded-card border border-line bg-bg shadow-[0_1px_2px_rgba(20,32,31,0.06)]" />
        </div>
        <div className="min-w-0 flex-1">
          {error ? <p className="text-sm text-muted">Tagesdaten konnten nicht geladen werden.</p>
            : !data ? <p className="text-sm text-muted">Wird geladen …</p>
            : <>
              <p className="text-sm"><strong>{data.sessions === 0 ? "Noch keine Einheit" : `${data.sessions} ${data.sessions === 1 ? "Einheit" : "Einheiten"}`}</strong>
                <span className="text-muted"> · {n0(data.active_minutes)} aktive min · {n0(data.steps)} Schritte</span></p>
              {summary && summary.length > 0 && <ul className="mt-2 space-y-1 text-sm">
                {summary.map((r, i) => <li key={i} className="flex min-w-0 gap-2">
                  <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ background: r.color }} />
                  <span className="min-w-0"><span className="font-semibold">{r.title}</span> <span className="text-muted">{r.detail}</span></span>
                </li>)}
              </ul>}
              <div className="mt-4 flex flex-wrap gap-2">
                <button onClick={exportPng} disabled={busy}
                  className="rounded bg-accent px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">Teilen / Speichern</button>
              </div>
              <p className="mt-2 text-[11px] text-muted">
                {note ?? "Auf dem Handy öffnet sich das Teilen-Menü (nur über HTTPS bzw. localhost), sonst wird ein PNG gespeichert."}
              </p>
              <p className="mt-1 text-[11px] text-muted">Datenschutz: keine Karte, keine Orte, keine Koordinaten · Start und Ziel jeder Route um {data.privacy.trim_m} m gekürzt.</p>
            </>}
        </div>
      </div>
    </Card>
  );
}
