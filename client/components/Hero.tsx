"use client";

import { useEffect, useState } from "react";
import type { Hero, HeroAttribute, HeroBuff, HeroItem, HeroVault, Rarity } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
import { de0, dm } from "@/lib/format";
import { AttributeRadar, HeroFigure } from "@/components/HeroVisuals";

// Farben/Tokens kommen aus dem .wow-Thema in globals.css.
const rc = (r: Rarity) => `var(--rar-${r})`;
const GOLD = "var(--wow-gold)";
const TIP_YELLOW = "#ffd100";

// Linien-Icons (lucide-Pfade, currentColor) für Ausrüstungs-Plätze und Klassen-Wappen.
const SLOT_ICON: Record<string, React.ReactNode> = {
  kopf: <><path d="M11.562 3.266a.5.5 0 0 1 .876 0L15.39 8.87a1 1 0 0 0 1.516.294L21.183 5.5a.5.5 0 0 1 .798.519l-2.834 10.246a1 1 0 0 1-.956.734H5.81a1 1 0 0 1-.957-.734L2.02 6.02a.5.5 0 0 1 .798-.519l4.276 3.664a1 1 0 0 0 1.516-.294z" /><path d="M5 21h14" /></>,
  schultern: <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" />,
  brust: <path d="M20.38 3.46 16 2a4 4 0 0 1-8 0L3.62 3.46a2 2 0 0 0-1.34 2.23l.58 3.47a1 1 0 0 0 .99.84H6v10c0 1.1.9 2 2 2h8a2 2 0 0 0 2-2V10h2.15a1 1 0 0 0 .99-.84l.58-3.47a2 2 0 0 0-1.34-2.23z" />,
  haende: <><path d="M18 11V6a2 2 0 0 0-4 0v5" /><path d="M14 10V4a2 2 0 0 0-4 0v6" /><path d="M10 10.5V6a2 2 0 0 0-4 0v8" /><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15" /></>,
  handgelenk: <><circle cx="12" cy="12" r="6" /><path d="M12 10v2l1 1" /><path d="m16.13 7.66-.81-4.05a2 2 0 0 0-2-1.61h-2.68a2 2 0 0 0-1.96 1.61l-.81 4.05" /><path d="m7.88 16.36.8 4a2 2 0 0 0 1.96 1.61h2.72a2 2 0 0 0 1.96-1.61l.81-4.05" /></>,
  beine: <path d="M7 3h10l1 18h-4l-2-11-2 11H6Z" />,
  fuesse: <><path d="M4 16v-2.38C4 11.5 2.97 10.5 3 8c.03-2.72 1.49-6 4.5-6C9.37 2 10 3.8 10 5.5c0 3.11-2 5.66-2 8.68V16a2 2 0 1 1-4 0Z" /><path d="M20 20v-2.38c0-2.12 1.03-3.12 1-5.62-.03-2.72-1.49-6-4.5-6C14.63 6 14 7.8 14 9.5c0 3.11 2 5.66 2 8.68V20a2 2 0 1 0 4 0Z" /></>,
  hals: <><path d="M7 3l5 7 5-7" /><circle cx="12" cy="15" r="5" /></>,
  ring: <><path d="M6 3h12l4 6-10 13L2 9Z" /><path d="M11 3 8 9l4 13 4-13-3-6" /><path d="M2 9h20" /></>,
  schmuck: <><line x1="10" x2="14" y1="2" y2="2" /><line x1="12" x2="15" y1="14" y2="11" /><circle cx="12" cy="14" r="8" /></>,
};
const CLASS_ICON: Record<string, React.ReactNode> = {
  krieger: <><polyline points="14.5 17.5 3 6 3 3 6 3 17.5 14.5" /><line x1="13" x2="19" y1="19" y2="13" /><line x1="16" x2="20" y1="16" y2="20" /><line x1="19" x2="21" y1="21" y2="19" /></>,
  paladin: SLOT_ICON.schultern,
  jaeger: <><circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="6" /><circle cx="12" cy="12" r="2" /></>,
  moench: SLOT_ICON.fuesse,
};
const CHEST = <><rect x="3" y="8" width="18" height="12" rx="2" /><path d="M3 12h18" /><path d="M12 12v3" /><path d="M7 8V6a5 5 0 0 1 10 0v2" /></>;
const LOCK = <><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>;
const LEFT_SLOTS = ["kopf", "hals", "schultern", "brust", "handgelenk"];
const RIGHT_SLOTS = ["haende", "beine", "fuesse", "ring", "schmuck"];
const SLOT_NAME: Record<string, string> = {
  kopf: "Kopf", hals: "Hals", schultern: "Schultern", brust: "Brust", handgelenk: "Handgelenk",
  haende: "Hände", beine: "Beine", fuesse: "Füße", ring: "Finger", schmuck: "Schmuckstück",
};

