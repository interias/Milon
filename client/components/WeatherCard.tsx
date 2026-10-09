"use client";
// Tageswetter für die Übersicht: aktuelle Lage + Stundenverlauf (Temperatur-Kurve, Regen-Balken).
// Daten: Open-Meteo via Backend (/weather); Ort in den Einstellungen.
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type RunAdvice, type RunWindow, type Weather, type WeatherHour } from "@/lib/api";
import { Card } from "@/components/ui";
import { linePath } from "@/components/charts";
import { de, de0 } from "@/lib/format";

const PLACE_KEY = "milon.weather.place";
const WEEKDAYS = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];
const weekday = (date: string) => WEEKDAYS[new Date(`${date}T12:00:00`).getDay()];
const hour = (iso: string) => Number(iso.slice(11, 13));
const clock = (iso: string) => iso.slice(11, 16);

export function WeatherIcon({ icon, night = false, size = 20 }: { icon: string; night?: boolean; size?: number }) {
  const cloud = <path d="M7 18h10a4 4 0 0 0 .4-8A5.5 5.5 0 0 0 6.8 11.2 3.4 3.4 0 0 0 7 18z" />;
  const smallCloud = <path d="M9 19h8a3.2 3.2 0 0 0 .3-6.4 4.4 4.4 0 0 0-8.4.9A2.8 2.8 0 0 0 9 19z" />;
  const sun = (cx: number, cy: number, r: number) => <g>
    <circle cx={cx} cy={cy} r={r} />
    {[0, 45, 90, 135, 180, 225, 270, 315].map((a) => {
      const rad = (a * Math.PI) / 180, i = r + 1.6, o = r + 3.4;
      return <path key={a} d={`M${cx + Math.cos(rad) * i} ${cy + Math.sin(rad) * i}L${cx + Math.cos(rad) * o} ${cy + Math.sin(rad) * o}`} />;
    })}
  </g>;
  const moon = (cx: number, cy: number, r: number) => <path d={`M${cx + r * 0.6} ${cy - r}A${r} ${r} 0 1 0 ${cx + r} ${cy + r * 0.5}A${r * 0.8} ${r * 0.8} 0 0 1 ${cx + r * 0.6} ${cy - r}z`} />;
  const drops = (n: number) => <g stroke="var(--color-accent-2)">{Array.from({ length: n }, (_, i) => <path key={i} d={`M${8 + i * 4} 20.5l-1 2.5`} />)}</g>;
  let body;
  switch (icon) {
    case "clear": body = night ? moon(12, 12, 6) : sun(12, 12, 4.2); break;
    case "mostly-clear":
    case "partly-cloudy": body = <>{night ? moon(8, 8, 4) : sun(8, 8, 3)}<g fill="var(--color-surface)">{smallCloud}</g></>; break;
    case "fog": body = <>{cloud}<path d="M5 21h14M7 23.5h10" stroke="var(--color-accent-2)" /></>; break;
    case "drizzle": body = <>{cloud}{drops(2)}</>; break;
    case "rain": body = <>{cloud}{drops(3)}</>; break;
    case "heavy-rain": body = <>{cloud}{drops(3)}<path d="M10 23l-.6 1.5M14 23l-.6 1.5" stroke="var(--color-accent-2)" /></>; break;
    case "sleet": body = <>{cloud}<path d="M9 20.5l-1 2.5" stroke="var(--color-accent-2)" /><circle cx="14" cy="21.8" r=".9" fill="currentColor" /></>; break;
    case "snow": body = <>{cloud}{[8, 12, 16].map((x) => <circle key={x} cx={x} cy={21.8} r=".9" fill="currentColor" />)}</>; break;
    case "thunder": body = <>{cloud}<path d="M12.5 18.5l-2 3h3l-2 3" stroke="#9a5b00" /></>; break;
    default: body = cloud;
  }
  return <svg viewBox="0 0 24 26" width={size} height={size * 26 / 24} fill="none" stroke="currentColor" strokeWidth="1.5"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="shrink-0 text-accent">{body}</svg>;
}

