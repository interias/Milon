"use client";

import { useEffect, useState } from "react";
import type { Achievements as AchData, Achievement, Rarity } from "@/lib/api";
import { Card } from "@/components/ui";
import { de0, dm } from "@/lib/format";

// WoW-Loot-Seltenheiten (grau→…→rot). Farbe kommt aus globals.css (--rar-*).
const RARITY_ORDER: Rarity[] = ["grau", "weiss", "gruen", "blau", "lila", "orange", "rot"];
const RARITY_LABEL: Record<Rarity, string> = {
  grau: "Schrott", weiss: "Gewöhnlich", gruen: "Ungewöhnlich", blau: "Selten",
  lila: "Episch", orange: "Legendär", rot: "Artefakt",
};
const rc = (r: Rarity) => `var(--rar-${r})`;

const CATS: { key: string; label: string; icon: string }[] = [
  { key: "distanz", label: "Distanz", icon: "🏃" },
  { key: "dauer", label: "Dauer", icon: "⏱️" },
  { key: "tempo", label: "Tempo & PR", icon: "⚡" },
  { key: "herzfrequenz", label: "Herzfrequenz", icon: "❤️" },
  { key: "effizienz", label: "Effizienz", icon: "🫀" },
  { key: "puls_pace", label: "Puls ↔ Pace", icon: "📈" },
  { key: "vo2max", label: "VO₂max", icon: "🫁" },
  { key: "wochenvolumen", label: "Wochenvolumen", icon: "📊" },
  { key: "volumen", label: "Häufigkeit", icon: "🔢" },
  { key: "kumulativ", label: "Kumulativ", icon: "🌍" },
  { key: "serie", label: "Serien", icon: "🔥" },
  { key: "streak", label: "Streaks", icon: "📆" },
  { key: "kalender", label: "Kalender", icon: "📅" },
  { key: "comeback", label: "Comeback", icon: "💪" },
  { key: "cross-domain", label: "Cross-Domain", icon: "🤸" },
  { key: "fun", label: "Fun & Kurios", icon: "✨" },
  { key: "meta", label: "Meta & Sammlung", icon: "🏆" },
];
const CAT_LABEL = Object.fromEntries(CATS.map((c) => [c.key, c.label]));
const CAT_ICON = Object.fromEntries(CATS.map((c) => [c.key, c.icon]));