export function Icon({ children, size = 20 }: { children: React.ReactNode; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
              strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>;
}

// --- Tooltip (WoW-Stil): beim Überfahren schwebend, beim Klicken als Dialog -----------------
export type Gear = {
  equipment: Record<string, HeroItem>;
  equip: (itemId: string) => Promise<void>;
  unequip: (slot: string) => Promise<void>;
  equipBest: () => Promise<void>;
  disenchant: (itemId: string) => Promise<void>;
  upgrade: (itemId: string) => Promise<void>;
  dust: number;
  dragging: string | null;
  setDragging: (slot: string | null) => void;
  isNew: (itemId: string) => boolean;
  markSeen: (itemId: string) => void;
};
const DRAG_TYPE = "application/x-hero-item";
const SHEEN = new Set<Rarity>(["lila", "orange", "rot"]);
const BTN = "rounded border px-3 py-1.5 font-display text-xs font-bold";
const BTN_STYLE = { background: "linear-gradient(180deg, #3b2c18, #1d150c)", borderColor: "#6b5230", color: TIP_YELLOW };

function ItemTooltipBody({ item, worn = false }: { item: HeroItem; worn?: boolean }) {
  const SOURCE: Record<HeroItem["source"], string> = { beute: "Beute nach einem Lauf", truhe: "Aus der Wochentruhe", veteran: "Aus der Veteranentruhe", auftrag: "Auftragsbeute", boss: "Hort eines Monatsbosses", instanz: "Schatz einer Instanz" };
  return <>
    {worn && <p className="mb-0.5 text-[11px] text-[#9d9d9d]">Derzeit angelegt</p>}
    <p className="text-[15px] font-bold leading-snug" style={{ color: rc(item.rarity) }}>{item.name}</p>
    <p style={{ color: TIP_YELLOW }}>Gegenstandsstufe {item.ilvl}{item.upgrades ? <span style={{ color: "#1eff00" }}> · Aufwertung {item.upgrades}/3</span> : null}</p>
    <p className="flex justify-between gap-6"><span>{item.slot_label}</span><span>{item.rarity_label}</span></p>
    <p style={{ color: "#1eff00" }}>Verdient: {item.reason}</p>
    {item.lucky && <p style={{ color: "#1eff00" }}>Glücksfund: eine Stufe besser als verdient</p>}
    {item.set && <p className="mt-1" style={{ color: TIP_YELLOW }}>Garnitur {item.set}</p>}
    <p className="mt-1 italic" style={{ color: TIP_YELLOW }}>„{item.flavor}“</p>
    <p className="mt-1 text-[12px] text-[#9d9d9d]">{SOURCE[item.source]} · {dm(item.date)}{item.run_km ? ` · ${item.run_km.toLocaleString("de-DE")} km` : ""}</p>
  </>;
}

function IlvlDiff({ item, worn }: { item: HeroItem; worn?: HeroItem }) {
  if (!worn || worn.id === item.id || item.equipped) return null;
  const d = item.ilvl - worn.ilvl;
  const color = d > 0 ? "#1eff00" : d < 0 ? "#ff3b3b" : "#9d9d9d";
  const text = d > 0 ? `▲ ${d} Stufen besser als angelegt` : d < 0 ? `▼ ${-d} Stufen schlechter als angelegt` : "gleiche Stufe wie angelegt";
  return <p className="mt-1 text-[12px]" style={{ color }}>{text}</p>;
}

function useItemTip(gear?: Gear) {
  const [tip, setTip] = useState<{ item: HeroItem; x: number; y: number } | null>(null);
  const [open, setOpen] = useState<HeroItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDe, setConfirmDe] = useState(false);
  const worn = (item: HeroItem) => gear?.equipment[item.slot];
  const canEquip = (item: HeroItem) => !!gear && !item.equipped;
  const bind = (item: HeroItem) => ({
    onMouseEnter: (e: React.MouseEvent) => { setTip({ item, x: e.clientX, y: e.clientY }); gear?.markSeen(item.id); },
    onMouseMove: (e: React.MouseEvent) => setTip({ item, x: e.clientX, y: e.clientY }),
    onMouseLeave: () => setTip(null),
    onClick: () => { setTip(null); setOpen(item); setConfirmDe(false); gear?.markSeen(item.id); },
    // Rechtsklick legt an wie in WoW.
    onContextMenu: canEquip(item) ? (e: React.MouseEvent) => { e.preventDefault(); setTip(null); gear!.equip(item.id); } : undefined,
    draggable: canEquip(item),
    onDragStart: canEquip(item) ? (e: React.DragEvent) => {
      setTip(null);
      e.dataTransfer.setData(DRAG_TYPE, JSON.stringify({ id: item.id, slot: item.slot }));
      e.dataTransfer.effectAllowed = "move";
      gear!.setDragging(item.slot);
    } : undefined,
    onDragEnd: gear ? () => gear.setDragging(null) : undefined,
  });
  async function act(fn: () => Promise<void>) {
    setBusy(true);
    try { await fn(); setOpen(null); } finally { setBusy(false); }
  }
  const compare = tip && !tip.item.equipped ? worn(tip.item) : undefined;
  const node = <>
    {tip && typeof window !== "undefined" && (
      <div className="pointer-events-none fixed z-50 flex items-start gap-1.5"
           style={{ left: Math.max(12, Math.min(tip.x + 16, window.innerWidth - (compare ? 600 : 300))), top: Math.max(12, Math.min(tip.y + 16, window.innerHeight - 240)) }}>
        <div className="wow-tip w-72"><ItemTooltipBody item={tip.item} /><IlvlDiff item={tip.item} worn={worn(tip.item)} /></div>
        {compare && compare.id !== tip.item.id && <div className="wow-tip w-72 opacity-95"><ItemTooltipBody item={compare} worn /></div>}
      </div>
    )}
    {open && <RunAnalysisDialog title={open.name} onClose={() => setOpen(null)}>
      <div className="flex flex-wrap justify-center gap-2">
        <div className="wow-tip w-full max-w-sm"><ItemTooltipBody item={open} /><IlvlDiff item={open} worn={worn(open)} /></div>
        {!open.equipped && worn(open) && worn(open)!.id !== open.id && <div className="wow-tip w-full max-w-sm"><ItemTooltipBody item={worn(open)!} worn /></div>}
      </div>
      {gear && <div className="mt-4 flex flex-wrap justify-center gap-2">
        {open.equipped
          ? <button type="button" disabled={busy} className={BTN} style={BTN_STYLE} onClick={() => act(() => gear.unequip(open.slot))}>Ablegen</button>
          : <button type="button" disabled={busy} className={BTN} style={BTN_STYLE} onClick={() => act(() => gear.equip(open.id))}>{worn(open) ? "Anlegen (tauschen)" : "Anlegen"}</button>}
        {open.upgrade_cost != null && (
          <button type="button" disabled={busy || gear.dust < open.upgrade_cost} className={BTN} style={{ ...BTN_STYLE, color: "#1eff00" }}
                  title={gear.dust < open.upgrade_cost ? `Du hast ${gear.dust} Arkanstaub` : undefined}
                  onClick={() => act(() => gear.upgrade(open.id))}>Aufwerten +4 · {open.upgrade_cost} Staub</button>
        )}
        {!open.equipped && (
          <button type="button" disabled={busy} className={BTN}
                  style={confirmDe ? { background: "linear-gradient(180deg, #b8131a, #6e0b0f)", borderColor: GOLD, color: TIP_YELLOW } : { ...BTN_STYLE, color: "#b552f7" }}
                  onClick={() => confirmDe ? act(() => gear.disenchant(open.id)) : setConfirmDe(true)}>
            {confirmDe ? `Wirklich zerlegen? (+${open.dust} Staub)` : `Entzaubern · +${open.dust} Staub`}
          </button>
        )}
      </div>}
      {gear && <p className="mt-2 text-center text-[11px] text-muted">Arkanstaub: {gear.dust}</p>}
    </RunAnalysisDialog>}
  </>;
  return { bind, node };
}

