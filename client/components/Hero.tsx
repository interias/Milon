"use client";

import { useState } from "react";
import type { Hero, HeroAttribute, HeroItem, HeroVault, Rarity } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
import { de0, dm } from "@/lib/format";

const rc = (r: Rarity) => `var(--rar-${r})`;

// Linien-Icons (lucide-Pfade, currentColor) für Ausrüstungs-Slots und Klassen-Wappen.
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

export function Icon({ children, size = 20 }: { children: React.ReactNode; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
              strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>;
}

function Bar({ value, color, rested }: { value: number; color: string; rested?: number }) {
  return (
    <div className="relative h-3 w-full overflow-hidden rounded-full bg-surface-alt" style={{ boxShadow: "inset 0 0 0 1px var(--color-line)" }}>
      {rested != null && rested > 0 && (
        <div className="absolute inset-y-0 rounded-full" title="Ruhebonus"
             style={{ left: `${value * 100}%`, width: `${Math.min(1 - value, rested) * 100}%`,
                      background: `repeating-linear-gradient(135deg, ${color}55 0 4px, ${color}22 4px 8px)` }} />
      )}
      <div className="relative h-full rounded-full transition-[width] duration-700" style={{ width: `${value * 100}%`, background: color }} />
    </div>
  );
}

// --- Charakterbogen ---------------------------------------------------------------------
export function HeroHeader({ data }: { data: Hero }) {
  const h = data.hero;
  const span = h.next - h.floor;
  const shares: [string, number, string][] = [
    ["Laufen", h.shares.laufen, "var(--color-accent)"], ["Kraft", h.shares.kraft, "#a07a52"], ["Alltag", h.shares.alltag, "var(--color-accent-2)"],
  ];
  return (
    <Card className="overflow-hidden">
      <div className="-m-4 mb-0 p-4 sm:-m-5 sm:p-5" style={{ background: `linear-gradient(180deg, ${h.class_color}1c, transparent)` }}>
        <div className="flex flex-wrap items-center gap-4">
          <div className="grid h-16 w-16 shrink-0 place-items-center rounded-xl" style={{ color: h.class_color, background: `${h.class_color}1f`, boxShadow: `inset 0 0 0 2px ${h.class_color}` }}>
            <Icon size={34}>{CLASS_ICON[h.class]}</Icon>
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-bold uppercase tracking-wider text-muted">Level {h.level} · {h.title}</p>
            <h2 className="font-display text-2xl font-extrabold tracking-tight sm:text-3xl" style={{ color: h.class_color }}>{h.class_label}</h2>
            <p className="text-sm text-muted">{h.spec_label ?? "Ohne Spezialisierung"} · <span className="text-xs">{h.class_desc}</span></p>
          </div>
          <div className="text-right tabular-nums">
            <p className="text-[11px] uppercase tracking-wide text-muted">Diese Woche</p>
            <p className="font-display text-2xl font-extrabold text-accent">+{de0(h.week_xp)} XP</p>
          </div>
        </div>
        <div className="mt-4">
          <div className="mb-1 flex flex-wrap justify-between gap-2 text-[11px] text-muted tabular-nums">
            <span>{de0(h.xp - h.floor)} / {de0(span)} XP · noch {de0(h.next - h.xp)} bis Level {h.level + 1}</span>
            <span title="Ruhe- und Krankheitstage laden den Bonus; er verdoppelt die nächsten Trainings-XP.">
              Ruhebonus <b className="text-ink">{de0(h.rested)}</b> / {de0(h.rested_cap)} XP
            </span>
          </div>
          <Bar value={h.progress} color={h.class_color} rested={h.rested / span} />
        </div>
      </div>
      <div className="mt-4 grid gap-4 border-t border-line pt-4 sm:grid-cols-2">
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted">Klasse · Anteil der XP (90 T)</p>
          <div className="flex h-2.5 overflow-hidden rounded-full">
            {shares.map(([k, v, c]) => <div key={k} style={{ width: `${v * 100}%`, background: c }} title={`${k} ${Math.round(v * 100)} %`} />)}
          </div>
          <div className="mt-1.5 flex flex-wrap gap-x-3 text-[11px] text-muted">
            {shares.map(([k, v, c]) => <span key={k}><span className="mr-1 inline-block h-2 w-2 rounded-sm align-middle" style={{ background: c }} />{k} {Math.round(v * 100)} %</span>)}
          </div>
        </div>
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted">Lauf-Spezialisierung · Neigung</p>
          {Object.keys(h.spec_scores).length ? (
            <div className="space-y-1">
              {Object.entries(h.spec_scores).map(([k, v]) => (
                <div key={k} className="flex items-center gap-2 text-[11px]">
                  <span className={`w-16 shrink-0 ${k === h.spec ? "font-bold text-ink" : "text-muted"}`}>{SPEC_SHORT[k] ?? k}</span>
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-alt">
                    <div className="h-full rounded-full" style={{ width: `${v * 100}%`, background: k === h.spec ? h.class_color : "var(--color-line)" }} />
                  </div>
                  <span className="w-8 text-right tabular-nums text-muted">{Math.round(v * 100)}</span>
                </div>
              ))}
            </div>
          ) : <p className="text-xs text-muted">{h.spec_desc}</p>}
        </div>
      </div>
    </Card>
  );
}
const SPEC_SHORT: Record<string, string> = { ausdauer: "Ausdauer", tempo: "Tempo", last: "Last", strecke: "Strecke" };

// --- Attribute --------------------------------------------------------------------------
export function HeroAttributes({ items }: { items: HeroAttribute[] }) {
  return (
    <Card>
      <CardTitle title="Attribute" sub="Aus deinen Messwerten abgeleitet · 0–100 · Δ zu vor 30 Tagen" />
      <div className="space-y-3">
        {items.map((a) => (
          <div key={a.key}>
            <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
              <span className="font-semibold">{a.label}</span>
              <span className="text-[11px] text-muted tabular-nums">
                {a.value}
                {a.delta != null && a.delta !== 0 && (
                  <b className={`ml-2 ${a.delta > 0 ? "text-good" : "text-bad"}`}>{a.delta > 0 ? "▲" : "▼"} {Math.abs(a.delta)}</b>
                )}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-alt">
                {a.score != null && <div className="h-full rounded-full bg-accent transition-[width] duration-700" style={{ width: `${a.score}%` }} />}
              </div>
              <span className="w-7 text-right font-display text-sm font-extrabold tabular-nums">{a.score ?? "–"}</span>
            </div>
            <p className="text-[10px] text-muted">{a.source}</p>
          </div>
        ))}
      </div>
    </Card>
  );
}

// --- Gegenstände ------------------------------------------------------------------------
export function ItemTile({ item, onClick, dim = false }: { item: HeroItem; onClick?: () => void; dim?: boolean }) {
  const col = rc(item.rarity);
  return (
    <button type="button" onClick={onClick} title={item.name}
            className="flex w-full min-w-0 items-center gap-2.5 rounded-lg border bg-surface p-2 text-left transition hover:brightness-[1.03] focus:outline-none focus-visible:ring-2"
            style={{ borderColor: col, boxShadow: `inset 3px 0 0 ${col}`, opacity: dim ? 0.55 : 1 }}>
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md" style={{ color: col, background: `color-mix(in srgb, ${col} 12%, transparent)`, boxShadow: `inset 0 0 0 1.5px ${col}` }}>
        <Icon size={20}>{SLOT_ICON[item.slot]}</Icon>
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[12.5px] font-semibold" style={{ color: col }}>{item.name}</span>
        <span className="block truncate text-[10px] text-muted">{item.slot_label} · Stufe {item.ilvl} · {dm(item.date)}</span>
      </span>
    </button>
  );
}

export function ItemDetail({ item, onClose }: { item: HeroItem; onClose: () => void }) {
  const col = rc(item.rarity);
  return (
    <RunAnalysisDialog title={item.name} onClose={onClose}>
      <div className="w-full max-w-md overflow-hidden rounded-xl border bg-surface shadow-2xl" style={{ borderColor: col }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-4 p-5" style={{ background: `linear-gradient(180deg, color-mix(in srgb, ${col} 14%, transparent), transparent)` }}>
          <div className="grid h-16 w-16 shrink-0 place-items-center rounded-lg" style={{ color: col, boxShadow: `inset 0 0 0 2px ${col}` }}>
            <Icon size={34}>{SLOT_ICON[item.slot]}</Icon>
          </div>
          <div className="min-w-0">
            <p className="text-[11px] font-bold uppercase tracking-wider" style={{ color: col }}>{item.rarity_label} · {item.slot_label}</p>
            <h3 className="font-display text-xl font-extrabold leading-tight" style={{ color: col }}>{item.name}</h3>
            <p className="mt-0.5 text-[11px] text-muted">Gegenstandsstufe {item.ilvl}</p>
          </div>
        </div>
        <div className="space-y-3 px-5 pb-5 text-sm">
          <p className="border-l-2 pl-3 italic text-muted" style={{ borderColor: col }}>„{item.flavor}“</p>
          <p><span className="text-muted">Herkunft: </span>{SOURCE[item.source]} am {dm(item.date)}{item.run_km ? ` · Lauf ${item.run_km.toLocaleString("de-DE")} km` : ""}</p>
          <p><span className="text-muted">Warum diese Seltenheit: </span>{item.reason}</p>
          {item.lucky && <p className="text-xs font-semibold" style={{ color: col }}>✦ Glücksfund – eine Stufe besser als verdient</p>}
        </div>
      </div>
    </RunAnalysisDialog>
  );
}
const SOURCE: Record<HeroItem["source"], string> = { beute: "Beute nach einem Lauf", truhe: "Wochentruhe", veteran: "Veteranentruhe" };

// --- Wochentruhe ------------------------------------------------------------------------
function VaultChoice({ vault, title, onClaim }: { vault: HeroVault; title: string; onClaim: (week: string, slot: number) => Promise<void> }) {
  const [pending, setPending] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [detail, setDetail] = useState<HeroItem | null>(null);
  async function take(slot: number) {
    if (pending !== slot) { setPending(slot); return; }
    setBusy(true); setErr(null);
    try { await onClaim(vault.week, slot); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); setBusy(false); }
  }
  return (
    <div className="rounded-lg border border-line p-3">
      <p className="mb-2 text-sm font-semibold">{title} <span className="text-xs font-normal text-muted">· wähle einen Gegenstand</span></p>
      <div className="space-y-2">
        {vault.slots.map((s) => (
          <div key={s.slot} className="flex min-w-0 items-center gap-2">
            {s.unlocked ? <>
              <div className="min-w-0 flex-1"><ItemTile item={s.item} onClick={() => setDetail(s.item)} /></div>
              <button type="button" disabled={busy} onClick={() => take(s.slot)}
                      className={`w-24 shrink-0 rounded-md border px-2 py-1.5 text-xs font-semibold ${pending === s.slot ? "border-accent bg-accent text-white" : "border-line hover:border-accent"}`}>
                {pending === s.slot ? "Sicher? Nehmen" : "Wählen"}
              </button>
            </> : <div className="grid h-[52px] flex-1 place-items-center rounded-lg border border-dashed border-line text-[11px] text-muted">gesperrt · ab {s.threshold} Läufen</div>}
          </div>
        ))}
      </div>
      {err && <p className="mt-2 text-xs text-bad">{err}</p>}
      {detail && <ItemDetail item={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

export function HeroVaultCard({ data, onClaim }: { data: Hero; onClaim: (week: string, slot: number) => Promise<void> }) {
  const cur = data.vault.current;
  const max = Math.max(...cur.slots.map((s) => s.threshold));
  return (
    <Card>
      <CardTitle title="Wochentruhe" sub="Slots öffnen sich bei 1 · 3 · 4 Läufen · Wahl ab Montag · Krankheitstage senken die Schwellen" />
      <div className="flex items-center gap-3">
        <div className="flex-1"><Bar value={Math.min(1, cur.runs / max)} color="var(--color-accent)" /></div>
        <span className="text-sm font-semibold tabular-nums">{cur.runs} / {max} Läufe</span>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2">
        {cur.slots.map((s) => {
          const col = rc(s.item.rarity);
          return (
            <div key={s.slot} className="grid h-20 place-items-center rounded-lg border text-center"
                 style={s.unlocked ? { borderColor: col, background: `color-mix(in srgb, ${col} 10%, transparent)`, color: col } : { borderStyle: "dashed", borderColor: "var(--color-line)" }}>
              <div>
                <Icon size={22}>{s.unlocked ? <><rect x="3" y="8" width="18" height="12" rx="2" /><path d="M3 12h18" /><path d="M12 12v3" /><path d="M7 8V6a5 5 0 0 1 10 0v2" /></> : <><rect x="5" y="11" width="14" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></>}</Icon>
                <p className="mt-1 text-[10px] font-semibold">{s.unlocked ? s.item.rarity_label : `ab ${s.threshold} Läufen`}</p>
              </div>
            </div>
          );
        })}
      </div>
      {cur.sick_days > 0 && <p className="mt-2 text-[11px] text-muted">{cur.sick_days} Krankheitstage diese Woche – Schwellen gesenkt.</p>}
      {(data.vault.veteran || data.vault.claimable.length > 0) && (
        <div className="mt-4 space-y-3 border-t border-line pt-4">
          {data.vault.veteran && <VaultChoice vault={data.vault.veteran} title="Veteranentruhe · für deine bisherige Reise" onClaim={onClaim} />}
          {data.vault.claimable.map((v) => <VaultChoice key={v.week} vault={v} title={`Woche vom ${dm(v.week)} · ${v.runs} Läufe`} onClaim={onClaim} />)}
        </div>
      )}
    </Card>
  );
}

// --- Inventar & Kampflog ----------------------------------------------------------------
export function HeroInventory({ items }: { items: HeroItem[] }) {
  const [sel, setSel] = useState<HeroItem | null>(null);
  return (
    <Card>
      <CardTitle title={`Inventar · ${items.length} ${items.length === 1 ? "Gegenstand" : "Gegenstände"}`} sub="Jeder Lauf droppt Beute: Seltenheit verdient, Gegenstand zufällig" />
      {items.length ? (
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((it) => <ItemTile key={it.id} item={it} onClick={() => setSel(it)} />)}
        </div>
      ) : <p className="text-xs text-muted">Noch leer – dein nächster Lauf bringt die erste Beute.</p>}
      {sel && <ItemDetail item={sel} onClose={() => setSel(null)} />}
    </Card>
  );
}

const LOG_ICON: Record<string, string> = { level: "⬆", klasse: "⚔", erfolg: "🏆", beute: "✦", truhe: "🗝" };

export function HeroLog({ data }: { data: Hero }) {
  return (
    <Card>
      <CardTitle title="Kampflog" sub="Level-Aufstiege, Klassenwechsel, Beute und Erfolge" />
      <ol className="max-h-96 space-y-1.5 overflow-y-auto pr-1 text-sm">
        {data.log.map((e, i) => (
          <li key={i} className="flex gap-2">
            <span className="w-12 shrink-0 text-[11px] tabular-nums text-muted">{dm(e.date)}</span>
            <span className="w-4 shrink-0 text-center" aria-hidden="true">{LOG_ICON[e.kind]}</span>
            <span className="min-w-0" style={e.rarity ? { color: rc(e.rarity) } : undefined}>{e.text}</span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

export function HeroRules({ data }: { data: Hero }) {
  const x = data.xp_sources;
  const rows: [string, number][] = [["Laufen", x.laufen], ["Kraft", x.kraft], ["Alltag", x.alltag], ["Erfolge", x.erfolge], ["Ruhebonus", x.ruhebonus]];
  return (
    <Card>
      <CardTitle title="So entstehen XP" sub={`Gesamt ${de0(data.hero.xp)} XP seit Beginn deiner Daten`} />
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm tabular-nums">
        {rows.map(([k, v]) => <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="text-right font-semibold">{de0(v)}</dd></div>)}
      </dl>
      <ul className="mt-3 list-disc space-y-1 border-t border-line pl-4 pt-3 text-[11px] text-muted">
        <li>Lauf: 2 XP je Minute × Puls-Zone (Z1 1,0 · Z2 1,2 · Z3 1,5 · Z4 1,8).</li>
        <li>Kraft: 6 XP je Arbeitssatz, höchstens 180 je Training.</li>
        <li>Ab dem {data.rules.runs_full_xp + 1}. Lauf bzw. {data.rules.workouts_full_xp + 1}. Krafttraining einer Woche nur halbe XP – Erholung zählt.</li>
        <li>Ruhe- und Krankheitstage laden {data.rules.rest_per_day} XP Ruhebonus, der die nächsten Trainings-XP verdoppelt.</li>
        <li>Alltag: Schritte über 5.000, Rad und Gehen. Erfolge zählen mit ihren Punkten.</li>
      </ul>
    </Card>
  );
}