// --- Detail-Modal: Erklärung + Symbolik (Flavor) ---
function Detail({ a, onClose }: { a: Achievement; onClose: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  const col = rc(a.rarity);
  const pct = Math.round(a.progress * 100);
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4 ach-fade"
      onClick={onClose} role="dialog" aria-modal="true" aria-label={a.name}
    >
      <div
        className="w-full max-w-md overflow-hidden rounded-xl border bg-surface shadow-2xl"
        style={{ borderColor: col }} onClick={(e) => e.stopPropagation()}
      >
        {/* Kopf mit Seltenheits-Verlauf */}
        <div className="flex items-center gap-4 p-5" style={{ background: `linear-gradient(180deg, ${col}22, transparent)` }}>
          <div
            className="grid h-16 w-16 shrink-0 place-items-center rounded-lg text-4xl"
            style={{
              background: a.earned ? `${col}1f` : "var(--color-surface-alt)",
              boxShadow: `inset 0 0 0 2px ${col}`,
              filter: a.earned ? "none" : "grayscale(1)", opacity: a.earned ? 1 : 0.55,
            }}
          >
            {a.earned ? a.icon : "🔒"}
          </div>
          <div className="min-w-0">
            <p className="text-[11px] font-bold uppercase tracking-wider" style={{ color: col }}>
              {RARITY_LABEL[a.rarity]} · {a.points} Punkte
            </p>
            <h3 className="font-display text-xl font-extrabold leading-tight" style={{ color: col }}>{a.name}</h3>
            <p className="mt-0.5 text-[11px] text-muted">{CAT_ICON[a.category]} {CAT_LABEL[a.category] ?? a.category}</p>
          </div>
        </div>

        <div className="space-y-3 px-5 pb-5">
          {a.flavor && (
            <p className="border-l-2 pl-3 text-sm italic text-muted" style={{ borderColor: col }}>„{a.flavor}“</p>
          )}
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">Bedingung</p>
            <p className="text-sm">{a.desc}</p>
          </div>
          {a.earned ? (
            <p className="rounded-lg px-3 py-2 text-sm font-semibold" style={{ background: `${col}1a`, color: col }}>
              ✓ Freigeschaltet{a.earned_date ? ` am ${dm(a.earned_date)}` : ""}
            </p>
          ) : (
            <div>
              <div className="mb-1 flex justify-between text-[11px] text-muted">
                <span>Fortschritt{a.progress_label ? ` · ${a.progress_label}` : ""}</span>
                <span>{pct}%</span>
              </div>
              <div className="h-2.5 w-full overflow-hidden rounded-full bg-surface-alt" style={{ boxShadow: "inset 0 0 0 1px var(--color-line)" }}>
                <div className="h-full rounded-full" style={{ width: `${pct}%`, background: col }} />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// --- Kompakte, klickbare Kachel ---
function Tile({ a, onClick }: { a: Achievement; onClick: () => void }) {
  const col = rc(a.rarity);
  const pct = Math.round(a.progress * 100);
  return (
    <button
      type="button" onClick={onClick} title={a.name}
      className="group relative flex items-center gap-2.5 overflow-hidden rounded-lg border bg-surface p-2 pl-2.5 text-left transition hover:brightness-[1.03] focus:outline-none focus-visible:ring-2"
      style={{ borderColor: a.earned ? col : "var(--color-line)", boxShadow: a.earned ? `inset 3px 0 0 ${col}` : "inset 3px 0 0 var(--color-line)" }}
    >
      <span
        className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-xl"
        style={{
          background: a.earned ? `${col}1f` : "var(--color-surface-alt)",
          boxShadow: `inset 0 0 0 1.5px ${a.earned ? col : "var(--color-line)"}`,
          filter: a.earned ? "none" : "grayscale(1)", opacity: a.earned ? 1 : 0.5,
        }}
      >
        {a.earned ? a.icon : "🔒"}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline justify-between gap-1.5">
          <span className={`truncate text-[12.5px] font-semibold ${a.earned ? "" : "text-muted"}`}
                style={a.earned ? { color: col } : undefined}>{a.name}</span>
          <span className="shrink-0 text-[10px] font-bold tabular-nums text-muted">{a.points}</span>
        </span>
        {a.earned ? (
          <span className="block truncate text-[10px] text-muted">{RARITY_LABEL[a.rarity]}{a.earned_date ? ` · ${dm(a.earned_date)}` : ""}</span>
        ) : (
          <span className="mt-1 block h-1 w-full overflow-hidden rounded-full bg-surface-alt">
            <span className="block h-full rounded-full" style={{ width: `${pct}%`, background: col, opacity: 0.7 }} />
          </span>
        )}
      </span>
    </button>
  );
}

export function AchievementsSummary({ data }: { data: AchData }) {
  const s = data.summary;
  const [sel, setSel] = useState<Achievement | null>(null);
  const artifacts = data.achievements.filter((a) => a.rarity === "rot");
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted">Läufer-Level {s.level}</p>
          <p className="font-display text-2xl font-extrabold tracking-tight">{s.title}</p>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted">Punkte</p>
          <p className="font-display text-3xl font-extrabold text-accent">
            {de0(s.points)}<span className="ml-1 text-sm font-semibold text-muted">/ {de0(s.points_possible)}</span>
          </p>
        </div>
        <div>
          <p className="text-[11px] uppercase tracking-wide text-muted">Trophäen</p>
          <p className="font-display text-3xl font-extrabold">🏆 {s.earned}<span className="ml-1 text-sm font-semibold text-muted">/ {s.total}</span></p>
        </div>
        {s.next_points != null && (
          <div className="min-w-[180px] flex-1">
            <p className="mb-1 flex justify-between text-[11px] text-muted"><span>bis Level {s.level + 1}</span><span>noch {de0(s.to_next)} P</span></p>
            <div className="h-2.5 w-full overflow-hidden rounded-full bg-surface-alt" style={{ boxShadow: "inset 0 0 0 1px var(--color-line)" }}>
              <div className="h-full rounded-full bg-accent" style={{ width: `${Math.round(s.progress * 100)}%` }} />
            </div>
          </div>
        )}
      </div>

      {/* Seltenheits-Verteilung */}
      <div className="mt-4 flex flex-wrap gap-x-3 gap-y-1.5 border-t border-line pt-3">
        {RARITY_ORDER.map((r) => {
          const v = s.rarity_counts?.[r];
          if (!v || !v.total) return null;
          return (
            <span key={r} className="flex items-center gap-1.5 text-[11px] text-muted">
              <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: rc(r) }} />
              <span style={{ color: rc(r) }} className="font-semibold">{RARITY_LABEL[r]}</span>
              <span className="tabular-nums">{v.earned}/{v.total}</span>
            </span>
          );
        })}
      </div>

      {/* Artefakt-Vorschau: die (fast) unerreichbaren Fernziele */}
      {artifacts.length > 0 && (
        <div className="mt-3 border-t border-line pt-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide" style={{ color: rc("rot") }}>
            🔴 Artefakt-Vorschau · Fernziele
          </p>
          <div className="flex gap-2 overflow-x-auto pb-1">
            {artifacts.map((a) => (
              <button
                key={a.id} type="button" onClick={() => setSel(a)} title={`${a.name} — ${a.desc}`}
                className="grid h-11 w-11 shrink-0 place-items-center rounded-lg text-2xl transition hover:scale-105"
                style={{
                  background: `${rc("rot")}12`, boxShadow: `inset 0 0 0 1.5px ${rc("rot")}`,
                  filter: a.earned ? "none" : "grayscale(1)", opacity: a.earned ? 1 : 0.6,
                }}
              >
                {a.earned ? a.icon : "🔒"}
              </button>
            ))}
          </div>
        </div>
      )}
      {sel && <Detail a={sel} onClose={() => setSel(null)} />}
    </Card>
  );
}

export function AchievementsGrid({ data }: { data: AchData }) {
  const [onlyEarned, setOnlyEarned] = useState(false);
  const [fRarity, setFRarity] = useState<Rarity | "alle">("alle");
  const [sel, setSel] = useState<Achievement | null>(null);

  let items = data.achievements;
  if (onlyEarned) items = items.filter((a) => a.earned);
  if (fRarity !== "alle") items = items.filter((a) => a.rarity === fRarity);

  const chip = "rounded-full border border-line px-2.5 py-1 text-[11px] font-semibold transition";
  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="mr-auto">
          <h2 className="font-display text-lg font-extrabold tracking-tight">Erfolge</h2>
          <p className="text-xs text-muted">Sammelbare Trophäen im Loot-Stil — anklicken für Symbolik &amp; Details</p>
        </div>
        <button type="button" onClick={() => setOnlyEarned((v) => !v)}
          className={`${chip} ${onlyEarned ? "bg-accent text-white" : "text-muted hover:bg-surface-alt"}`}>
          {onlyEarned ? "nur erreichte ✓" : "nur erreichte"}
        </button>
      </div>

      {/* Rarität-Filter (Loot-Farben) */}
      <div className="mb-4 flex flex-wrap gap-1.5">
        <button type="button" onClick={() => setFRarity("alle")}
          className={`${chip} ${fRarity === "alle" ? "bg-ink text-bg" : "text-muted hover:bg-surface-alt"}`}
          style={fRarity === "alle" ? { background: "var(--color-ink)", color: "var(--color-bg)" } : undefined}>
          Alle
        </button>
        {RARITY_ORDER.map((r) => {
          const v = data.summary.rarity_counts?.[r];
          if (!v || !v.total) return null;
          const on = fRarity === r;
          return (
            <button key={r} type="button" onClick={() => setFRarity(on ? "alle" : r)}
              className={chip}
              style={{
                borderColor: rc(r), color: on ? "#fff" : rc(r),
                background: on ? rc(r) : `var(--rar-${r})14`,
              }}>
              {RARITY_LABEL[r]} <span className="tabular-nums opacity-80">{v.earned}/{v.total}</span>
            </button>
          );
        })}
      </div>

      <div className="space-y-5">
        {CATS.map((cat) => {
          const group = items
            .filter((a) => a.category === cat.key)
            .sort((a, b) => (b.earned ? 1 : 0) - (a.earned ? 1 : 0)
              || RARITY_ORDER.indexOf(a.rarity) - RARITY_ORDER.indexOf(b.rarity) || a.points - b.points);
          if (!group.length) return null;
          const all = data.achievements.filter((a) => a.category === cat.key);
          const done = all.filter((a) => a.earned).length;
          return (
            <div key={cat.key}>
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
                <span>{cat.icon}</span> {cat.label}
                <span className="text-[11px] font-normal text-muted tabular-nums">{done}/{all.length}</span>
              </h3>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {group.map((a) => <Tile key={a.id} a={a} onClick={() => setSel(a)} />)}
              </div>
            </div>
          );
        })}
      </div>

      {sel && <Detail a={sel} onClose={() => setSel(null)} />}
    </>
  );
}
