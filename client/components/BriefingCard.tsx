"use client";

import { useEffect, useState } from "react";
import { api, type BriefingToday } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { Markdown } from "@/components/Markdown";

// Erste Zeile des Briefings („**Heute:** …“) als Klartext — für das Helden-Widget.
export function briefingHeadline(content: string): string {
  const first = content.split("\n").find((line) => line.trim()) ?? "";
  return first.replace(/[*_#`>]/g, "").replace(/^\s*Heute:\s*/i, "").trim();
}

// Ausgeblendet gilt je Gerät für den Tag des Briefings (localStorage = Datum).
const HIDDEN_KEY = "milon.briefing.hidden";
function readHidden(): string | null {
  try { return localStorage.getItem(HIDDEN_KEY); } catch { return null; }
}
function writeHidden(day: string | null) {
  try { if (day) localStorage.setItem(HIDDEN_KEY, day); else localStorage.removeItem(HIDDEN_KEY); } catch { /* ohne Speicher bleibt es offen */ }
}

// Morgenbriefing des Coaches: entsteht automatisch nach dem Schlaf-Sync, spätestens 1 h vor Sonnenaufgang.
export function BriefingCard() {
  const [data, setData] = useState<BriefingToday | null>(null);
  const [hiddenDay, setHiddenDay] = useState<string | null>(null);
  useEffect(() => { setHiddenDay(readHidden()); api.coachBriefingToday().then(setData).catch(() => {}); }, []);
  if (!data) return null;
  const b = data.briefing;
  const time = b ? new Date(b.created_at).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }) : null;
  const hide = (day: string | null) => { writeHidden(day); setHiddenDay(day); };
  if (hiddenDay === data.date) {
    return (
      <Card className="mt-4 py-2! sm:py-2!">
        <div className="flex items-center gap-3 text-sm">
          <span className="shrink-0 text-xs font-semibold text-muted">Briefing</span>
          <span className="min-w-0 flex-1 truncate">{b ? briefingHeadline(b.content) : "Für heute noch keins."}</span>
          <button type="button" onClick={() => hide(null)} className="shrink-0 py-1 text-xs font-semibold text-accent">Einblenden</button>
        </div>
      </Card>
    );
  }
  return (
    <Card className="mt-4">
      <div className="flex items-start justify-between gap-3">
        <CardTitle title="Morgenbriefing" sub={b ? `Coach · heute ${time} Uhr · nur Vorschläge` : "Coach · entsteht nach dem Schlaf-Sync, spätestens 1 h vor Sonnenaufgang"} />
        <button type="button" onClick={() => hide(data.date)} className="shrink-0 py-1 text-xs font-semibold text-muted underline underline-offset-4">Für heute ausblenden</button>
      </div>
      {b ? <Markdown>{b.content}</Markdown>
        : <p className="text-xs text-muted" role="status">Für heute liegt noch kein Briefing vor.</p>}
    </Card>
  );
}