function Slot({ item, slot, bind, size = 44, upgrade = false, isNew = false }: { item?: HeroItem; slot?: string; bind?: ReturnType<ReturnType<typeof useItemTip>["bind"]>; size?: number; upgrade?: boolean; isNew?: boolean }) {
  if (!item) {
    return <span className="wow-slot text-[#4b3a22]" style={{ width: size, height: size }} title={slot ? `${SLOT_NAME[slot]} – leer` : undefined}>
      {slot && <Icon size={size * 0.45}>{SLOT_ICON[slot]}</Icon>}
    </span>;
  }
  const col = rc(item.rarity);
  return <button type="button" {...bind} aria-label={item.name}
                 className={`wow-slot wow-slot-filled relative shrink-0 focus:outline-none focus-visible:ring-2 ${SHEEN.has(item.rarity) ? "wow-sheen" : ""} ${isNew ? "wow-new" : ""}`}
                 style={{ width: size, height: size, color: col, ["--glow" as string]: col }}>
    <Icon size={size * 0.5}>{SLOT_ICON[item.slot]}</Icon>
    {upgrade && <span className="absolute left-0.5 top-0 text-[11px] font-bold leading-none text-[#1eff00]" style={{ textShadow: "0 1px 1px #000" }} title="Verbesserung">▲</span>}
  </button>;
}

// --- Einheitenrahmen ----------------------------------------------------------------------
function XpBar({ data }: { data: Hero }) {
  const h = data.hero;
  const span = h.next - h.floor;
  const rested = Math.min(1 - h.progress, h.rested / span);
  return (
    <div className="relative h-4 w-full overflow-hidden rounded-[3px] border border-[#000] bg-[#0a0807]" style={{ boxShadow: "0 0 0 1px #5b4526" }}>
      {rested > 0 && <div className="absolute inset-y-0" style={{ left: `${h.progress * 100}%`, width: `${rested * 100}%`, background: "var(--wow-rested)", opacity: .55 }} />}
      <div className="absolute inset-y-0 left-0 transition-[width] duration-700"
           style={{ width: `${h.progress * 100}%`, background: "linear-gradient(180deg, #b36cf0, var(--wow-xp) 55%, #5c2391)" }} />
      <div className="absolute inset-0" style={{ background: "repeating-linear-gradient(90deg, transparent 0 calc(5% - 1px), rgba(0,0,0,.65) calc(5% - 1px) 5%)" }} />
      <p className="absolute inset-0 grid place-items-center text-[11px] font-semibold text-white" style={{ textShadow: "0 1px 2px #000" }}>
        EP {de0(h.xp - h.floor)} / {de0(span)}{h.rested > 0 ? ` · Ausgeruht +${de0(h.rested)}` : ""}
      </p>
    </div>
  );
}

// --- Buffs & Debuffs am Einheitenrahmen ----------------------------------------------------
const BUFF_ICON: Record<string, React.ReactNode> = {
  food: <><path d="M15.4 15.63a7.875 6 135 1 1 6.23-6.23 4.5 3.43 135 0 0-6.23 6.23" /><path d="m8.29 12.71-2.6 2.6a2.5 2.5 0 1 0-1.65 4.65A2.5 2.5 0 1 0 8.7 18.3l2.59-2.59" /></>,
  moon: <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />,
  eye: <><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" /></>,
  bed: <><path d="M2 4v16" /><path d="M2 8h18a2 2 0 0 1 2 2v10" /><path d="M2 17h20" /><path d="M6 8v9" /></>,
  thermo: <path d="M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z" />,
  zap: <path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z" />,
  battery: <><rect x="2" y="7" width="16" height="10" rx="2" /><path d="M22 11v2" /><path d="M6 11v2" /></>,
  flame: <path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z" />,
  target: <><circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="6" /><circle cx="12" cy="12" r="2" /></>,
};

