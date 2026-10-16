"use client";

import { useCallback, useEffect, useState } from "react";
import { Cinzel } from "next/font/google";
import { api, type Achievements, type Hero } from "@/lib/api";
import { PageTitle, Loading, ApiError } from "@/components/ui";
import { HeroBags, HeroCharacter, HeroHeader, HeroLog, HeroRules, HeroVaultCard } from "@/components/Hero";
import { AchievementsGrid, AchievementsSummary } from "@/components/Achievements";

const cinzel = Cinzel({ subsets: ["latin"], weight: ["600", "700"], variable: "--font-cinzel" });

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

  return (
    <div className={`wow ${cinzel.variable}`}>
      <PageTitle title="Heldenreise" sub="Dein Training als Rollenspiel – Klasse, Stufe, Beute und Erfolge aus echten Daten" />
      {err ? <ApiError error={err} /> : !hero ? <Loading /> : (
        <div className="space-y-4">
          <HeroHeader data={hero} />
          <div className="grid items-start gap-4 xl:grid-cols-2 [&>*]:min-w-0">
            <HeroCharacter data={hero} />
            <HeroVaultCard data={hero} onClaim={claim} />
          </div>
          <HeroBags items={hero.inventory} />
          <div className="grid items-start gap-4 xl:grid-cols-2 [&>*]:min-w-0">
            <HeroLog data={hero} />
            <HeroRules data={hero} />
          </div>
          <section id="erfolge" className="scroll-mt-20" aria-label="Erfolge">
            {ach ? <><AchievementsSummary data={ach} showLevel={false} /><div className="mt-4"><AchievementsGrid data={ach} /></div></> : <Loading />}
          </section>
        </div>
      )}
    </div>
  );
}
