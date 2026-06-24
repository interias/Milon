"use client";

import { useEffect, useState } from "react";
import { COACH_QUIPS } from "@/lib/quips";

const LABELS: Record<string, string> = {
  chat: "Der Coach wertet deine Frage aus",
  daily: "Der Coach schreibt den Tagesreport",
  weekly: "Der Coach schreibt den Wochenreport",
};

const CSS = `
.ct-runner{animation:ctBob .52s ease-in-out infinite}
.ct-legA{transform-box:view-box;transform-origin:118px 76px;animation:ctSwingA .52s ease-in-out infinite}
.ct-legB{transform-box:view-box;transform-origin:118px 76px;animation:ctSwingB .52s ease-in-out infinite}
.ct-armA{transform-box:view-box;transform-origin:128px 50px;animation:ctArmA .52s ease-in-out infinite}
.ct-armB{transform-box:view-box;transform-origin:128px 50px;animation:ctArmB .52s ease-in-out infinite}
.ct-ground{stroke-dasharray:9 7;animation:ctGround .52s linear infinite}
@keyframes ctBob{0%,100%{transform:translateY(0)}50%{transform:translateY(-3.5px)}}
@keyframes ctSwingA{0%,100%{transform:rotate(27deg)}50%{transform:rotate(-25deg)}}
@keyframes ctSwingB{0%,100%{transform:rotate(-25deg)}50%{transform:rotate(27deg)}}
@keyframes ctArmA{0%,100%{transform:rotate(-32deg)}50%{transform:rotate(26deg)}}
@keyframes ctArmB{0%,100%{transform:rotate(26deg)}50%{transform:rotate(-32deg)}}
@keyframes ctGround{to{stroke-dashoffset:-16}}
@keyframes ctFade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.ct-quip{animation:ctFade .4s ease}
@media (prefers-reduced-motion:reduce){.ct-runner,.ct-legA,.ct-legB,.ct-armA,.ct-armB,.ct-ground{animation:none}}
`;

function Runner() {
  return (
    <svg viewBox="0 0 240 130" width="186" height="100" className="mx-auto text-accent"
         role="img" aria-label="Läuft" fill="none" stroke="currentColor"
         strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
      <line className="ct-ground" x1="18" y1="116" x2="222" y2="116" stroke="var(--color-line)" strokeWidth="3" />
      <g className="ct-runner">
        <g className="ct-legB"><path d="M118 76 L124 96 L118 110" /><line x1="118" y1="110" x2="127" y2="110" /></g>
        <g className="ct-armB"><path d="M128 50 L139 63 L133 73" /></g>
        <line x1="128" y1="50" x2="118" y2="76" />
        <circle cx="134" cy="38" r="9" />
        <g className="ct-legA"><path d="M118 76 L124 96 L118 110" /><line x1="118" y1="110" x2="127" y2="110" /></g>
        <g className="ct-armA"><path d="M128 50 L139 63 L133 73" /></g>
      </g>
    </svg>
  );
}

/** Vollflächiges Lade-Overlay mit Läufer-Animation + rotierenden Sprüchen, solange der Coach arbeitet. */
export function CoachThinking({ busy }: { busy: "chat" | "daily" | "weekly" | null }) {
  const active = busy !== null;
  const [i, setI] = useState(0);
  const [secs, setSecs] = useState(0);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    if (!active) return;
    setHidden(false);
    setSecs(0);
    setI(Math.floor(Math.random() * COACH_QUIPS.length));
    const quip = setInterval(
      () => setI((p) => {
        let n = p;
        while (n === p && COACH_QUIPS.length > 1) n = Math.floor(Math.random() * COACH_QUIPS.length);
        return n;
      }),
      2800,
    );
    const tick = setInterval(() => setSecs((s) => s + 1), 1000);
    const onEsc = (e: KeyboardEvent) => { if (e.key === "Escape") setHidden(true); };
    window.addEventListener("keydown", onEsc);
    return () => { clearInterval(quip); clearInterval(tick); window.removeEventListener("keydown", onEsc); };
  }, [active]);

  if (!active || hidden) return null;
  const label = (busy && LABELS[busy]) || "Der Coach denkt nach";

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-ink/40 p-4 backdrop-blur-sm"
      role="dialog" aria-label="Coach arbeitet" onClick={() => setHidden(true)}
    >
      <div
        className="w-full max-w-sm rounded-card border border-line bg-surface p-6 text-center shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <Runner />
        <p className="mt-4 text-sm font-semibold text-ink">{label} …</p>
        <p key={i} className="ct-quip mt-1 min-h-[2.5em] text-sm text-accent">{COACH_QUIPS[i]} …</p>
        <p className="mt-4 text-[11px] text-muted">
          läuft seit {secs}s{secs >= 25 ? " · gleich ist es so weit" : ""}
          <span className="mt-0.5 block opacity-80">Esc oder Klick blendet aus — der Coach rechnet weiter.</span>
        </p>
      </div>
      <style>{CSS}</style>
    </div>
  );
}
