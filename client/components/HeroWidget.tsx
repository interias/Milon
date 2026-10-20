"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Briefing, type Hero } from "@/lib/api";
import { briefingHeadline } from "@/components/BriefingCard";
import { useWeeklyReport, weeklyHeadline } from "@/components/WeeklyReportCard";
import { de0 } from "@/lib/format";

// Kompakter Einheitenrahmen für die Übersicht: Stufe, EP, Tagesaufgabe, Truhe, Event — Link zur Heldenreise.
export function HeroWidget() {
  const [hero, setHero] = useState<Hero | null>(null);
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  useEffect(() => { api.hero().then(setHero).catch(() => {}); }, []);
  useEffect(() => { api.coachBriefingToday().then((d) => setBriefing(d.briefing)).catch(() => {}); }, []);
  const weekly = useWeeklyReport();
  if (!hero) return null;
  const h = hero.hero, cur = hero.vault.current, d = hero.daily?.today, ev = hero.event;
  const max = Math.max(...cur.slots.map((s) => s.threshold));
  const chips: [string, string, boolean][] = [
    ...(d ? [[d.done ? "✓" : "!", `Tagesaufgabe: ${d.title}`, !d.done] as [string, string, boolean]] : []),
    [`${cur.runs}/${max}`, "Läufe/Fahrten für die Wochentruhe", false],
    ...(ev ? [[`${ev.tokens}/${ev.goal}`, ev.name, false] as [string, string, boolean]] : []),
    ...(hero.vault.claimable.length || hero.vault.veteran ? [["!", "Truhe wählbar", true] as [string, string, boolean]] : []),
  ];
  return (
    <Link href="/heldenreise" aria-label="Zur Heldenreise"
          className="block rounded-card border p-3 transition hover:brightness-110 sm:p-4"
          style={{ borderColor: "#5a4424", background: "radial-gradient(600px 160px at 0% 0%, rgba(120,82,28,.5), transparent 70%), linear-gradient(180deg, #17130f, #0d0a07)", color: "#efe3c8" }}>
      <div className="flex flex-wrap items-center gap-3">
        <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full font-display text-sm font-extrabold"
              style={{ color: "#ffd100", background: "#0b0907", boxShadow: `0 0 0 2px #000, 0 0 0 3px ${h.class_color}, 0 0 10px ${h.class_color}66` }}>{h.level}</span>
        <div className="min-w-[160px] flex-1">
          <p className="text-sm font-bold" style={{ color: h.class_color }}>
            {h.class_label} <span className="font-normal text-[#a99c80]">· &lt;{h.title_chosen ?? h.title}&gt; · {hero.companion?.name ?? ""}</span>
          </p>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-black/60" style={{ boxShadow: "0 0 0 1px #5b4526" }}>
            <div className="h-full" style={{ width: `${h.progress * 100}%`, background: "linear-gradient(180deg, #b36cf0, #8f3fd6)" }} />
          </div>
          <p className="mt-0.5 text-[11px] text-[#a99c80]">noch {de0(h.next - h.xp)} EP bis Stufe {h.level + 1} · diese Woche +{de0(h.week_xp)} EP</p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {chips.map(([badge, label, alert]) => (
            <span key={label} className="flex items-center gap-1.5 rounded border px-2 py-1 text-[11px]"
                  style={{ borderColor: alert ? "#ffd100" : "#3a2d1a", color: alert ? "#ffd100" : "#cfc3a8" }}>
              <b>{badge}</b>{label}
            </span>
          ))}
        </div>
      </div>
      {weekly.unread && weekly.report && <p className="mt-2 truncate border-t pt-2 text-[11px]" style={{ borderColor: "#3a2d1a", color: "#cfc3a8" }}>
        <b style={{ color: "#ffd100" }}>! Wochenbericht bereit:</b> {weeklyHeadline(weekly.report.content)}
      </p>}
      {briefing && <p className="mt-2 truncate border-t pt-2 text-[11px]" style={{ borderColor: "#3a2d1a", color: "#cfc3a8" }}>
        <b style={{ color: "#ffd100" }}>Morgenbriefing:</b> {briefingHeadline(briefing.content)}
      </p>}
    </Link>
  );
}
