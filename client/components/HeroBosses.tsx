"use client";

import type { Hero } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { Icon } from "@/components/Hero";
import { dm } from "@/lib/format";

const TIP_YELLOW = "#ffd100";
const SKULL = <><path d="m12.5 17-.5-1-.5 1h1z" /><path d="M15 22a1 1 0 0 0 1-1v-1a2 2 0 0 0 1.56-3.25 8 8 0 1 0-11.12 0A2 2 0 0 0 8 20v1a1 1 0 0 0 1 1z" /><circle cx="15" cy="12" r="1" /><circle cx="9" cy="12" r="1" /></>;
const BOSS_ICON: Record<string, React.ReactNode> = {
  waechter: <><circle cx="12" cy="13" r="8" /><path d="M12 9v4l2 2" /><path d="M10 2h4" /></>,
  wyrm: <path d="M4 18c3 0 3-4 6-4s3 4 6 4 3-6 6-6M2 8c2 0 3-3 5-3s3 3 5 3" />,
  fresser: <><path d="M3 12h18" /><path d="M12 3a9 9 0 1 0 9 9" /><path d="m15 3 6 6" /></>,
  koloss: <><path d="M14.4 14.4 9.6 9.6" /><path d="M18.657 21.485a2 2 0 1 1-2.829-2.828l-1.767 1.768a2 2 0 1 1-2.829-2.829l6.364-6.364a2 2 0 1 1 2.829 2.829l-1.768 1.767a2 2 0 1 1 2.828 2.829z" /><path d="M6.404 12.768a2 2 0 1 1-2.829-2.829l1.768-1.767a2 2 0 1 1-2.828-2.829l2.828-2.828a2 2 0 1 1 2.829 2.828l1.767-1.768a2 2 0 1 1 2.829 2.829z" /></>,
  kettenfresser: <><circle cx="6" cy="16" r="3.5" /><circle cx="18" cy="16" r="3.5" /><path d="M6 16 10 8h5l3 8M10 8 12 16h-6" /></>,
};
const MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];

// --- Schlachtzug des Monats: Bossrahmen mit Lebensleiste -----------------------------------
export function HeroRaid({ data }: { data: Hero }) {
  const month = data.bosses[0] ? MONTHS[Number(data.bosses[0].month.slice(5, 7)) - 1] : "";
  const down = data.bosses.filter((b) => b.defeated).length;
  return (
    <Card>
      <CardTitle title={`Schlachtzug · ${month}`} sub={`${down}/${data.bosses.length} Bosse besiegt · Ziele relativ zu deinen 90 Tagen vor Monatsbeginn · je 400 EP + epische Beute`} />
      <div className="space-y-3">
        {data.bosses.map((b) => {
          const col = b.loot === "orange" ? "var(--rar-orange)" : "var(--rar-lila)";
          return (
            <div key={b.key} className="flex items-center gap-3">
              <span className="grid h-12 w-12 shrink-0 place-items-center rounded-full"
                    style={{ color: b.defeated ? "#5b4526" : "#ff6a5c", background: "radial-gradient(circle at 50% 35%, #3a1410, #0b0907 75%)",
                             boxShadow: `0 0 0 2px #000, 0 0 0 3px ${b.defeated ? "#4b3a22" : "var(--wow-gold)"}` }}>
                <Icon size={22}>{b.defeated ? SKULL : BOSS_ICON[b.key]}</Icon>
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <p className="truncate font-display text-[13px] font-bold" style={{ color: b.defeated ? "#9d9d9d" : TIP_YELLOW }}>{b.name}</p>
                  <span className="shrink-0 text-[10px] uppercase tracking-wider text-muted">{b.kind}</span>
                </div>
                <div className="relative mt-1 h-4 overflow-hidden rounded-[3px] border border-black bg-[#1a0606]" style={{ boxShadow: "0 0 0 1px #5b4526" }}>
                  <div className="absolute inset-y-0 left-0 transition-[width] duration-700"
                       style={{ width: `${b.hp * 100}%`, background: "linear-gradient(180deg, #e8392c, #9b1410 60%, #6b0c08)" }} />
                  <p className="absolute inset-0 grid place-items-center text-[10px] font-bold text-white" style={{ textShadow: "0 1px 2px #000" }}>
                    {b.defeated ? `Besiegt am ${dm(b.defeated_on!)}` : `${Math.round(b.hp * 100)} %`}
                  </p>
                </div>
                <p className="mt-0.5 flex flex-wrap justify-between gap-x-2 text-[11px] text-muted">
                  <span>Ziel: {b.goal}</span><span>{b.status}</span>
                </p>
                {b.defeated && <p className="text-[11px]" style={{ color: col }}>Beute erhalten · {b.loot === "orange" ? "Legendär-Chance" : "Episch"}</p>}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// --- Instanzen: lange Läufe als Dungeons ---------------------------------------------------
const TIER_COLOR: Record<string, string> = { normal: "var(--rar-blau)", heroisch: "var(--rar-lila)", mythisch: "var(--rar-orange)" };

export function HeroDungeons({ data }: { data: Hero }) {
  return (
    <Card>
      <CardTitle title="Instanzen" sub="Jeder Lauf ab 10 km · Normal ab 10 · Heroisch ab 15 · Mythisch ab 21,1 km · Kilometermarken sind die Bosse" />
      {data.dungeons.length === 0 ? (
        <p className="text-xs text-muted">Noch keine Instanz betreten – dein nächster Lauf ab 10 km öffnet die erste.</p>
      ) : (
        <ul className="space-y-2.5">
          {data.dungeons.map((d) => (
            <li key={d.id} className="rounded-md border border-[#2c2216] bg-black/25 p-2.5">
              <div className="flex items-baseline justify-between gap-2">
                <p className="truncate font-display text-[13px] font-bold" style={{ color: TIP_YELLOW }}>{d.name}</p>
                <span className="shrink-0 rounded border px-1.5 text-[10px] font-bold" style={{ borderColor: TIER_COLOR[d.tier], color: TIER_COLOR[d.tier] }}>{d.tier_label}</span>
              </div>
              <p className="text-[11px] text-muted">{dm(d.date)} · {d.km.toLocaleString("de-DE")} km · {d.cleared ? <span style={{ color: "#1eff00" }}>bezwungen</span> : "nicht ganz bezwungen"}</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {d.bosses.map((b) => (
                  <span key={b.name} title={`${b.name}${b.km ? ` · ${String(b.km).replace(".", ",")} km` : ""}${b.hint ? ` · ${b.hint}` : ""}${b.optional ? " · nächste Marke" : ""}`}
                        className="flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px]"
                        style={{ borderColor: b.defeated ? "#7a1a12" : "#3a2d1a", color: b.defeated ? "#ff6a5c" : "#6b5a40",
                                 background: b.defeated ? "#1d0807" : "transparent", borderStyle: b.optional ? "dashed" : "solid" }}>
                    <Icon size={11}>{SKULL}</Icon>{b.name}
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
