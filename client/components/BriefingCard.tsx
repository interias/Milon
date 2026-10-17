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

// Morgenbriefing des Coaches: entsteht automatisch nach dem Schlaf-Sync, spätestens 1 h vor Sonnenaufgang.
export function BriefingCard() {
  const [data, setData] = useState<BriefingToday | null>(null);
  useEffect(() => { api.coachBriefingToday().then(setData).catch(() => {}); }, []);
  if (!data) return null;
  const b = data.briefing;
  const time = b ? new Date(b.created_at).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }) : null;
  return (
    <Card className="mt-4">
      <CardTitle title="Morgenbriefing" sub={b ? `Coach · heute ${time} Uhr · nur Vorschläge` : "Coach · entsteht nach dem Schlaf-Sync, spätestens 1 h vor Sonnenaufgang"} />
      {b ? <Markdown>{b.content}</Markdown>
        : <p className="text-xs text-muted" role="status">Für heute liegt noch kein Briefing vor.</p>}
    </Card>
  );
}
