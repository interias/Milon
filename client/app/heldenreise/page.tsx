"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Achievements, type Hero } from "@/lib/api";
import { PageTitle, Loading, ApiError } from "@/components/ui";
import { HeroAttributes, HeroHeader, HeroInventory, HeroLog, HeroRules, HeroVaultCard } from "@/components/Hero";
import { AchievementsGrid, AchievementsSummary } from "@/components/Achievements";

export default function Heldenreise() {
  const [hero, setHero] = useState<Hero | null>(null);
  const [ach, setAch] = useState<Achievements | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api.hero().then(setHero).catch((e) => setErr(String(e))), []);
  useEffect(() => {
    load();
    api.runAchievements().then(setAch).catch(() => {});
  }, [load]);
  const claim = useCallback(async (week: string, slot: number) => { await api.heroClaim(week, slot); await load(); }, [load]);

  if (err) return <><PageTitle title="Heldenreise" /><ApiError error={err} /></>;
  if (!hero) return <><PageTitle title="Heldenreise" /><Loading /></>;
  return <>
    <PageTitle title="Heldenreise" sub="Dein Training als Rollenspiel – Klasse, Level, Beute und Erfolge aus echten Daten" />
    <div className="space-y-4">
      <HeroHeader data={hero} />
      <div className="grid items-start gap-4 xl:grid-cols-2 [&>*]:min-w-0">
        <HeroVaultCard data={hero} onClaim={claim} />
        <HeroAttributes items={hero.attributes} />
      </div>
      <HeroInventory items={hero.inventory} />
      <div className="grid items-start gap-4 xl:grid-cols-2 [&>*]:min-w-0">
        <HeroLog data={hero} />
        <HeroRules data={hero} />
      </div>
      <section id="erfolge" className="scroll-mt-20" aria-label="Erfolge">
        {ach ? <><AchievementsSummary data={ach} showLevel={false} /><div className="mt-4"><AchievementsGrid data={ach} /></div></> : <Loading />}
      </section>
    </div>
  </>;
}
