"use client";

import { useEffect, useState } from "react";
import type { Hero, Weather } from "@/lib/api";
import { play, setSoundOn, soundOn } from "@/lib/hero-sound";
import { de0, dm } from "@/lib/format";

const TIP_YELLOW = "#ffd100";

// --- Szene: echtes Wetter + Tageszeit hinter der Figur --------------------------------------
type Phase = "nacht" | "morgen" | "tag" | "abend";
const PHASE_LABEL: Record<Phase, string> = { nacht: "Nacht", morgen: "Morgengrauen", tag: "Tag", abend: "Abenddämmerung" };

function phaseOf(weather: Extract<Weather, { configured: true }>, now: Date): Phase {
  const t = now.getTime();
  const rise = new Date(weather.day.sunrise).getTime(), set = new Date(weather.day.sunset).getTime();
  const m = 45 * 60 * 1000;
  if (Math.abs(t - rise) <= m) return "morgen";
  if (Math.abs(t - set) <= m) return "abend";
  return t > rise && t < set ? "tag" : "nacht";
}

const SKY: Record<Phase, string> = {
  nacht: "linear-gradient(180deg, #070b1f 0%, #141a36 55%, #0b0907 100%)",
  morgen: "linear-gradient(180deg, #23173a 0%, #9c4f3a 50%, #0b0907 100%)",
  abend: "linear-gradient(180deg, #1f1230 0%, #a2472b 50%, #0b0907 100%)",
  tag: "linear-gradient(180deg, #1f4466 0%, #4f7896 50%, #0b0907 100%)",
};
// Saisonale Effekte des laufenden Events (Blätter, Schnee, Blüten, Glühwürmchen, Funken).
const SEASON: Record<string, { cls: string; glyph: string; colors: string[] }> = {
  blaetter: { cls: "hero-leaf", glyph: "❧", colors: ["#d9622b", "#b8860b", "#a0522d", "#e8a33d"] },
  schnee: { cls: "hero-leaf", glyph: "❄", colors: ["#e8f4ff", "#cfe6ff"] },
  blueten: { cls: "hero-leaf", glyph: "✿", colors: ["#ff9ec7", "#ffd1e3", "#fff0f6"] },
  gluehwuermchen: { cls: "hero-firefly", glyph: "•", colors: ["#ffe066", "#d4ff6b"] },
  funken: { cls: "hero-spark", glyph: "✷", colors: ["#ffb347", "#ffd27f"] },
};
const WET = new Set(["drizzle", "rain", "heavy-rain", "thunder", "sleet"]);
const CLOUDY = new Set(["cloudy", "partly-cloudy", "mostly-clear", "fog", "drizzle", "rain", "heavy-rain", "thunder", "snow", "sleet"]);

