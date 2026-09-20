"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

export function RunAnalysisDialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = dialog.current!;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    element.showModal();
    document.body.style.overflow = "hidden";
    return () => { element.close(); document.body.style.overflow = overflow; previous?.focus(); };
  }, []);
  return <dialog ref={dialog} aria-labelledby={titleId} onKeyDown={(event) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    onClose();
  }} onCancel={(event) => {
    event.preventDefault();
    event.stopPropagation();
    if (event.target === event.currentTarget) onClose();
  }}
    className="fixed inset-0 m-auto max-h-[85dvh] w-[calc(100%-2rem)] max-w-3xl overflow-y-auto rounded-card border border-line bg-surface p-4 text-ink shadow-xl backdrop:bg-black/35 sm:p-6">
    <div className="mb-4 flex items-center justify-between gap-4">
      <h2 id={titleId} className="text-base font-semibold">{title}</h2>
      <button autoFocus onClick={onClose} className="rounded border border-line px-3 py-2 text-sm">Schließen</button>
    </div>
    {children}
  </dialog>;
}
