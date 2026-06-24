"use client";

// Foto auswählen ODER per Drag-and-drop ablegen, auf 3:4 zuschneiden (Ziehen = Pan,
// Slider = Zoom) und als komprimiertes JPEG (810×1080) exportieren. Crop + Rescale +
// Compression im Browser.
import { useEffect, useRef, useState } from "react";

const OUTW = 810, OUTH = 1080; // einheitliches Export-Format (3:4)

type Pt = { x: number; y: number };

export function PhotoPicker({ label, onChange, guide, initialUrl }: { label: string; onChange: (b: Blob | null) => void; guide?: string; initialUrl?: string }) {
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  const [zoom, setZoom] = useState(1);
  const [over, setOver] = useState(false);
  const [showGuide, setShowGuide] = useState(true);
  const [removed, setRemoved] = useState(false);
  const center = useRef<Pt>({ x: 0.5, y: 0.5 });
  const drag = useRef<{ x: number; y: number } | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // zoom/center werden explizit übergeben, damit der Export direkt nach dem Laden den
  // frischen Zustand nutzt (nicht den noch nicht angewendeten State).
  function srcRect(iw: number, ih: number, z: number = zoom, c: Pt = center.current) {
    const baseSW = Math.min(iw, (ih * 3) / 4);
    const baseSH = (baseSW * 4) / 3;
    const sw = baseSW / z;
    const sh = baseSH / z;
    let sx = c.x * iw - sw / 2;
    let sy = c.y * ih - sh / 2;
    sx = Math.max(0, Math.min(iw - sw, sx));
    sy = Math.max(0, Math.min(ih - sh, sy));
    return { sx, sy, sw, sh };
  }

  function draw() {
    const c = canvasRef.current;
    if (!c || !img) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const { sx, sy, sw, sh } = srcRect(img.naturalWidth, img.naturalHeight);
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.drawImage(img, sx, sy, sw, sh, 0, 0, c.width, c.height);
  }

  useEffect(draw, [img, zoom]);

  // Export aus dem ÜBERGEBENEN Bild + Zustand (kein Stale-Closure auf den img-State, der
  // direkt nach pick/drop noch null bzw. das alte Bild ist).
  function exportFrom(image: HTMLImageElement | null, z: number = zoom, c: Pt = center.current) {
    if (!image) { onChange(null); return; }
    const off = document.createElement("canvas");
    off.width = OUTW; off.height = OUTH;
    const ctx = off.getContext("2d");
    if (!ctx) return;
    const { sx, sy, sw, sh } = srcRect(image.naturalWidth, image.naturalHeight, z, c);
    ctx.drawImage(image, sx, sy, sw, sh, 0, 0, OUTW, OUTH);
    off.toBlob((b) => onChange(b), "image/jpeg", 0.85);
  }

  function loadFile(f: File | null | undefined) {
    if (!f || !f.type.startsWith("image/")) return;
    const url = URL.createObjectURL(f);
    const im = new Image();
    const start: Pt = { x: 0.5, y: 0.5 };
    im.onload = () => {
      center.current = start;
      setZoom(1);
      setImg(im);
      exportFrom(im, 1, start);   // direkt aus dem frisch geladenen Bild + Startzustand
      URL.revokeObjectURL(url);   // Blob-URL freigeben (Bitmap ist dekodiert)
    };
    im.onerror = () => URL.revokeObjectURL(url);
    im.src = url;
  }

  function pick(e: React.ChangeEvent<HTMLInputElement>) {
    loadFile(e.target.files?.[0]);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setOver(false);
    loadFile(e.dataTransfer.files?.[0]);
  }
  function onDragOver(e: React.DragEvent) {
    e.preventDefault();
    if (!over) setOver(true);
  }
  function onDragLeave(e: React.DragEvent) {
    // Kein Flackern: nur zurücksetzen, wenn der Cursor das Element wirklich verlässt
    // (nicht beim Übergang auf ein Kind-Element).
    if (!(e.currentTarget as Node).contains(e.relatedTarget as Node | null)) setOver(false);
  }

  function down(e: React.PointerEvent) { if (img) drag.current = { x: e.clientX, y: e.clientY }; }
  function move(e: React.PointerEvent) {
    if (!drag.current || !img) return;
    const rect = canvasRef.current!.getBoundingClientRect();
    const { sw, sh } = srcRect(img.naturalWidth, img.naturalHeight);
    const dx = (e.clientX - drag.current.x) / rect.width;
    const dy = (e.clientY - drag.current.y) / rect.height;
    drag.current = { x: e.clientX, y: e.clientY };
    center.current = {
      x: Math.min(1, Math.max(0, center.current.x - dx * (sw / img.naturalWidth))),
      y: Math.min(1, Math.max(0, center.current.y - dy * (sh / img.naturalHeight))),
    };
    draw();
  }
  function up() { if (drag.current) { drag.current = null; exportFrom(img); } }
  function remove() { setImg(null); setRemoved(true); onChange(null); }

  // Silhouetten-Schablone als teal getöntes Overlay (CSS-Maske nutzt den Alpha-Kanal der
  // freigestellten Outline-PNG) — rein visuelle Ausrichthilfe, kommt NICHT ins Foto.
  const silhouette = guide && showGuide ? (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0"
      style={{
        background: "var(--color-accent)",
        opacity: 0.5,
        WebkitMaskImage: `url(${guide})`, maskImage: `url(${guide})`,
        WebkitMaskRepeat: "no-repeat", maskRepeat: "no-repeat",
        WebkitMaskPosition: "center", maskPosition: "center",
        WebkitMaskSize: "contain", maskSize: "contain",
      }}
    />
  ) : null;

  return (
    <div>
      <div className="mb-1 text-xs font-semibold">{label}</div>
      {img ? (
        <div>
          <div className="relative">
            <canvas
              ref={canvasRef}
              width={270}
              height={360}
              onPointerDown={down}
              onPointerMove={move}
              onPointerUp={up}
              onPointerLeave={up}
              onDrop={onDrop}
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              className={
                "aspect-[3/4] w-full cursor-grab touch-none rounded-lg bg-surface-alt active:cursor-grabbing " +
                (over ? "ring-2 ring-accent" : "")
              }
            />
            {silhouette}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <input
              type="range" min={1} max={3} step={0.01} value={zoom}
              onChange={(e) => setZoom(+e.target.value)}
              onPointerUp={() => exportFrom(img)}
              onKeyUp={() => exportFrom(img)}
              className="flex-1"
              style={{ accentColor: "var(--color-accent)" }}
            />
            {guide && (
              <button type="button" className="py-1 text-[11px] text-muted underline" onClick={() => setShowGuide((v) => !v)}>
                {showGuide ? "Schablone aus" : "Schablone an"}
              </button>
            )}
            <button type="button" className="py-1 text-[11px] text-muted underline" onClick={remove}>
              entfernen
            </button>
          </div>
        </div>
      ) : initialUrl && !removed ? (
        <div>
          <div className="relative" onDrop={onDrop} onDragOver={onDragOver} onDragLeave={onDragLeave}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={initialUrl} alt={label} className={"aspect-[3/4] w-full rounded-lg object-cover " + (over ? "ring-2 ring-accent" : "")} />
            {silhouette}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <label className="cursor-pointer py-1 text-[11px] font-medium text-accent underline">
              ersetzen
              <input type="file" accept="image/*" className="hidden" onChange={pick} />
            </label>
            {guide && (
              <button type="button" className="py-1 text-[11px] text-muted underline" onClick={() => setShowGuide((v) => !v)}>
                {showGuide ? "Schablone aus" : "Schablone an"}
              </button>
            )}
            <button type="button" className="py-1 text-[11px] text-muted underline" onClick={remove}>
              entfernen
            </button>
          </div>
        </div>
      ) : (
        <label
          onDrop={onDrop}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          className={
            "relative grid aspect-[3/4] cursor-pointer place-items-center rounded-lg border-2 border-dashed text-center text-xs hover:border-accent " +
            (over ? "border-accent bg-accent/10 text-accent" : "border-line bg-surface-alt text-muted")
          }
        >
          {silhouette}
          <span className="relative px-2 leading-tight">{over ? "loslassen" : "+ Foto / ziehen"}</span>
          <input type="file" accept="image/*" className="hidden" onChange={pick} />
        </label>
      )}
    </div>
  );
}