function BuffBar({ buffs }: { buffs: HeroBuff[] }) {
  const [tip, setTip] = useState<{ b: HeroBuff; x: number; y: number } | null>(null);
  const [pinned, setPinned] = useState<HeroBuff | null>(null);
  if (!buffs.length) return null;
  const show = tip ?? (pinned ? { b: pinned, x: 0, y: 0 } : null);
  return (
    <div className="flex flex-wrap gap-1.5" aria-label="Buffs und Debuffs">
      {buffs.map((b) => {
        const debuff = b.kind === "debuff";
        return <button key={b.key} type="button" aria-label={`${b.name}: ${b.effect}`}
                       onMouseEnter={(e) => setTip({ b, x: e.clientX, y: e.clientY })}
                       onMouseMove={(e) => setTip({ b, x: e.clientX, y: e.clientY })}
                       onMouseLeave={() => setTip(null)}
                       onClick={() => setPinned(pinned?.key === b.key ? null : b)}
                       className="grid h-8 w-8 place-items-center rounded-[4px] border"
                       style={{ borderColor: debuff ? "#c41e1e" : "#6b5230", color: debuff ? "#ff6a5c" : TIP_YELLOW,
                                background: debuff ? "radial-gradient(circle, #3a0e0c, #120605)" : "radial-gradient(circle, #2e2414, #0b0907)",
                                boxShadow: "inset 0 0 0 1px #000" }}>
          <Icon size={17}>{BUFF_ICON[b.icon]}</Icon>
        </button>;
      })}
      {show && (
        <div className={`wow-tip z-50 w-64 ${tip ? "pointer-events-none fixed" : "absolute right-4 mt-10"}`}
             style={tip ? { left: Math.max(12, Math.min(tip.x + 14, (typeof window !== "undefined" ? window.innerWidth : 800) - 280)), top: tip.y + 14 } : undefined}>
          <p className="font-bold" style={{ color: show.b.kind === "debuff" ? "#ff6a5c" : TIP_YELLOW }}>{show.b.name}</p>
          <p className="text-white">{show.b.effect}</p>
          <p className="mt-1 text-[12px] text-[#9d9d9d]">{show.b.kind === "debuff" ? "Debuff" : "Buff"} · {show.b.source}</p>
        </div>
      )}
    </div>
  );
}