export function HeroScene({ weather, effect }: { weather: Weather | null; effect?: string }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 60_000); return () => clearInterval(t); }, []);
  if (!weather || !weather.configured) return null;
  const phase = phaseOf(weather, now);
  const icon = weather.current.icon;
  const grey = icon === "cloudy" || WET.has(icon) || icon === "fog";
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden rounded-md" aria-hidden="true">
      <div className="absolute inset-0" style={{ background: SKY[phase], opacity: grey ? 0.55 : 0.75, filter: grey ? "saturate(.45)" : undefined }} />
      {phase === "nacht" && !grey && Array.from({ length: 22 }, (_, i) => (
        <span key={i} className="hero-star absolute rounded-full bg-white"
              style={{ left: `${(i * 37) % 100}%`, top: `${(i * 23) % 45}%`, width: i % 5 ? 1.5 : 2.5, height: i % 5 ? 1.5 : 2.5, animationDelay: `${(i % 7) * 0.6}s` }} />
      ))}
      {!grey && (phase === "nacht"
        ? <span className="absolute right-[12%] top-[8%] h-7 w-7 rounded-full" style={{ background: "#f4f1de", boxShadow: "0 0 18px #f4f1de88, inset -6px -3px 0 #c9c3a6" }} />
        : <span className="absolute right-[12%] rounded-full" style={{ top: phase === "tag" ? "8%" : "34%", width: 30, height: 30, background: phase === "tag" ? "#ffe9a8" : "#ffb36b", boxShadow: `0 0 28px ${phase === "tag" ? "#ffe9a8" : "#ff8a3d"}` }} />)}
      {CLOUDY.has(icon) && [0, 1, 2].map((i) => (
        <span key={i} className="hero-cloud absolute rounded-full"
              style={{ top: `${6 + i * 10}%`, left: `${-30 + i * 25}%`, width: 120 + i * 30, height: 34 + i * 6,
                       background: grey ? "#8a919c" : "#c7ccd4", opacity: grey ? 0.35 : 0.22, filter: "blur(8px)", animationDelay: `${i * -9}s` }} />
      ))}
      {WET.has(icon) && Array.from({ length: icon === "drizzle" ? 14 : 28 }, (_, i) => (
        <span key={i} className={icon === "sleet" && i % 2 ? "hero-flake absolute rounded-full bg-white/70" : "hero-drop absolute"}
              style={{ left: `${(i * 29) % 100}%`, top: "-10%", animationDelay: `${(i % 9) * 0.17}s`, animationDuration: `${0.7 + (i % 4) * 0.12}s`,
                       ...(icon === "sleet" && i % 2 ? { width: 3, height: 3 } : {}) }} />
      ))}
      {icon === "snow" && Array.from({ length: 26 }, (_, i) => (
        <span key={i} className="hero-flake absolute rounded-full bg-white/80"
              style={{ left: `${(i * 31) % 100}%`, top: "-5%", width: 3 + (i % 3), height: 3 + (i % 3), animationDelay: `${(i % 8) * 0.5}s` }} />
      ))}
      {icon === "fog" && <span className="hero-fog absolute inset-x-0 bottom-[20%] h-1/3" />}
      {icon === "thunder" && <span className="hero-flash absolute inset-0 bg-white" />}
      {effect && SEASON[effect] && Array.from({ length: 9 }, (_, i) => (
        <span key={`s${i}`} className={`absolute ${SEASON[effect].cls}`}
              style={{ left: `${(i * 41 + 7) % 100}%`, top: SEASON[effect].cls === "hero-firefly" ? `${30 + (i * 17) % 55}%` : "-8%",
                       color: SEASON[effect].colors[i % SEASON[effect].colors.length], animationDelay: `${i * -1.3}s`, fontSize: 10 + (i % 3) * 3 }}>
          {SEASON[effect].glyph}
        </span>
      ))}
      <div className="absolute inset-0" style={{ background: "radial-gradient(ellipse at 50% 60%, transparent 40%, rgba(0,0,0,.55) 100%)" }} />
      <p className="absolute bottom-1 right-2 text-[9px] text-white/60">
        {weather.place.split(",")[0]} · {Math.round(weather.current.temp)} °C · {weather.current.text} · {PHASE_LABEL[phase]}
      </p>
    </div>
  );
}

// --- Begleiter ----------------------------------------------------------------------------
const PET_COLORS: Record<string, { body: string; dark: string; light: string }> = {
  fuchs: { body: "#e8772e", dark: "#9c4214", light: "#fff3e6" },
  baer: { body: "#8b5a2b", dark: "#5a3716", light: "#d8b48a" },
  loewe: { body: "#d9a441", dark: "#a8641f", light: "#f6e3b5" },
  eule: { body: "#8d7b68", dark: "#5e4f40", light: "#efe3c8" },
};