function HourChart({ hours, nowHour, run }: { hours: WeatherHour[]; nowHour: string | null; run: RunAdvice | null }) {
  const W = 240, H = 100, top = 10, bottom = 66, rainH = 30;
  const temps = hours.map((h) => h.temp);
  const lo = Math.min(...temps) - 0.5, hi = Math.max(...temps) + 0.5;
  const x = (i: number) => ((i + 0.5) / hours.length) * W;
  const y = (t: number) => bottom - ((t - lo) / (hi - lo || 1)) * (bottom - top);
  const pts = hours.map((h, i) => [x(i), y(h.temp)] as const);
  const line = linePath(pts, true);
  const nowIdx = hours.findIndex((h) => h.time === nowHour);
  const nowX = nowIdx >= 0 ? x(nowIdx) : null;
  const maxIdx = temps.indexOf(Math.max(...temps)), minIdx = temps.indexOf(Math.min(...temps));
  const ticks = hours.map((h, i) => ({ h, i })).filter(({ h }) => hour(h.time) % 3 === 0);
  const pct = (i: number) => `${((i + 0.5) / hours.length) * 100}%`;
  // Uhrzeit → x (gleiche Skala wie die Stundenpunkte); null, wenn nicht heute.
  const day0 = hours[0].time.slice(0, 10);
  const frac = (iso: string) => iso.slice(0, 10) === day0 ? Number(iso.slice(11, 13)) + Number(iso.slice(14, 16)) / 60 : null;
  const tx = (iso: string) => { const f = frac(iso); return f == null ? null : ((f + 0.5) / hours.length) * W; };
  const tpct = (iso: string) => { const f = frac(iso); return `${((f ?? 0) + 0.5) / hours.length * 100}%`; };
  const sunrise = run ? tx(run.sunrise) : null, sunset = run ? tx(run.sunset) : null;
  const windows = run?.date === day0 ? [run.morning, run.best].filter((w): w is RunWindow => w != null) : [];
  return <div className="mt-4">
    <div className="relative h-32">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden="true">
        <defs>
          <linearGradient id="wx-temp" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="var(--color-accent)" stopOpacity="0.16" />
            <stop offset="1" stopColor="var(--color-accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {sunrise != null && <rect x={0} width={sunrise} y={0} height={H} fill="var(--color-ink)" opacity={0.05} />}
        {sunset != null && <rect x={sunset} width={W - sunset} y={0} height={H} fill="var(--color-ink)" opacity={0.05} />}
        {windows.map((w) => <rect key={w.start} x={tx(w.start)!} width={tx(w.end)! - tx(w.start)!} y={0} height={H} fill="var(--color-accent)" opacity={0.12} />)}
        {[sunrise, sunset].map((sx, k) => sx != null && <line key={k} x1={sx} x2={sx} y1={0} y2={H} stroke="var(--color-warn)" strokeWidth={1} vectorEffect="non-scaling-stroke" opacity={0.6} />)}
        {hours.map((h, i) => h.rain_prob ? <rect key={h.time} x={x(i) - 3.2} width={6.4} y={H - (h.rain_prob / 100) * rainH}
          height={(h.rain_prob / 100) * rainH} rx={1} fill="var(--color-accent-2)" opacity={0.25 + Math.min(h.rain_mm, 3) / 6} /> : null)}
        <path d={`${line} L${x(hours.length - 1)} ${bottom + 4} L${x(0)} ${bottom + 4} Z`} fill="url(#wx-temp)" />
        <path d={line} fill="none" stroke="var(--color-accent)" strokeWidth={2} vectorEffect="non-scaling-stroke" />
        {nowX != null && <>
          <rect x={0} y={0} width={nowX} height={H} fill="var(--color-surface)" opacity={0.55} />
          <line x1={nowX} x2={nowX} y1={2} y2={H} stroke="var(--color-ink)" strokeDasharray="2 2" strokeWidth={1} vectorEffect="non-scaling-stroke" opacity={0.5} />
        </>}
      </svg>
      {nowIdx >= 0 && <span className="absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface bg-accent"
        style={{ left: pct(nowIdx), top: `${(y(hours[nowIdx].temp) / H) * 100}%` }} />}
      {[maxIdx, minIdx].filter((v, k, a) => a.indexOf(v) === k).map((i) => <span key={i}
        className="absolute -translate-x-1/2 text-[11px] font-semibold text-ink"
        style={{ left: pct(i), top: `calc(${(y(hours[i].temp) / H) * 100}% ${i === maxIdx ? "- 18px" : "+ 5px"})` }}>{de0(hours[i].temp)}°</span>)}
      {windows.map((w) => <span key={w.start} className="absolute bottom-0 -translate-x-1/2 rounded bg-accent px-1 text-[10px] font-semibold text-white"
        style={{ left: `calc((${tpct(w.start)} + ${tpct(w.end)}) / 2)` }}>Lauf</span>)}
      {run && [["↑", run.sunrise], ["↓", run.sunset]].map(([arrow, iso]) => frac(iso) != null && <span key={iso}
        className="absolute top-3 -translate-x-1/2 rounded bg-surface px-0.5 text-[10px] font-semibold text-warn" style={{ left: tpct(iso) }}>☀{arrow} {clock(iso)}</span>)}
      {nowX != null && <span className="absolute top-0 -translate-x-1/2 rounded bg-surface px-1 text-[10px] font-semibold text-muted" style={{ left: pct(nowIdx) }}>jetzt</span>}
    </div>
    <div className="relative mt-1 h-12">
      {ticks.map(({ h, i }) => <div key={h.time} title={`${clock(h.time)} · ${h.text} · ${de(h.temp, 1)} °C · Regen ${h.rain_prob ?? 0} %`}
        className={`absolute flex -translate-x-1/2 flex-col items-center gap-0.5 ${nowIdx >= 0 && i < nowIdx ? "opacity-50" : ""}`} style={{ left: pct(i) }}>
        <WeatherIcon icon={h.icon} night={!h.is_day} size={18} />
        <span className="text-[10px] font-semibold tabular-nums">{de0(h.temp)}°</span>
        <span className="text-[10px] tabular-nums text-muted">{clock(h.time).slice(0, 2)}</span>
      </div>)}
    </div>
    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[10px] text-muted">
      <span className="h-0.5 w-4 rounded bg-accent" /><span>Temperatur</span>
      <span className="ml-2 h-2.5 w-2 rounded-[2px] bg-accent-2/60" /><span>Regenwahrscheinlichkeit</span>
      {windows.length > 0 && <><span className="ml-2 h-2.5 w-2.5 rounded-[2px] bg-accent/15" /><span>Laufempfehlung</span></>}
    </div>
  </div>;
}

