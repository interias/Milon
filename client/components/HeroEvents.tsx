"use client";

import type { Hero } from "@/lib/api";
import { Card } from "@/components/ui";
import { Icon } from "@/components/Hero";
import { dm } from "@/lib/format";

const TIP_YELLOW = "#ffd100";
const HELM = <><path d="M12 2a8 8 0 0 0-8 8v4h16v-4a8 8 0 0 0-8-8Z" /><path d="M4 14v3a2 2 0 0 0 2 2h3l3 3 3-3h3a2 2 0 0 0 2-2v-3" /><path d="M9 14v2" /><path d="M15 14v2" /></>;
const EVENT_COLOR: Record<string, string> = { blaetter: "#ff8a3d", schnee: "#9fd8ff", blueten: "#ff9ec7", gluehwuermchen: "#ffe066", funken: "#ffb347" };

// --- Questgeber: Meister Gorm + Tagesaufgabe -----------------------------------------------
export function HeroTrainer({ data }: { data: Hero }) {
  const t = data.trainer, d = data.daily;
  if (!t) return null;
  const open = d?.today && !d.today.done;
  return (
    <Card>
      <div className="flex items-start gap-3">
        <span className="relative grid h-14 w-14 shrink-0 place-items-center rounded-full"
              style={{ color: "#c69b6d", background: "radial-gradient(circle at 50% 35%, #3b2c18, #0b0907 75%)", boxShadow: "0 0 0 2px #000, 0 0 0 3px var(--wow-gold)" }}>
          <Icon size={28}>{HELM}</Icon>
          {d?.today && <span className="absolute -top-2 left-1/2 -translate-x-1/2 font-display text-xl font-bold" style={{ color: open ? TIP_YELLOW : "#1eff00", textShadow: "0 0 6px #000" }}>{open ? "!" : "✓"}</span>}
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-display text-sm font-bold" style={{ color: TIP_YELLOW }}>{t.name}</p>
          <p className="text-[11px] text-muted">{t.role}</p>
          <p className="mt-1.5 rounded-md border border-[#3a2d1a] bg-black/30 px-3 py-2 text-[13px] italic" style={{ color: "#efe3c8" }}>„{t.quote}“</p>
        </div>
      </div>
      {d?.today && (
        <div className="mt-3 border-t border-[#3a2d1a] pt-3">
          <div className="flex items-baseline justify-between gap-2">
            <p className="font-display text-[13px] font-bold" style={{ color: open ? TIP_YELLOW : "#9d9d9d" }}>
              Tagesaufgabe: {d.today.title}{open ? "" : " ✓"}
            </p>
            <span className="shrink-0 text-[11px] text-muted">+50 EP</span>
          </div>
          <p className="text-[12px]" style={{ color: open ? "#fff" : "#9d9d9d" }}>– {d.today.goal}</p>
          <div className="mt-2 flex items-center gap-2">
            <div className="flex gap-1">
              {d.last7.map((x) => (
                <span key={x.date} title={`${dm(x.date)} · ${x.title}${x.done ? " ✓" : x.sick ? " · krank" : ""}`}
                      className="h-3 w-3 rounded-sm border"
                      style={{ borderColor: x.date === d.today?.date ? TIP_YELLOW : "#3a2d1a",
                               background: x.done ? "#1eff00" : x.sick ? "var(--color-sick)" : "#0a0807" }} />
              ))}
            </div>
            <span className="text-[11px] text-muted">Serie {d.streak} · alle 7 Tage seltene Beute</span>
          </div>
        </div>
      )}
    </Card>
  );
}

// --- Saison-Event -------------------------------------------------------------------------
export function HeroEvent({ data }: { data: Hero }) {
  const e = data.event;
  if (!e) return null;
  const col = EVENT_COLOR[e.effect] ?? TIP_YELLOW;
  const pct = Math.min(1, e.tokens / e.goal);
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="font-display text-base font-bold" style={{ color: col }}>{e.name}</h3>
        <span className="text-[11px] text-muted">Saison-Event · nur diesen Monat</span>
      </div>
      <p className="text-[12px] text-muted">{e.rule} · Belohnung bei {e.goal}: {e.xp} EP und</p>
      <p className="text-[13px] font-semibold" style={{ color: "var(--rar-lila)" }}>[{e.item}]</p>
      <div className="mt-2 flex flex-wrap gap-1" aria-label={`${e.tokens} von ${e.goal} ${e.token}`}>
        {Array.from({ length: e.goal }, (_, i) => (
          <span key={i} className="grid h-6 w-6 place-items-center rounded border text-[12px]"
                style={{ borderColor: i < e.tokens ? col : "#3a2d1a", background: i < e.tokens ? `color-mix(in srgb, ${col} 22%, #0b0907)` : "#0b0907",
                         color: i < e.tokens ? col : "#3a2d1a" }}>
            {TOKEN_GLYPH[e.effect] ?? "✦"}
          </span>
        ))}
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#0a0807]"><div className="h-full rounded-full" style={{ width: `${pct * 100}%`, background: col }} /></div>
      <p className="mt-1 text-[11px]" style={{ color: e.done ? "#1eff00" : "var(--color-muted)" }}>
        {e.done ? `Abgeschlossen am ${dm(e.done_on!)} – die Festtagsbeute liegt in deinen Taschen.` : `${e.tokens}/${e.goal} ${e.token}`}
      </p>
    </Card>
  );
}
const TOKEN_GLYPH: Record<string, string> = { blaetter: "🍂", schnee: "❄", blueten: "✿", gluehwuermchen: "✧", funken: "✷" };