function PetSvg({ species, mood }: { species: string; mood: string }) {
  const c = PET_COLORS[species] ?? PET_COLORS.fuchs;
  const closed = mood === "schlaeft" || mood === "krank";
  const eyes = closed
    ? <><path d="M24 21q2 2 4 0" stroke="#1a120c" strokeWidth="1.2" fill="none" /><path d="M32 21q2 2 4 0" stroke="#1a120c" strokeWidth="1.2" fill="none" /></>
    : <><circle cx="26" cy="20.5" r="1.6" fill="#1a120c" /><circle cx="34" cy="20.5" r="1.6" fill="#1a120c" /></>;
  if (species === "eule") {
    return <svg viewBox="0 0 60 50" className="h-full w-full">
      <path d="M22 10 l3 5 M38 10 l-3 5" stroke={c.dark} strokeWidth="3" strokeLinecap="round" />
      <ellipse cx="30" cy="30" rx="13" ry="16" fill={c.body} />
      <ellipse cx="30" cy="34" rx="8" ry="10" fill={c.light} />
      <path d="M17 26 q-5 10 3 18 M43 26 q5 10 -3 18" fill={c.dark} />
      {closed ? <>{eyes}</> : <><circle cx="25" cy="21" r="5" fill="#fff" /><circle cx="35" cy="21" r="5" fill="#fff" /><circle cx="25" cy="21" r="2.2" fill="#1a120c" /><circle cx="35" cy="21" r="2.2" fill="#1a120c" /></>}
      <path d="M28.5 25 l1.5 3 l1.5 -3 z" fill="#e3b64f" />
    </svg>;
  }
  return <svg viewBox="0 0 60 50" className="h-full w-full">
    {species === "fuchs" && <g className="pet-tail"><path d="M42 36 q16 -2 14 -16 q-6 8 -16 10 z" fill={c.body} /><path d="M54 21 q2 4 -2 6 q-1 -4 2 -6" fill={c.light} /></g>}
    {species === "loewe" && <g className="pet-tail"><path d="M43 37 q12 2 12 -10" stroke={c.body} strokeWidth="2.5" fill="none" /><circle cx="55" cy="26" r="3" fill={c.dark} /></g>}
    {species === "baer" && <circle cx="45" cy="35" r="3" fill={c.body} />}
    <ellipse cx="32" cy="36" rx="14" ry="9" fill={c.body} />
    <ellipse cx="22" cy="43" rx="3.5" ry="3" fill={c.dark} /><ellipse cx="40" cy="43" rx="3.5" ry="3" fill={c.dark} />
    {species === "loewe" && <circle cx="30" cy="21" r="13" fill={c.dark} />}
    {species === "fuchs" && <><path d="M21 15 l2 -11 l7 8 z" fill={c.body} /><path d="M39 15 l-2 -11 l-7 8 z" fill={c.body} /></>}
    {species === "baer" && <><circle cx="21" cy="12" r="4" fill={c.body} /><circle cx="39" cy="12" r="4" fill={c.body} /><circle cx="21" cy="12" r="2" fill={c.dark} /><circle cx="39" cy="12" r="2" fill={c.dark} /></>}
    {species === "loewe" && <><circle cx="21" cy="13" r="3" fill={c.body} /><circle cx="39" cy="13" r="3" fill={c.body} /></>}
    <circle cx="30" cy="21" r="10" fill={c.body} />
    <ellipse cx="30" cy="26" rx={species === "fuchs" ? 5 : 6} ry="4" fill={c.light} />
    <circle cx="30" cy="24.5" r="1.4" fill="#1a120c" />
    {eyes}
    <ellipse cx="32" cy="38" rx="6" ry="4" fill={c.light} opacity=".7" />
  </svg>;
}

export function Companion({ pet }: { pet: Hero["companion"] }) {
  const [talk, setTalk] = useState(false);
  useEffect(() => { if (!talk) return; const t = setTimeout(() => setTalk(false), 4500); return () => clearTimeout(t); }, [talk]);
  const size = [46, 58, 70][pet.stage];
  return (
    <div className="absolute bottom-2 left-2 z-10">
      {talk && (
        <div className="wow-tip ach-fade absolute bottom-full left-0 mb-2 w-48 text-[12px]">
          <p className="font-bold" style={{ color: TIP_YELLOW }}>{pet.name} <span className="font-normal text-[#9d9d9d]">· {pet.stage_label}</span></p>
          <p>{pet.text}</p>
          {pet.next_stage != null && <p className="mt-1 text-[11px] text-[#9d9d9d]">Wächst ab {pet.next_stage} Tagen Serie (jetzt {pet.streak}).</p>}
        </div>
      )}
      <button type="button" onClick={() => { setTalk((v) => !v); play("click"); }} aria-label={`${pet.name}: ${pet.text}`} title={pet.name}
              className={`pet relative block pet-${pet.mood}`} style={{ width: size, height: size * 0.83 }}>
        <PetSvg species={pet.species} mood={pet.mood} />
        {pet.mood === "schlaeft" && <span className="pet-z absolute -top-2 right-0 font-display text-[11px] font-bold text-white/80">z</span>}
        {pet.mood === "stolz" && <span className="pet-spark absolute -top-1 right-1 text-[12px]" style={{ color: TIP_YELLOW }}>✦</span>}
        {pet.mood === "krank" && <span className="absolute -top-1 right-0 text-[11px]">🌡</span>}
      </button>
    </div>
  );
}