function RunWindowRow({ label, w, other }: { label: string; w: RunWindow; other: string | null }) {
  const tone = w.rating === "ideal" ? "bg-accent text-white" : w.rating === "gut" ? "bg-accent/10 text-accent" : "bg-surface-alt text-muted";
  const rain = w.rain_prob >= 20 || w.wet ? `Regen ${w.rain_prob} %` : "trocken";
  return <li className="flex flex-col gap-0.5">
    <p className="flex flex-wrap items-baseline gap-x-2">
      <span className="w-28 text-xs font-semibold text-muted">{label}{other ? ` · ${other}` : ""}</span>
      <strong className="tabular-nums">{clock(w.start)}–{clock(w.end)}</strong>
      <span className="text-xs text-muted">{de0(w.temp)}° · {rain} · Wind {w.wind_kmh} km/h</span>
      <span className={`rounded px-1.5 text-[11px] font-semibold ${tone}`}>{w.rating}</span>
    </p>
    <p className="text-xs text-muted"><span className="font-semibold text-accent">Kleidung:</span> <span className="text-ink">{w.clothing.text}{w.clothing.extras.length ? ` + ${w.clothing.extras.join(", ")}` : ""}</span>
      {w.clothing.adjust > 0 && <> · fühlt sich wie {de0(w.clothing.felt)}° an</>}</p>
  </li>;
}

function RunAdviceBlock({ run, date, isToday }: { run: RunAdvice | null; date: string; isToday: boolean }) {
  if (!run) return <p className="mt-3 border-t border-line pt-3 text-xs text-muted">Laufen: kein Tageslicht-Fenster in Sicht.</p>;
  // Fällt die Empfehlung auf einen anderen Tag (heute schon dunkel), Tag dazuschreiben.
  const other = run.date === date ? null : isToday ? "morgen" : weekday(run.date);
  return <div className="mt-3 border-t border-line pt-3">
    <ul className="flex flex-col gap-2 text-sm">
      {run.morning && <RunWindowRow label="Morgenlauf" w={run.morning} other={other} />}
      {run.best && <RunWindowRow label={run.morning ? "Bestes Fenster" : "Empfehlung"} w={run.best} other={other} />}
    </ul>
    {run.notes.length > 0 && <p className="mt-2 text-xs text-muted">{run.notes.join(" · ")}</p>}
  </div>;
}

