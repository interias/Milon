"use client";

import { useState } from "react";
import type { Hero } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";
import { de0 } from "@/lib/format";

const TIP_YELLOW = "#ffd100";
// WoW-Ruffarben: Neutral gelb, Freundlich bis Respektvoll grün, Ehrfürchtig türkis.
const STANDING_COLOR = ["#ffd100", "#1eff00", "#1eff00", "#1eff00", "#00ffba"];

export function HeroReputation({ data }: { data: Hero }) {
  return (
    <Card>
      <CardTitle title="Ruf" sub="Fraktionen von Neutral bis Ehrfürchtig – aus deinen Daten seit Beginn" />
      <div className="space-y-3">
        {data.reputation.map((f) => {
          const col = STANDING_COLOR[f.rank];
          return (
            <div key={f.key}>
              <div className="flex items-baseline justify-between gap-2">
                <p className="truncate font-display text-[13px] font-bold" style={{ color: TIP_YELLOW }}>{f.name}</p>
                <span className="shrink-0 text-[11px] font-semibold" style={{ color: col }}>{f.standing}</span>
              </div>
              <div className="relative mt-1 h-4 overflow-hidden rounded-[3px] border border-black bg-[#0a0807]" style={{ boxShadow: "0 0 0 1px #5b4526" }}>
                <div className="absolute inset-y-0 left-0 transition-[width] duration-700"
                     style={{ width: `${f.progress * 100}%`, background: `linear-gradient(180deg, color-mix(in srgb, ${col} 85%, #fff), color-mix(in srgb, ${col} 70%, #000))` }} />
                <p className="absolute inset-0 grid place-items-center text-[10px] font-bold text-white" style={{ textShadow: "0 1px 2px #000" }}>
                  {f.next ? `${de0(f.value - f.floor)} / ${de0(f.next - f.floor)}` : `${de0(f.value)} · höchste Stufe`}
                </p>
              </div>
              <p className="mt-0.5 text-[10px] text-muted">{f.source}</p>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

export function HeroTitleChooser({ data, onChoose, onClose }: { data: Hero; onChoose: (key: string | null) => Promise<void>; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  async function pick(key: string | null) {
    setBusy(true);
    try { await onChoose(key); onClose(); } finally { setBusy(false); }
  }
  const earned = data.titles.filter((t) => t.earned).length;
  return (
    <RunAnalysisDialog title={`Titel · ${earned}/${data.titles.length} freigeschaltet`} onClose={onClose}>
      <p className="mb-3 text-sm text-muted">Wähle einen Titel, den du am Einheitenrahmen trägst. Ohne Wahl zeigt er den Stufentitel.</p>
      <div className="grid gap-1.5 sm:grid-cols-2">
        {data.titles.map((t) => (
          <button key={t.key} type="button" disabled={!t.earned || busy || t.chosen} onClick={() => pick(t.key)}
                  className="rounded-md border p-2.5 text-left transition hover:brightness-110"
                  style={{ borderColor: t.chosen ? "var(--wow-gold)" : "#3a2d1a", background: "#120e0a", opacity: t.earned ? 1 : 0.55 }}>
            <p className="font-display text-sm font-bold" style={{ color: t.earned ? TIP_YELLOW : "#9d9d9d" }}>&lt;{t.name}&gt;{t.chosen ? " · getragen" : ""}</p>
            <p className="text-[11px] text-muted">{t.condition}</p>
            {!t.earned && (
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-[#0a0807]">
                <div className="h-full rounded-full bg-[#b36cf0]" style={{ width: `${(t.value / t.target) * 100}%` }} />
              </div>
            )}
          </button>
        ))}
      </div>
      <button type="button" disabled={busy || !data.hero.title_chosen} onClick={() => pick(null)}
              className="mt-3 w-full rounded-md border border-[#4b3a22] p-2 text-xs text-muted hover:brightness-110">Stufentitel tragen</button>
    </RunAnalysisDialog>
  );
}
