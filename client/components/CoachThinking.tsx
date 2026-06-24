"use client";

import { useEffect, useState } from "react";
import { COACH_QUIPS } from "@/lib/quips";

const LABELS: Record<string, string> = {
  chat: "Der Coach wertet deine Frage aus",
  daily: "Der Coach schreibt den Tagesreport",
  weekly: "Der Coach schreibt den Wochenreport",
};

// Vier ausgewählte Lade-Animationen (aus der Design-Galerie, #5/#9/#15/#20). Pro Aufruf wird
// zufällig eine gezeigt → Abwechslung. Jede ist selbstständig (SVG + scoped CSS, eindeutig
// präfixierte Klassen/Keyframes), eingespielt per dangerouslySetInnerHTML.
const ANIMS: string[] = [
  // Wiederholungen — Langhantel federt durch die Rep
  `<svg viewBox="0 0 120 96" aria-hidden="true">
     <g class="lift-1-bar">
       <rect x="34" y="46" width="52" height="4" rx="2" fill="#14201f"/>
       <rect x="28" y="38" width="6" height="20" rx="2" fill="#0a6e66"/>
       <rect x="22" y="41" width="6" height="14" rx="2" fill="#5cb8af"/>
       <rect x="86" y="38" width="6" height="20" rx="2" fill="#0a6e66"/>
       <rect x="92" y="41" width="6" height="14" rx="2" fill="#5cb8af"/>
     </g>
   </svg>
   <style>.lift-1-bar{transform-box:fill-box;transform-origin:center;animation:lift-1-rep 1.8s ease-in-out infinite}
   @keyframes lift-1-rep{0%,100%{transform:translateY(14px)}45%,55%{transform:translateY(-14px)}}
   @media(prefers-reduced-motion:reduce){.lift-1-bar{animation:none}}</style>`,
  // EKG-Linie — Herzschlag zeichnet sich
  `<svg viewBox="0 0 120 96" aria-hidden="true">
     <path class="puls-1-trace" d="M6 48 H40 l5 0 l4 -22 l6 44 l5 -22 l3 0 H78 l4 -10 l4 10 H114" fill="none" stroke="#0a6e66" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
   </svg>
   <style>.puls-1-trace{stroke-dasharray:260;stroke-dashoffset:260;animation:puls-1-draw 2s linear infinite}
   @keyframes puls-1-draw{0%{stroke-dashoffset:260}55%{stroke-dashoffset:0}100%{stroke-dashoffset:-260}}
   @media(prefers-reduced-motion:reduce){.puls-1-trace{animation:none;stroke-dashoffset:0}}</style>`,
  // Trend-Linie — Mini-Liniengrafik zeichnet sich steigend nach
  `<svg viewBox="0 0 120 96" aria-hidden="true">
     <line x1="18" y1="74" x2="102" y2="74" stroke="#e2e7e8" stroke-width="2"/>
     <polyline class="data-3-line" points="18,68 38,56 58,60 78,38 102,24" fill="none" stroke="#0a6e66" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="120" stroke-dashoffset="120"/>
     <circle class="data-3-dot" cx="102" cy="24" r="4" fill="#0a6e66"/>
   </svg>
   <style>.data-3-line{animation:data-3-draw 2s ease-in-out infinite}
   .data-3-dot{transform-box:fill-box;transform-origin:center;animation:data-3-pop 2s ease-in-out infinite}
   @keyframes data-3-draw{0%{stroke-dashoffset:120}55%{stroke-dashoffset:0}85%{stroke-dashoffset:0}100%{stroke-dashoffset:120}}
   @keyframes data-3-pop{0%,50%{opacity:0;transform:scale(0)}62%{opacity:1;transform:scale(1.3)}70%,85%{opacity:1;transform:scale(1)}100%{opacity:0;transform:scale(0)}}
   @media(prefers-reduced-motion:reduce){.data-3-line{animation:none;stroke-dashoffset:0}.data-3-dot{animation:none}}</style>`,
  // Stoppuhr — Zeiger kreist
  `<svg viewBox="0 0 120 96" aria-hidden="true">
     <line x1="60" y1="16" x2="60" y2="22" stroke="#0a6e66" stroke-width="3" stroke-linecap="round"/>
     <line x1="52" y1="14" x2="68" y2="14" stroke="#0a6e66" stroke-width="3" stroke-linecap="round"/>
     <circle cx="60" cy="54" r="26" fill="none" stroke="#0a6e66" stroke-width="3"/>
     <circle cx="60" cy="54" r="26" fill="none" stroke="#5cb8af" stroke-width="3" stroke-dasharray="2 9" opacity="0.6"/>
     <line class="play-4-hand" x1="60" y1="54" x2="60" y2="34" stroke="#0a6e66" stroke-width="2.5" stroke-linecap="round"/>
     <circle cx="60" cy="54" r="3" fill="#14201f"/>
   </svg>
   <style>.play-4-hand{transform-box:fill-box;transform-origin:bottom center;animation:play-4-tick 1.6s linear infinite}
   @keyframes play-4-tick{from{transform:rotate(0)}to{transform:rotate(360deg)}}
   @media(prefers-reduced-motion:reduce){.play-4-hand{animation:none}}</style>`,
];

const STAGE_CSS =
  ".ct-stage{display:grid;place-items:center;min-height:112px}" +
  ".ct-stage svg{height:104px;width:auto}" +
  ".ct-quip{animation:ctFade .4s ease}" +
  "@keyframes ctFade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}";

/** Lade-Overlay, solange der Coach arbeitet: eine zufällige von vier Sport-Animationen + rotierende Sprüche. */
export function CoachThinking({ busy }: { busy: "chat" | "daily" | "weekly" | null }) {
  const active = busy !== null;
  const [i, setI] = useState(0);
  const [ani, setAni] = useState(0);
  const [secs, setSecs] = useState(0);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    if (!active) return;
    setHidden(false);
    setSecs(0);
    setI(Math.floor(Math.random() * COACH_QUIPS.length));
    setAni(Math.floor(Math.random() * ANIMS.length));
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
        <div className="ct-stage" dangerouslySetInnerHTML={{ __html: ANIMS[ani] }} />
        <p className="mt-4 text-sm font-semibold text-ink">{label} …</p>
        <p key={i} className="ct-quip mt-1 min-h-[2.5em] text-sm text-accent">{COACH_QUIPS[i]} …</p>
        <p className="mt-4 text-[11px] text-muted">
          läuft seit {secs}s{secs >= 25 ? " · gleich ist es so weit" : ""}
          <span className="mt-0.5 block opacity-80">Esc oder Klick blendet aus — der Coach rechnet weiter.</span>
        </p>
      </div>
      <style>{STAGE_CSS}</style>
    </div>
  );
}
