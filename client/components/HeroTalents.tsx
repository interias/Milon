"use client";

import { useState } from "react";
import type { Hero } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { Icon } from "@/components/Hero";
import { de0 } from "@/lib/format";

const TIP_YELLOW = "#ffd100";

const TALENT_ICON: Record<string, React.ReactNode> = {
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2" /><path d="M12 20v2" /><path d="m4.93 4.93 1.41 1.41" /><path d="m17.66 17.66 1.41 1.41" /><path d="M2 12h2" /><path d="M20 12h2" /><path d="m6.34 17.66-1.41 1.41" /><path d="m19.07 4.93-1.41 1.41" /></>,
  sunset: <><path d="M12 10V2" /><path d="m4.93 10.93 1.41 1.41" /><path d="M2 18h2" /><path d="M20 18h2" /><path d="m19.07 10.93-1.41 1.41" /><path d="M22 22H2" /><path d="m16 6-4 4-4-4" /><path d="M16 18a4 4 0 0 0-8 0" /></>,
  calendar: <><rect width="18" height="18" x="3" y="4" rx="2" /><path d="M16 2v4" /><path d="M8 2v4" /><path d="M3 10h18" /></>,
  dumbbell: <><path d="M14.4 14.4 9.6 9.6" /><path d="M18.657 21.485a2 2 0 1 1-2.829-2.828l-1.767 1.768a2 2 0 1 1-2.829-2.829l6.364-6.364a2 2 0 1 1 2.829 2.829l-1.768 1.767a2 2 0 1 1 2.828 2.829z" /><path d="M6.404 12.768a2 2 0 1 1-2.829-2.829l1.768-1.767a2 2 0 1 1-2.828-2.829l2.828-2.828a2 2 0 1 1 2.829 2.828l1.767-1.768a2 2 0 1 1 2.829 2.829z" /></>,
  scale: <><path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z" /><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z" /><path d="M7 21h10" /><path d="M12 3v18" /><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2" /></>,
  swords: <><polyline points="14.5 17.5 3 6 3 3 6 3 17.5 14.5" /><line x1="13" x2="19" y1="19" y2="13" /><polyline points="14.5 6.5 18 3 21 3 21 6 17.5 9.5" /><line x1="5" x2="9" y1="14" y2="18" /></>,
  moon: <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />,
  bed: <><path d="M2 4v16" /><path d="M2 8h18a2 2 0 0 1 2 2v10" /><path d="M2 17h20" /><path d="M6 8v9" /></>,
  food: <><path d="M15.4 15.63a7.875 6 135 1 1 6.23-6.23 4.5 3.43 135 0 0-6.23 6.23" /><path d="m8.29 12.71-2.6 2.6a2.5 2.5 0 1 0-1.65 4.65A2.5 2.5 0 1 0 8.7 18.3l2.59-2.59" /></>,
  map: <><path d="M14.106 5.553a2 2 0 0 0 1.788 0l3.659-1.83A1 1 0 0 1 21 4.619v12.764a1 1 0 0 1-.553.894l-4.553 2.277a2 2 0 0 1-1.788 0l-4.212-2.106a2 2 0 0 0-1.788 0l-3.659 1.83A1 1 0 0 1 3 19.381V6.618a1 1 0 0 1 .553-.894l4.553-2.277a2 2 0 0 1 1.788 0z" /><path d="M15 5.764v15" /><path d="M9 3.236v15" /></>,
  anvil: <><path d="M7 10H6a4 4 0 0 1-4-4 1 1 0 0 1 1-1h4" /><path d="M7 5a1 1 0 0 1 1-1h13a1 1 0 0 1 1 1 7 7 0 0 1-7 7H8a1 1 0 0 1-1-1z" /><path d="M9 12v5" /><path d="M15 12v5" /><path d="M5 20a3 3 0 0 1 3-3h8a3 3 0 0 1 3 3 1 1 0 0 1-1 1H6a1 1 0 0 1-1-1" /></>,
  leaf: <><path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10Z" /><path d="M2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12" /></>,
  gem: <><path d="M6 3h12l4 6-10 13L2 9Z" /><path d="M11 3 8 9l4 13 4-13-3-6" /><path d="M2 9h20" /></>,
  chest: <><rect x="3" y="8" width="18" height="12" rx="2" /><path d="M3 12h18" /><path d="M12 12v3" /><path d="M7 8V6a5 5 0 0 1 10 0v2" /></>,
  skull: <><path d="m12.5 17-.5-1-.5 1h1z" /><path d="M15 22a1 1 0 0 0 1-1v-1a2 2 0 0 0 1.56-3.25 8 8 0 1 0-11.12 0A2 2 0 0 0 8 20v1a1 1 0 0 0 1 1z" /><circle cx="15" cy="12" r="1" /><circle cx="9" cy="12" r="1" /></>,
};
const LOCK = <><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>;