// --- Spezialisierung wählen -----------------------------------------------------------------
function SpecChooser({ data, onChoose, onClose }: { data: Hero; onChoose: (spec: string | null) => Promise<void>; onClose: () => void }) {
  const h = data.hero;
  const [busy, setBusy] = useState(false);
  async function pick(spec: string | null) {
    setBusy(true);
    try { await onChoose(spec); onClose(); } finally { setBusy(false); }
  }
  const autoLabel = data.specs.find((s) => s.key === h.spec_auto)?.label ?? "noch offen";
  return (
    <RunAnalysisDialog title="Spezialisierung wählen" onClose={onClose}>
      <p className="mb-3 text-sm text-muted">Deine Klasse folgt deinem Training. Die Spezialisierung wählst du als <b className="text-ink">Trainingsfokus</b>:
        passende Läufe geben ab heute +10 % EP. Die Neigung zeigt, wie gut dein bisheriges Training dazu passt.</p>
      <div className="grid gap-2 sm:grid-cols-2">
        {data.specs.map((sp) => {
          const active = h.spec_chosen === sp.key;
          return <button key={sp.key} type="button" disabled={busy || active} onClick={() => pick(sp.key)}
                         className="rounded-md border p-3 text-left transition hover:brightness-110"
                         style={{ borderColor: active ? h.class_color : "#4b3a22", background: active ? `color-mix(in srgb, ${h.class_color} 14%, #120e0a)` : "#120e0a" }}>
            <p className="font-display text-sm font-bold" style={{ color: active ? h.class_color : TIP_YELLOW }}>{sp.label}{active ? " · aktiv" : ""}</p>
            <p className="text-xs text-muted">{sp.desc}</p>
            <p className="mt-1 text-xs" style={{ color: "#1eff00" }}>{sp.focus}</p>
            <div className="mt-2 flex items-center gap-2 text-[11px] text-muted">
              <span>Neigung</span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[#0a0807]"><div className="h-full rounded-full" style={{ width: `${(sp.score ?? 0) * 100}%`, background: h.class_color }} /></div>
              <span className="tabular-nums">{sp.score != null ? Math.round(sp.score * 100) : "–"}</span>
            </div>
          </button>;
        })}
      </div>
      <button type="button" disabled={busy || h.spec_chosen == null} onClick={() => pick(null)}
              className="mt-3 w-full rounded-md border border-[#4b3a22] p-2.5 text-left text-xs text-muted hover:brightness-110">
        <b style={{ color: TIP_YELLOW }}>Automatisch</b> – folgt deiner Neigung (aktuell {autoLabel}), ohne Fokus-Bonus{h.spec_chosen == null ? " · aktiv" : ""}
      </button>
    </RunAnalysisDialog>
  );
}

export function HeroHeader({ data, onSpec, onTitle }: { data: Hero; onSpec: (spec: string | null) => Promise<void>; onTitle: () => void }) {
  const [choosing, setChoosing] = useState(false);
  const h = data.hero;
  const shares: [string, number, string][] = [
    ["Laufen", h.shares.laufen, "#aad372"], ["Kraft", h.shares.kraft, "#c69b6d"], ["Alltag", h.shares.alltag, "#00ff98"],
  ];
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-4">
        <div className="relative shrink-0">
          <div className="grid h-20 w-20 place-items-center rounded-full"
               style={{ color: h.class_color, background: `radial-gradient(circle at 50% 35%, ${h.class_color}55, #0b0907 72%)`,
                        boxShadow: `0 0 0 2px #000, 0 0 0 4px ${h.class_color}, 0 0 0 5px #000, 0 0 0 7px var(--wow-gold), 0 0 18px ${h.class_color}66` }}>
            <Icon size={38}>{CLASS_ICON[h.class]}</Icon>
          </div>
          <span className="absolute -bottom-1 -left-1 grid h-8 w-8 place-items-center rounded-full border-2 bg-[#120e0a] font-display text-sm font-bold"
                style={{ borderColor: GOLD, color: TIP_YELLOW }} title="Level">{h.level}</span>
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-3xl font-bold leading-none" style={{ color: h.class_color, textShadow: "0 2px 6px #000" }}>{h.class_label}</h2>
          <p className="mt-1 font-display text-sm" style={{ color: "var(--wow-gold-soft)" }}>
            <button type="button" onClick={onTitle} className="underline decoration-dotted underline-offset-4" title="Titel wählen">&lt;{h.title_chosen ?? h.title}&gt;</button> · Stufe {h.level}
          </p>
          <p className="text-xs text-muted">
            <button type="button" onClick={() => setChoosing(true)} className="font-semibold underline decoration-dotted underline-offset-4" style={{ color: "var(--wow-gold-soft)" }}>
              {h.spec_label ?? "Spezialisierung wählen"}
            </button>
            {h.spec_chosen ? " · Fokus" : " · automatisch"} — {h.class_desc}
          </p>
          <div className="relative mt-2"><BuffBar buffs={data.buffs} /></div>
        </div>
        <div className="text-right tabular-nums">
          <p className="font-display text-[11px] uppercase tracking-wider text-muted">Diese Woche</p>
          <p className="font-display text-2xl font-bold" style={{ color: TIP_YELLOW }}>+{de0(h.week_xp)} EP</p>
          <p className="text-[11px] text-muted">noch {de0(h.next - h.xp)} bis Stufe {h.level + 1}</p>
        </div>
      </div>
      <div className="mt-4"><XpBar data={data} /></div>
      <div className="wow-rule my-4" />
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <p className="mb-1.5 font-display text-[11px] uppercase tracking-wider text-muted">Klasse · Anteil der EP (90 T)</p>
          <div className="flex h-2.5 overflow-hidden rounded-full border border-black">
            {shares.map(([k, v, c]) => <div key={k} style={{ width: `${v * 100}%`, background: c }} title={`${k} ${Math.round(v * 100)} %`} />)}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-x-3 text-[11px] text-muted">
            {shares.map(([k, v, c]) => <span key={k}><span className="mr-1 inline-block h-2 w-2 rounded-sm align-middle" style={{ background: c }} />{k} {Math.round(v * 100)} %</span>)}
          </div>
        </div>
        <div>
          <p className="mb-1.5 font-display text-[11px] uppercase tracking-wider text-muted">Spezialisierung · Neigung</p>
          {Object.keys(h.spec_scores).length ? (
            <div className="space-y-1">
              {Object.entries(h.spec_scores).map(([k, v]) => (
                <div key={k} className="flex items-center gap-2 text-[11px]">
                  <span className={`w-16 shrink-0 ${k === h.spec ? "font-bold" : "text-muted"}`} style={k === h.spec ? { color: TIP_YELLOW } : undefined}>{SPEC_SHORT[k] ?? k}</span>
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[#0a0807]">
                    <div className="h-full rounded-full" style={{ width: `${v * 100}%`, background: k === h.spec ? h.class_color : "#4b3a22" }} />
                  </div>
                  <span className="w-8 text-right tabular-nums text-muted">{Math.round(v * 100)}</span>
                </div>
              ))}
            </div>
          ) : <p className="text-xs text-muted">{h.spec_desc}</p>}
        </div>
      </div>
      {choosing && <SpecChooser data={data} onChoose={onSpec} onClose={() => setChoosing(false)} />}
    </Card>
  );
}
const SPEC_SHORT: Record<string, string> = { ausdauer: "Ausdauer", tempo: "Tempo", last: "Last", strecke: "Strecke" };

// --- Charakterfenster: Ausrüstung links/rechts, Werte in der Mitte --------------------------
function StatRow({ a }: { a: HeroAttribute }) {
  return (
    <div className="py-1">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[13px]" style={{ color: TIP_YELLOW }}>{a.label}</span>
        <span className="font-display text-[15px] font-bold tabular-nums text-white">
          {a.score ?? "–"}
          {a.delta != null && a.delta !== 0 && <span className={`ml-1.5 text-[11px] ${a.delta > 0 ? "text-good" : "text-bad"}`}>{a.delta > 0 ? "+" : "−"}{Math.abs(a.delta)}</span>}
        </span>
      </div>
      <p className="truncate text-[10.5px] text-muted" title={a.source}>{a.value}</p>
    </div>
  );
}

export function HeroCharacter({ data, gear }: { data: Hero; gear: Gear }) {
  const { bind, node } = useItemTip(gear);
  const [busy, setBusy] = useState(false);
  const upgrades = data.inventory.filter((it) => !it.equipped && it.ilvl > (gear.equipment[it.slot]?.ilvl ?? 0));
  const upgradeSlots = new Set(upgrades.map((it) => it.slot)).size;
  function target(slot: string) {
    const item = gear.equipment[slot];
    return <div key={slot} className="rounded-md transition"
                style={gear.dragging === slot ? { boxShadow: `0 0 0 2px ${GOLD}, 0 0 12px ${GOLD}` } : undefined}
                onDragOver={(e) => { if (gear.dragging === slot) e.preventDefault(); }}
                onDrop={(e) => {
                  e.preventDefault();
                  const raw = e.dataTransfer.getData(DRAG_TYPE);
                  gear.setDragging(null);
                  if (!raw) return;
                  const dropped = JSON.parse(raw) as { id: string; slot: string };
                  if (dropped.slot === slot) gear.equip(dropped.id);
                }}>
      <Slot slot={slot} item={item} bind={item && bind(item)} />
    </div>;
  }
  const column = (slots: string[]) => <div className="flex flex-col gap-1.5">{slots.map(target)}</div>;
  return (
    <Card>
      <div className="flex items-start justify-between gap-2">
        <CardTitle title="Charakter" sub="Anlegen: in den Platz ziehen, Rechtsklick oder antippen · Werte 0–100, ± zu vor 30 T" />
        {upgradeSlots > 0 && (
          <button type="button" disabled={busy} className={`${BTN} shrink-0`} style={{ ...BTN_STYLE, color: "#1eff00" }}
                  onClick={async () => { setBusy(true); try { await gear.equipBest(); } finally { setBusy(false); } }}>
            ▲ Beste anlegen ({upgradeSlots})
          </button>
        )}
      </div>
      <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-stretch gap-3">
        {column(LEFT_SLOTS)}
        <div className="relative min-w-0 rounded-md border border-[#2c2216]"
             style={{ background: `radial-gradient(ellipse at 50% 85%, color-mix(in srgb, ${data.hero.class_color} 22%, transparent), rgba(0,0,0,.35) 70%)` }}>
          <p className="absolute inset-x-0 top-1.5 z-10 text-center font-display text-[11px] uppercase tracking-wider text-muted">
            Ø Gegenstandsstufe <b className="text-sm" style={{ color: TIP_YELLOW }}>{data.ilvl_avg ?? "–"}</b>
          </p>
          <div className="h-[244px] px-2 pb-1 pt-7"><HeroFigure color={data.hero.class_color} equipment={gear.equipment}
            aura={(() => { const s = data.sets.find((x) => x.bonus); return s ? { color: s.color, pulse: s.equipped >= 4 } : null; })()} /></div>
        </div>
        {column(RIGHT_SLOTS)}
      </div>
      <div className="wow-rule my-4" />
      <div className="grid items-center gap-3 sm:grid-cols-2">
        <div>
          <AttributeRadar items={data.attributes} color={data.hero.class_color} />
          <p className="text-center text-[10px] text-muted">gestrichelt: vor 30 Tagen</p>
        </div>
        <div className="rounded-md border border-[#2c2216] bg-black/30 px-3 py-1">
          {data.attributes.map((a) => <StatRow key={a.key} a={a} />)}
        </div>
      </div>
      {data.sets.some((x) => x.owned >= 2 || x.equipped >= 1) && <>
        <div className="wow-rule my-4" />
        <p className="mb-1.5 font-display text-[11px] uppercase tracking-wider text-muted">Garnituren · ab 2 angelegten Teilen Aura, ab 4 pulsierend</p>
        <div className="flex flex-wrap gap-1.5">
          {data.sets.filter((x) => x.owned >= 2 || x.equipped >= 1).map((x) => (
            <span key={x.suffix} className="rounded border px-2 py-1 text-[11px]"
                  style={{ borderColor: x.bonus ? x.color : "#3a2d1a", color: x.bonus ? x.color : "var(--color-muted)" }}>
              {x.name} · {x.equipped}/{x.owned} angelegt{x.bonus ? ` · ${x.bonus}` : ""}
            </span>
          ))}
        </div>
      </>}
      {node}
    </Card>
  );
}

// --- Wochentruhe --------------------------------------------------------------------------
function VaultChoice({ vault, title, onClaim }: { vault: HeroVault; title: string; onClaim: (week: string, slot: number) => Promise<void> }) {
  const { bind, node } = useItemTip();
  const [pending, setPending] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function take(slot: number) {
    if (pending !== slot) { setPending(slot); return; }
    setBusy(true); setErr(null);
    try { await onClaim(vault.week, slot); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); setBusy(false); }
  }
  return (
    <div className="rounded-md border border-[#3a2d1a] bg-black/25 p-3">
      <p className="mb-2 font-display text-sm" style={{ color: "var(--wow-gold-soft)" }}>{title}</p>
      <div className="space-y-2">
        {vault.slots.map((s) => (
          <div key={s.slot} className="flex min-w-0 items-center gap-2.5">
            {s.unlocked ? <>
              <Slot item={s.item} bind={bind(s.item)} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-semibold" style={{ color: rc(s.item.rarity) }}>{s.item.name}</span>
                <span className="block text-[11px] text-muted">{s.item.slot_label} · Stufe {s.item.ilvl}</span>
              </span>
              <button type="button" disabled={busy} onClick={() => take(s.slot)}
                      className="w-24 shrink-0 rounded border px-2 py-1.5 font-display text-xs font-bold"
                      style={pending === s.slot
                        ? { background: "linear-gradient(180deg, #b8131a, #6e0b0f)", borderColor: GOLD, color: TIP_YELLOW }
                        : { background: "linear-gradient(180deg, #3b2c18, #1d150c)", borderColor: "#6b5230", color: TIP_YELLOW }}>
                {pending === s.slot ? "Sicher?" : "Wählen"}
              </button>
            </> : <>
              <span className="wow-slot text-[#4b3a22]"><Icon size={20}>{LOCK}</Icon></span>
              <span className="text-[11px] text-muted">gesperrt · ab {s.threshold} Läufen</span>
            </>}
          </div>
        ))}
      </div>
      {err && <p className="mt-2 text-xs text-bad">{err}</p>}
      {node}
    </div>
  );
}