export function WeatherCard() {
  const [data, setData] = useState<Weather | null>(null);
  const [error, setError] = useState(false);
  const [index, setIndex] = useState<number | null>(null);
  const [dayIdx, setDayIdx] = useState(0);
  useEffect(() => {
    let saved = 0;
    try { saved = Number(localStorage.getItem(PLACE_KEY)) || 0; } catch { /* Speicher gesperrt */ }
    setIndex(saved);
  }, []);
  useEffect(() => {
    if (index === null) return;
    let active = true;
    const load = () => api.weather(index, dayIdx).then((w) => { if (active) { setData(w); setError(false); } }).catch(() => { if (active) setError(true); });
    void load();
    const timer = window.setInterval(load, 30 * 60_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [index, dayIdx]);
  function browse(step: number) {
    if (!data?.configured) return;
    const next = (data.index + step + data.places.length) % data.places.length;
    try { localStorage.setItem(PLACE_KEY, String(next)); } catch { /* Speicher gesperrt */ }
    setIndex(next);
  }

  if (error) return <Card><p className="text-xs text-muted" role="status">Wetter gerade nicht verfügbar.</p></Card>;
  if (!data) return null;
  if (!data.configured) return <Card>
    <p className="text-sm"><span className="font-semibold">Wetter</span> <span className="text-muted">· Lege deinen Ort fest, um hier den Tagesverlauf zu sehen.</span></p>
    <Link href="/einstellungen" className="mt-2 inline-block py-1 text-xs font-semibold text-accent">Ort in den Einstellungen festlegen →</Link>
  </Card>;

  const { current, day } = data;
  const isToday = data.now_hour != null;
  const many = data.places.length > 1;
  const arrow = "flex h-8 w-8 items-center justify-center rounded border border-line text-accent hover:border-accent";
  return <Card>
    <div className="mb-3 flex items-center gap-2">
      <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">{data.place}</h2>
      {many && <>
        <span className="flex gap-1" aria-hidden="true">{data.places.map((p, i) => <span key={p} className={`h-1.5 w-1.5 rounded-full ${i === data.index ? "bg-accent" : "bg-line"}`} />)}</span>
        <button type="button" aria-label="Vorheriger Ort" onClick={() => browse(-1)} className={arrow}>‹</button>
        <button type="button" aria-label="Nächster Ort" onClick={() => browse(1)} className={arrow}>›</button>
      </>}
    </div>
    <div className="-mx-1 mb-4 flex gap-1 overflow-x-auto px-1 pb-1" role="tablist" aria-label="Wettertag">
      {data.days.map((d, i) => <button key={d.date} type="button" role="tab" aria-selected={i === dayIdx} onClick={() => setDayIdx(i)}
        aria-label={`${i === 0 ? "Heute" : weekday(d.date)}: ${d.text}, ${de0(d.temp_max)} bis ${de0(d.temp_min)} Grad, Regen bis ${d.rain_prob_max ?? 0} %`}
        className={`flex min-w-[3.6rem] flex-1 flex-col items-center gap-0.5 rounded-lg border px-1 py-1.5 text-[11px] transition-colors ${i === dayIdx ? "border-accent bg-accent/5" : "border-transparent hover:border-line"}`}>
        <span className={`font-semibold ${i === dayIdx ? "text-accent" : ""}`}>{i === 0 ? "Heute" : weekday(d.date)}</span>
        <WeatherIcon icon={d.icon} size={20} />
        <span className="tabular-nums"><strong>{de0(d.temp_max)}°</strong> <span className="text-muted">{de0(d.temp_min)}°</span></span>
      </button>)}
    </div>
    <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      {isToday ? <div className="flex items-center gap-3">
        <WeatherIcon icon={current.icon} night={!current.is_day} size={44} />
        <div>
          <p className="font-display text-3xl font-extrabold leading-none tracking-tight">{de0(current.temp)}<span className="text-lg font-semibold text-muted">°C</span></p>
          <p className="mt-1 text-sm">{current.text} <span className="text-xs text-muted">· gefühlt {de0(current.feels_like)}°</span></p>
        </div>
      </div> : <div className="flex items-center gap-3">
        <WeatherIcon icon={day.icon} size={44} />
        <div>
          <p className="font-display text-xl font-extrabold leading-none tracking-tight">{weekday(data.date)}, {data.date.slice(8, 10)}.{data.date.slice(5, 7)}.</p>
          <p className="mt-1 text-sm">{day.text}</p>
        </div>
      </div>}
      <div className="text-xs text-muted sm:text-right">
        <p className="text-sm text-ink"><span className="font-semibold">↑ {de0(day.temp_max)}°</span> · ↓ {de0(day.temp_min)}°</p>
        <p className="mt-1">{day.rain_mm > 0 ? `${de(day.rain_mm, 1)} mm Regen · bis ${day.rain_prob_max ?? 0} %` : "Kein Regen erwartet"} · {isToday ? `Wind ${de0(current.wind_kmh)} km/h` : `Wind bis ${de0(day.wind_max_kmh)} km/h`}</p>
        <p className="mt-1">☀ {clock(day.sunrise)}–{clock(day.sunset)}</p>
      </div>
    </div>
    {data.hours.length > 1 && <HourChart hours={data.hours} nowHour={data.now_hour} run={data.run} />}
    <RunAdviceBlock run={data.run} date={data.date} isToday={isToday} />
  </Card>;
}
