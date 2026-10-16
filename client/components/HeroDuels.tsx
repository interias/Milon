"use client";

import { useState } from "react";
import { api, type Hero, type HeroSaga } from "@/lib/api";
import { useEffect } from "react";
import { Markdown } from "@/components/Markdown";
import { Card, CardTitle } from "@/components/ui";
import { de, de0, dm, pace } from "@/lib/format";

const TIP_YELLOW = "#ffd100";

// --- Doppelgänger: Lauf-Duell + Schattenvergleich -----------------------------------------
export function HeroDuel({ data }: { data: Hero }) {
  const d = data.duels;
  if (!d) return null;
  const last = d.last;
  const side = (title: string, sub: string, km: number, p: number, ef: number | null, win: boolean, ghost = false) => (
    <div className="min-w-0 flex-1 rounded-md border p-2.5 text-center"
         style={{ borderColor: win ? "var(--wow-gold)" : "#3a2d1a", background: ghost ? "rgba(120,140,190,.08)" : "rgba(0,0,0,.3)",
                  filter: ghost ? "saturate(.6)" : undefined }}>
      <p className="font-display text-[13px] font-bold" style={{ color: ghost ? "#a9b8d8" : TIP_YELLOW }}>{win ? "👑 " : ""}{title}</p>
      <p className="text-[11px] text-muted">{sub}</p>
      <p className="mt-1 font-display text-lg font-bold text-white">{pace(p)} <span className="text-[11px] font-normal text-muted">/km</span></p>
      <p className="text-[11px] text-muted">{de(km, 1)} km · Effizienz {ef != null ? de(ef, 2) : "–"}</p>
    </div>
  );
  return (
    <Card>
      <CardTitle title="Doppelgänger" sub={`Duelle gegen dein Ich von vor ~3 Monaten · ähnliche Distanz · Sieg = schneller und effizienter · ${d.won}/${d.total} gewonnen · je 75 EP`} />
      <div className="grid gap-4 @3xl:grid-cols-2">
        <div>
          <p className="mb-1.5 font-display text-[11px] uppercase tracking-wider text-muted">Letztes Duell</p>
          {last ? (
            <div className="flex items-stretch gap-2">
              {side("Du", dm(last.date), last.km, last.pace, last.ef, last.won)}
              <span className="self-center font-display text-sm font-bold text-[#ff6a5c]">VS</span>
              {side("Dein Schatten", dm(last.twin_date), last.twin_km, last.twin_pace, last.twin_ef, !last.won, true)}
            </div>
          ) : <p className="text-xs text-muted">Noch kein Duell – sobald ein Lauf einen ähnlich langen Zwilling von vor ~3 Monaten hat, tritt dein Schatten an.</p>}
        </div>
        <div className="space-y-3">
          {d.shadows.map((sh) => (
            <div key={sh.label}>
              <p className="mb-1 font-display text-[11px] uppercase tracking-wider text-muted">Schatten {sh.label} · letzte 28 Tage</p>
              {!sh.available ? <p className="text-xs text-muted">Erscheint {sh.appears ? `ab ${dm(sh.appears)}${sh.appears.slice(0, 4) !== data.today.slice(0, 4) ? sh.appears.slice(0, 4) : ""}` : "später"} – dann gibt es genug Daten.</p> : (
                <table className="w-full text-[12px] tabular-nums">
                  <tbody>
                    {sh.rows!.map((r) => (
                      <tr key={r.key} className="border-b border-[#2c2216] last:border-0">
                        <td className="py-0.5 text-muted">{r.name}</td>
                        <td className="py-0.5 text-right text-white">{fmt(r.key, r.now)}</td>
                        <td className="py-0.5 text-right text-[#8a8a8a]">{fmt(r.key, r.then)}</td>
                        <td className="w-6 py-0.5 text-right" style={{ color: r.better ? "#1eff00" : r.better === false ? "#ff6a5c" : "#9d9d9d" }}>
                          {r.better ? "▲" : r.better === false ? "▼" : "="}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {sh.available && <p className="mt-0.5 text-[11px]" style={{ color: sh.won ? "#1eff00" : "var(--color-muted)" }}>{sh.won ? `Schatten besiegt (${sh.wins}/4)` : `${sh.wins}/4 – der Schatten hält noch stand`}</p>}
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}
const fmt = (key: string, v: number | null) => v == null ? "–" : key === "pace" ? pace(v) : key === "ef" ? de(v, 2) : key === "km" ? de(v, 1) : de0(v);

// --- Reittiere ----------------------------------------------------------------------------
export function HeroMounts({ data, onChoose }: { data: Hero; onChoose: (key: string | null) => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [all, setAll] = useState(false);
  if (!data.mounts) return null;
  const owned = data.mounts.filter((m) => m.unlocked).length;
  const shown = all ? data.mounts : [...data.mounts.filter((m) => m.unlocked), ...data.mounts.filter((m) => !m.unlocked).slice(0, 2)];
  async function pick(key: string | null) {
    setBusy(true);
    try { await onChoose(key); } finally { setBusy(false); }
  }
  return (
    <Card>
      <CardTitle title={`Reittiere · ${owned}/${data.mounts.length}`} sub="Freigeschaltet über deine Gesamt-km bzw. Arbeitssätze · eines reitet neben deiner Figur" />
      <div className="grid grid-cols-2 gap-2 @3xl:grid-cols-3">
        {shown.map((m) => (
          <button key={m.key} type="button" disabled={!m.unlocked || busy} onClick={() => pick(m.chosen ? null : m.key)}
                  className={`flex min-w-0 items-center gap-2 rounded-md border p-1.5 text-left transition hover:brightness-110 sm:gap-3 sm:p-2 ${m.chosen ? "wow-pulse" : ""}`}
                  style={{ borderColor: m.chosen ? "var(--wow-gold)" : m.unlocked ? "#6b5230" : "#2c2216", background: "#120e0a",
                           ["--glow" as string]: "var(--wow-gold)", opacity: m.unlocked ? 1 : 0.6 }}>
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-xl sm:h-11 sm:w-11 sm:text-2xl" style={{ background: "#0b0907", filter: m.unlocked ? undefined : "grayscale(1) brightness(.5)" }}>{m.glyph}</span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[12px] font-semibold sm:text-[13px]" style={{ color: m.unlocked ? TIP_YELLOW : "#9d9d9d" }}>{m.name}</span>
              {m.unlocked
                ? <span className="block truncate text-[11px] text-muted">{m.chosen ? "reitet mit dir" : `seit ${dm(m.unlocked_on!)}`}</span>
                : <>
                    <span className="block text-[11px] text-muted">{de0(m.value)}/{de0(m.need)} {m.unit}</span>
                    <span className="mt-1 block h-1 overflow-hidden rounded-full bg-[#0a0807]"><span className="block h-full rounded-full bg-[#b36cf0]" style={{ width: `${(m.value / m.need) * 100}%` }} /></span>
                  </>}
            </span>
          </button>
        ))}
      </div>
      {data.mounts.length > shown.length || all ? (
        <button type="button" onClick={() => setAll((v) => !v)} className="mt-2 text-[11px] text-muted underline decoration-dotted underline-offset-4">
          {all ? "weniger zeigen ▴" : `alle ${data.mounts.length} anzeigen ▾`}
        </button>
      ) : null}
    </Card>
  );
}

// --- Wochen-Saga: der Chronist erzählt die Woche (LLM, nur auf Knopfdruck) ------------------
export function HeroSagaCard() {
  const [saga, setSaga] = useState<HeroSaga | null>(null);
  const [week, setWeek] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  useEffect(() => { api.heroSaga().then((r) => { setSaga(r.saga); setWeek(r.week); }).catch(() => {}); }, []);
  async function write() {
    setBusy(true); setErr(null);
    try { setSaga((await api.heroWriteSaga()).saga); } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }
  const current = saga?.week === week;
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <CardTitle title="Saga der Woche" sub={`Der Chronist erzählt deine Woche${week ? ` ab ${dm(week)}` : ""} · nur auf Knopfdruck, kostet ein paar Cent über deinen Coach-Zugang`} />
        <button type="button" disabled={busy} onClick={write} className="shrink-0 rounded border px-3 py-1.5 font-display text-xs font-bold"
                style={{ background: "linear-gradient(180deg, #3b2c18, #1d150c)", borderColor: "#6b5230", color: TIP_YELLOW }}>
          {busy ? "Der Chronist schreibt …" : current ? "Neu erzählen lassen" : "Saga dieser Woche schreiben"}
        </button>
      </div>
      {err && <p className="text-xs text-bad">{err}</p>}
      {saga ? (
        <div className="rounded-md border border-[#3a2d1a] bg-black/30 px-4 py-3 [&_h2]:font-display [&_h2]:text-[#ffd100]">
          <div className={`relative ${more ? "" : "max-h-44 overflow-hidden sm:max-h-none"}`}>
            <Markdown>{saga.content}</Markdown>
            {!more && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 sm:hidden" style={{ background: "linear-gradient(transparent, #120e0a)" }} />}
          </div>
          {!more && <button type="button" onClick={() => setMore(true)} className="mt-1 text-[12px] underline decoration-dotted underline-offset-4 sm:hidden" style={{ color: TIP_YELLOW }}>Weiterlesen ▾</button>}
          <p className="mt-2 text-[10px] text-muted">
            {current ? "Diese Woche" : `Woche ab ${saga.week ? dm(saga.week) : "?"}`} · geschrieben {new Date(saga.created_at).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
            {saga.cost_usd != null ? ` · ${saga.cost_usd.toFixed(4).replace(".", ",")} $` : ""}
          </p>
        </div>
      ) : <p className="text-xs text-muted">Noch keine Saga – lass den Chronisten deine Woche erzählen.</p>}
    </Card>
  );
}