// --- Auftragslog im Stil des WoW-Quest-Trackers --------------------------------------------
export function HeroQuestLog({ data }: { data: Hero }) {
  const wk = data.quests;
  return (
    <Card>
      <CardTitle title="Auftragslog" sub="Neue Aufträge jeden Montag · je 150 EP · alle erfüllt = Auftragsbeute" />
      {!wk ? <p className="text-xs text-muted">Aufträge starten mit deiner Heldenreise.</p> : <>
        <ul className="space-y-3">
          {wk.quests.map((q) => {
            const pct = Math.min(1, q.progress / q.target);
            const fmt = (v: number) => q.unit === "Schritte" ? de0(v) : String(Math.round(v * 10) / 10).replace(".", ",");
            return (
              <li key={q.id}>
                <p className="font-display text-[13px] font-bold" style={{ color: q.done ? "#9d9d9d" : TIP_YELLOW }}>
                  {q.done ? "✓ " : ""}{q.title}
                  <span className="ml-2 font-sans text-[10px] font-normal uppercase tracking-wider text-muted">{CAT[q.category]}</span>
                </p>
                <p className="text-[12px]" style={{ color: q.done ? "#9d9d9d" : "#fff" }}>– {fmt(q.progress)}/{fmt(q.target)} {q.goal}</p>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-[#0a0807]">
                  <div className="h-full rounded-full transition-[width] duration-700" style={{ width: `${pct * 100}%`, background: q.done ? "#1eff00" : "#b36cf0" }} />
                </div>
              </li>
            );
          })}
        </ul>
        <div className="wow-rule my-3" />
        <p className="flex items-center gap-2 text-xs" style={{ color: wk.complete ? "#1eff00" : "var(--color-muted)" }}>
          <Icon size={16}>{TALENT_ICON.chest}</Icon>
          {wk.complete ? "Alle Aufträge erfüllt – die Auftragsbeute liegt in deinen Taschen." : `Auftragsbeute nach ${wk.quests.length} erfüllten Aufträgen`}
        </p>
        {wk.halved && <p className="mt-1 text-[11px] text-muted">{wk.sick_days} Krankheitstage – Ziele diese Woche halbiert.</p>}
      </>}
    </Card>
  );
}
const CAT: Record<string, string> = { lauf: "Laufen", kraft: "Kraft", pflege: "Pflege" };

// --- Talentbaum: eine Reihe je 10 Stufen, je eine von drei Optionen ------------------------
export function HeroTalentTree({ data, onChoose }: { data: Hero; onChoose: (row: number, choice: string | null) => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const toggle = (lvl: number) => setExpanded((prev) => { const n = new Set(prev); if (n.has(lvl)) n.delete(lvl); else n.add(lvl); return n; });
  const color = data.hero.class_color;
  async function pick(row: number, choice: string | null) {
    setBusy(`${row}:${choice}`);
    try { await onChoose(row, choice); setExpanded((prev) => { const n = new Set(prev); n.delete(row); return n; }); } finally { setBusy(null); }
  }
  return (
    <Card>
      <CardTitle title="Talente" sub="Eine Reihe je 10 Stufen · Talente lenken deinen Trainingsfokus · wirken ab dem Tag der Wahl, jederzeit umwählbar" />
      <div className="@container space-y-2">
        {data.talents.map((row) => (
          <div key={row.level} className="grid grid-cols-[40px_minmax(0,1fr)] items-center gap-2 sm:grid-cols-[52px_minmax(0,1fr)]">
            <div className="text-center">
              <span className="mx-auto grid h-9 w-9 place-items-center rounded-full border-2 font-display text-sm font-bold"
                    style={{ borderColor: row.unlocked ? "var(--wow-gold)" : "#3a2d1a", color: row.unlocked ? TIP_YELLOW : "#5b4526", background: "#0b0907" }}>{row.level}</span>
              <p className="mt-0.5 hidden truncate text-[9px] uppercase tracking-wider text-muted sm:block">{row.name}</p>
            </div>
            {row.options.length === 0 ? (
              <div className="flex h-14 items-center gap-2 rounded-md border border-dashed border-[#3a2d1a] px-3 text-[11px] text-muted">
                <Icon size={16}>{LOCK}</Icon> Reihe ab Stufe {row.level} – noch verborgen
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-1.5 @xl:grid-cols-3">
                {!expanded.has(row.level) && !row.chosen && (
                  <button type="button" onClick={() => toggle(row.level)} disabled={!row.unlocked}
                          className="flex h-12 items-center justify-between rounded-md border border-dashed px-3 text-[12px] @xl:hidden"
                          style={{ borderColor: row.unlocked ? "var(--wow-gold)" : "#3a2d1a", color: row.unlocked ? TIP_YELLOW : "#6b5a40" }}>
                    {row.unlocked ? "Talent wählen" : `Ab Stufe ${row.level}`} <span>{row.unlocked ? "▾" : "🔒"}</span>
                  </button>
                )}
                {row.options.map((o) => {
                  const chosen = row.chosen === o.key;
                  const dim = !row.unlocked || (row.chosen != null && !chosen);
                  const narrowHidden = !expanded.has(row.level) && !chosen;
                  return (
                    <button key={o.key} type="button" disabled={!row.unlocked || busy != null}
                            onClick={() => pick(row.level, chosen ? null : o.key)}
                            title={row.unlocked ? (chosen ? "Klicken zum Abwählen" : "Klicken zum Wählen") : `Ab Stufe ${row.level}`}
                            className={`min-w-0 items-center gap-2 rounded-md border p-1.5 text-left transition sm:p-2 ${chosen ? "wow-pulse" : ""} ${narrowHidden ? "hidden @xl:flex" : "flex"}`}
                            style={{ borderColor: chosen ? "var(--wow-gold)" : "#3a2d1a", opacity: dim ? 0.5 : 1,
                                     background: chosen ? `radial-gradient(circle at 20% 50%, color-mix(in srgb, ${color} 25%, transparent), #120e0a 70%)` : "#120e0a",
                                     ["--glow" as string]: "var(--wow-gold)", filter: row.unlocked ? undefined : "grayscale(1)" }}>
                      <span className="grid h-8 w-8 shrink-0 place-items-center rounded border border-black"
                            style={{ color: chosen ? TIP_YELLOW : "#a99c80", background: "#0b0907" }}>
                        <Icon size={17}>{row.unlocked ? TALENT_ICON[o.icon] : LOCK}</Icon>
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[12px] font-semibold leading-tight" style={{ color: chosen ? TIP_YELLOW : "var(--color-ink)" }}>{o.name}</span>
                        <span className="block text-[10px] leading-tight text-muted">{o.effect}</span>
                      </span>
                    </button>
                  );
                })}
                {row.chosen && row.unlocked && (
                  <button type="button" onClick={() => toggle(row.level)} className="justify-self-start text-[11px] text-muted underline decoration-dotted underline-offset-4 @xl:hidden">
                    {expanded.has(row.level) ? "zuklappen ▴" : "ändern ▾"}
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}
