"use client";

import Link from "next/link";
import { Card, PageTitle } from "@/components/ui";
import { ScaleWeigh } from "@/components/ScaleWeigh";

// Eigene Seite, damit „Wiegen“ als Lesezeichen/Startbildschirm-Verknüpfung direkt aufgeht.
export default function Wiegen() {
  return <>
    <PageTitle title="Wiegen" sub="Arboleaf-Waage direkt per Bluetooth" />
    <Card className="min-w-0"><ScaleWeigh /></Card>
    <p className="mt-3 text-xs"><Link className="py-2 text-accent underline underline-offset-4" href="/koerper">Zum Gewichtsverlauf</Link></p>
  </>;
}