export function HeroVaultCard({ data, onClaim }: { data: Hero; onClaim: (week: string, slot: number) => Promise<void> }) {
  const cur = data.vault.current;
  return (
    <Card>
      <CardTitle title="Wochentruhe" sub="Slots bei 1 · 3 · 4 Läufen · Wahl ab Montag · Krankheitstage senken die Schwellen" />
      <div className="grid grid-cols-3 gap-2">
        {cur.slots.map((s) => {
          const col = rc(s.item.rarity);
          return (
            <div key={s.slot} className={`grid h-28 place-items-center rounded-md border text-center ${s.unlocked ? "wow-pulse" : ""}`}
                 style={s.unlocked
                   ? { borderColor: col, background: `radial-gradient(circle at 50% 40%, color-mix(in srgb, ${col} 28%, transparent), #0b0907 75%)`, color: col, ["--glow" as string]: col }
                   : { borderColor: "#3a2d1a", background: "radial-gradient(circle at 50% 40%, #1d1712, #0b0907 75%)", color: "#5b4526" }}>
              <div>
                <Icon size={30}>{s.unlocked ? CHEST : LOCK}</Icon>
                <p className="mt-1 font-display text-[11px] font-bold">{s.unlocked ? s.item.rarity_label : `${Math.min(cur.runs, s.threshold)} / ${s.threshold}`}</p>
                <p className="text-[10px] text-muted">{s.threshold} {s.threshold === 1 ? "Lauf" : "Läufe"}</p>
              </div>
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-[11px] text-muted">{cur.runs} {cur.runs === 1 ? "Lauf" : "Läufe"} diese Woche{cur.sick_days > 0 ? ` · ${cur.sick_days} Krankheitstage, Schwellen gesenkt` : ""}</p>
      {(data.vault.veteran || data.vault.claimable.length > 0) && (
        <div className="mt-4 space-y-3">
          {data.vault.veteran && <VaultChoice vault={data.vault.veteran} title="Veteranentruhe · für deine bisherige Reise" onClaim={onClaim} />}
          {data.vault.claimable.map((v) => <VaultChoice key={v.week} vault={v} title={`Woche vom ${dm(v.week)} · ${v.runs} Läufe`} onClaim={onClaim} />)}
        </div>
      )}
    </Card>
  );
}

// --- Taschen ------------------------------------------------------------------------------
export function HeroBags({ items, gear }: { items: HeroItem[]; gear: Gear }) {
  const { bind, node } = useItemTip(gear);
  const loose = items.filter((it) => !it.equipped);
  const size = Math.max(16, Math.ceil(loose.length / 8) * 8);
  return (
    <Card>
      <div className="flex items-start justify-between gap-2">
        <CardTitle title={`Taschen · ${loose.length} / ${size}`} sub="Jeder Lauf droppt Beute – Seltenheit verdient, Gegenstand zufällig. ▲ = besser als angelegt." />
        <span className="shrink-0 rounded border border-[#3a2d1a] px-2 py-1 text-[11px]" style={{ color: "#b552f7" }} title="Aus entzauberten Gegenständen; wertet Gegenstände auf">✦ {gear.dust} Arkanstaub</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {Array.from({ length: size }, (_, i) => loose[i]
          ? <Slot key={loose[i].id} item={loose[i]} bind={bind(loose[i])} upgrade={loose[i].ilvl > (gear.equipment[loose[i].slot]?.ilvl ?? 0)} isNew={gear.isNew(loose[i].id)} />
          : <span key={`empty-${i}`} className="wow-slot" />)}
      </div>
      {node}
    </Card>
  );
}

// --- Kampflog im Chat-Stil ----------------------------------------------------------------
function LogLine({ e }: { e: Hero["log"][number] }) {
  const name = (color: string) => <span style={{ color }}>[{e.name}]</span>;
  switch (e.kind) {
    case "level": return <span style={{ color: TIP_YELLOW }}>Glückwunsch! Ihr habt Stufe {e.level} erreicht{e.name ? ` – ${e.name}` : ""}.</span>;
    case "klasse": return <span style={{ color: "#ff7d0a" }}>Ihr folgt nun dem Pfad: {e.name}.</span>;
    case "erfolg": return <span style={{ color: "#ffff00" }}>Ihr habt den Erfolg {name("#ffff00")} errungen!{e.xp ? ` (+${e.xp} EP)` : ""}</span>;
    case "beute": return <span style={{ color: "#00aa00" }}>Ihr erhaltet Beute: {name(e.rarity ? rc(e.rarity) : "#fff")}.</span>;
    case "auftrag": return <span style={{ color: "#ffd100" }}>Auftrag abgeschlossen: {name("#ffd100")}{e.xp ? ` (+${e.xp} EP)` : ""}</span>;
    case "boss": return <span style={{ color: "#ff6a5c" }}>Boss besiegt: {name("#ff6a5c")}!{e.xp ? ` (+${e.xp} EP)` : ""}</span>;
    case "instanz": return <span style={{ color: "#3d95ff" }}>Instanz bezwungen: {name("#3d95ff")}{e.xp ? ` (+${e.xp} EP)` : ""}</span>;
    case "truhe": return <span style={{ color: "#00aa00" }}>Ihr wählt aus der Truhe: {name(e.rarity ? rc(e.rarity) : "#fff")}.</span>;
    default: return <span>{e.text}</span>;
  }
}

export function HeroLog({ data, listClass = "max-h-96" }: { data: Hero; listClass?: string }) {
  return (
    <Card>
      <CardTitle title="Kampflog" sub="Stufenaufstiege, Klassenwechsel, Beute und Erfolge" />
      <ol className={`wow-chat space-y-0.5 overflow-y-auto p-2.5 ${listClass}`}>
        {data.log.map((e, i) => (
          <li key={i}><span className="mr-1.5 tabular-nums text-[#8a8a8a]">[{dm(e.date)}]</span><LogLine e={e} /></li>
        ))}
      </ol>
    </Card>
  );
}

export function HeroRules({ data }: { data: Hero }) {
  const x = data.xp_sources;
  const rows: [string, number][] = [["Laufen", x.laufen], ["Kraft", x.kraft], ["Alltag", x.alltag], ["Erfolge", x.erfolge], ["Ausgeruht-Bonus", x.ruhebonus], ["Buffs", x.buffs], ["Fokus", x.fokus], ["Talente", x.talente], ["Aufträge", x.auftraege], ["Bosse", x.bosse], ["Instanzen", x.instanzen]];
  return (
    <Card>
      <CardTitle title="Woher deine EP stammen" sub={`Gesamt ${de0(data.hero.xp)} EP seit Beginn deiner Daten`} />
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm tabular-nums">
        {rows.map(([k, v]) => <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="text-right font-semibold" style={{ color: TIP_YELLOW }}>{de0(v)}</dd></div>)}
      </dl>
      <div className="wow-rule my-3" />
      <ul className="list-disc space-y-1 pl-4 text-[11px] text-muted">
        <li>Lauf: 2 EP je Minute × Puls-Zone (Z1 1,0 · Z2 1,2 · Z3 1,5 · Z4 1,8).</li>
        <li>Kraft: 6 EP je Arbeitssatz, höchstens 180 je Training.</li>
        <li>Ab dem {data.rules.runs_full_xp + 1}. Lauf bzw. {data.rules.workouts_full_xp + 1}. Krafttraining einer Woche nur halbe EP – Erholung zählt.</li>
        <li>Ruhe- und Krankheitstage laden {data.rules.rest_per_day} EP „Ausgeruht“, das die nächsten Trainings-EP verdoppelt.</li>
        <li>Alltag: Schritte über 5.000, Rad und Gehen. Erfolge zählen mit ihren Punkten.</li>
        <li>Buffs: Protein-Ziel am Vortag (Wohlgenährt) und eine Nacht ab 7 h (Erholt) geben je +5 % Trainings-EP.</li>
        <li>Fokus: Läufe passend zur gewählten Spezialisierung geben ab dem Tag der Wahl +10 %.</li>
        <li>Talente wirken ab dem Tag der Wahl; Wochenaufträge geben je 150 EP.</li>
        <li>Monatsbosse geben 400 EP, jeder Instanz-Boss 50 EP.</li>
      </ul>
    </Card>
  );
}

// --- Truhe öffnen: Lichtstrahlen, Gegenstand springt heraus --------------------------------
export function LootReveal({ item, onClose }: { item: HeroItem; onClose: () => void }) {
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);
  const col = rc(item.rarity);
  return (
    <div role="dialog" aria-modal="true" aria-label={`Beute: ${item.name}`} onClick={onClose}
         className="ach-fade fixed inset-0 z-50 grid place-items-center overflow-hidden bg-black/75 p-4">
      <div className="relative grid w-full max-w-sm place-items-center" onClick={(e) => e.stopPropagation()}>
        <div className="wow-rays pointer-events-none absolute left-1/2 top-[48px] h-[420px] w-[420px] -ml-[210px] -mt-[210px] rounded-full"
             style={{ ["--ray" as string]: `color-mix(in srgb, ${col} 45%, transparent)` }} />
        <div className="wow-pop relative"><Slot item={item} size={96} /></div>
        <div className="wow-rise relative mt-5 w-full">
          <p className="mb-2 text-center font-display text-xs uppercase tracking-[.3em] text-muted">Ihr erhaltet Beute</p>
          <div className="wow-tip"><ItemTooltipBody item={item} /></div>
          <div className="mt-4 text-center">
            <button type="button" autoFocus onClick={onClose} className={BTN} style={BTN_STYLE}>Einsacken</button>
          </div>
        </div>
      </div>
    </div>
  );
}
