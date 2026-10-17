"use client";

import { useEffect, useState } from "react";
import { api, type WeeklyAutoCurrent } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { Markdown } from "@/components/Markdown";
import { dm } from "@/lib/format";

const SEEN_KEY = "milon.weekly.seen";   // Id des zuletzt weggeklickten Berichts (je Gerät)
const SEEN_EVENT = "milon:weekly-seen";

function readSeen(): number | null {
  try { const v = localStorage.getItem(SEEN_KEY); return v ? Number(v) : null; } catch { return null; }
}

// Erste Zeile des Wochenberichts („**Woche:** …“) als Klartext — für das Helden-Widget.
export function weeklyHeadline(content: string): string {
  const first = content.split("\n").find((line) => line.trim()) ?? "";
  return first.replace(/[*_#`>]/g, "").replace(/^\s*Woche:\s*/i, "").trim();
}

// Bericht der zuletzt beendeten Woche, solange die neue läuft; `unread` bis er weggeklickt wurde.
export function useWeeklyReport() {
  const [data, setData] = useState<WeeklyAutoCurrent | null>(null);
  const [seen, setSeen] = useState<number | null>(null);
  useEffect(() => {
    api.coachWeeklyAuto().then(setData).catch(() => {});
    setSeen(readSeen());
    const sync = () => setSeen(readSeen());
    window.addEventListener(SEEN_EVENT, sync);
    return () => window.removeEventListener(SEEN_EVENT, sync);
  }, []);
  const report = data?.report ?? null;
  const dismiss = () => {
    if (!report) return;
    try { localStorage.setItem(SEEN_KEY, String(report.id)); } catch { /* Speicher gesperrt: nur bis zum Neuladen */ }
    setSeen(report.id);
    window.dispatchEvent(new Event(SEEN_EVENT));
  };
  return { data, report, unread: !!report && seen !== report.id, dismiss };
}

// Wochenbericht des Coaches: entsteht automatisch Sonntagnacht (23:30), bleibt sichtbar, solange die neue Woche läuft.
export function WeeklyReportCard() {
  const { data, report, unread, dismiss } = useWeeklyReport();
  if (!data || !report || !unread) return null;
  return (
    <Card className="mt-4">
      <div className="flex items-start justify-between gap-3">
        <CardTitle title="Wochenbericht" sub={`Coach · ${dm(data.week_from)}–${dm(data.week_to)} · nur Vorschläge`} />
        <button type="button" onClick={dismiss} aria-label="Wochenbericht ausblenden"
                className="shrink-0 rounded border border-border px-2 py-1 text-xs text-muted hover:text-text">Ausblenden</button>
      </div>
      <Markdown>{report.content}</Markdown>
    </Card>
  );
}