// --- Seit deinem letzten Besuch -----------------------------------------------------------
const VISIT_KEY = "milon.hero.visit";
const logKey = (e: Hero["log"][number]) => `${e.date}|${e.text}`;

export function useLastVisit(hero: Hero | null) {
  const [state, setState] = useState<{ fromXp: number | null; news: Hero["log"]; gained: number } | null>(null);
  useEffect(() => {
    if (!hero || state) return;
    let prev: { xp: number; log: string[] } | null = null;
    try { prev = JSON.parse(localStorage.getItem(VISIT_KEY) || "null"); } catch { /* leer */ }
    const keys = hero.log.map(logKey);
    try { localStorage.setItem(VISIT_KEY, JSON.stringify({ xp: hero.hero.xp, log: keys })); } catch { /* ohne Speicher */ }
    if (!prev) { setState({ fromXp: null, news: [], gained: 0 }); return; }
    const seen = new Set(prev.log);
    setState({ fromXp: prev.xp, news: hero.log.filter((e) => !seen.has(logKey(e))), gained: Math.max(0, hero.hero.xp - prev.xp) });
  }, [hero, state]);
  return state;
}

export function WelcomeBack({ news, gained, onClose }: { news: Hero["log"]; gained: number; onClose: () => void }) {
  useEffect(() => { if (news.length || gained) play(news.some((e) => e.kind === "level") ? "levelup" : "quest"); }, [news, gained]);
  if (!news.length && !gained) return null;
  return (
    <div className="ach-fade rounded-card border p-4" role="status"
         style={{ borderColor: "var(--wow-gold)", background: "radial-gradient(circle at 0% 0%, rgba(120,82,28,.55), rgba(12,9,6,.9) 60%)" }}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-display text-lg font-bold" style={{ color: TIP_YELLOW }}>Willkommen zurück, Held!</p>
          <p className="text-sm text-muted">Seit deinem letzten Besuch{gained ? <> · <b className="hero-float inline-block" style={{ color: "#1eff00" }}>+{de0(gained)} EP</b></> : null}</p>
        </div>
        <button type="button" onClick={onClose} className="rounded border border-[#4b3a22] px-2 py-1 text-xs text-muted">Weiter</button>
      </div>
      {news.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-[13px]">
          {news.slice(0, 6).map((e, i) => <li key={i}><span className="mr-1.5 text-[#8a8a8a]">[{dm(e.date)}]</span>{e.text.replace(/ \(\+\d+ XP\)$/, "")}</li>)}
          {news.length > 6 && <li className="text-xs text-muted">… und {news.length - 6} weitere im Kampflog</li>}
        </ul>
      )}
    </div>
  );
}

export function SoundToggle() {
  const [on, setOn] = useState(false);
  useEffect(() => setOn(soundOn()), []);
  return (
    <button type="button" onClick={() => { const next = !on; setSoundOn(next); setOn(next); if (next) play("quest"); }}
            className="grid h-8 w-8 place-items-center rounded border border-[#4b3a22] text-muted hover:text-[#ffd100]"
            aria-label={on ? "Klänge ausschalten" : "Klänge einschalten"} title={on ? "Klänge an" : "Klänge aus"}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M11 4.7a.7.7 0 0 0-1.2-.5L6.4 7.6A1.4 1.4 0 0 1 5.4 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.4a1.4 1.4 0 0 1 1 .4l3.4 3.4a.7.7 0 0 0 1.2-.5z" />
        {on ? <><path d="M16 9a5 5 0 0 1 0 6" /><path d="M19.4 18.4a9 9 0 0 0 0-12.8" /></> : <><line x1="22" x2="16" y1="9" y2="15" /><line x1="16" x2="22" y1="9" y2="15" /></>}
      </svg>
    </button>
  );
}
