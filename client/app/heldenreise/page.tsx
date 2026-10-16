"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Cinzel } from "next/font/google";
import { api, type Achievements, type Hero, type HeroItem } from "@/lib/api";
import { PageTitle, Loading, ApiError } from "@/components/ui";
import { HeroBags, HeroCharacter, HeroHeader, HeroLog, HeroRules, HeroVaultCard, LootReveal, type Gear } from "@/components/Hero";
import { HeroChronicle, LevelUpBanner } from "@/components/HeroVisuals";
import { HeroQuestLog, HeroTalentTree } from "@/components/HeroTalents";
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
  const [reveal, setReveal] = useState<HeroItem | null>(null);
  const claim = useCallback(async (week: string, slot: number) => {
    const { item } = await api.heroClaim(week, slot);
    setReveal(item);
    await load();
  }, [load]);
  // Gesehene Beute merken (localStorage); beim ersten Besuch gilt alles als gesehen.
  const [seen, setSeen] = useState<Set<string> | null>(null);
  useEffect(() => {
    if (!hero || seen) return;
    let ids: string[] | null = null;
    try { ids = JSON.parse(localStorage.getItem("milon.hero.seen") || "null"); } catch { /* leer */ }
    const initial = new Set(ids ?? hero.inventory.map((it) => it.id));
    try { localStorage.setItem("milon.hero.seen", JSON.stringify([...initial])); } catch { /* ohne Speicher */ }
    setSeen(initial);
  }, [hero, seen]);
  const markSeen = useCallback((id: string) => setSeen((prev) => {
    if (!prev || prev.has(id)) return prev;
    const next = new Set(prev).add(id);
    try { localStorage.setItem("milon.hero.seen", JSON.stringify([...next])); } catch { /* ohne Speicher */ }
    return next;
  }), []);
  const [dragging, setDragging] = useState<string | null>(null);
  const gear = useMemo<Gear>(() => ({
    equipment: hero?.equipment ?? {},
    equip: async (itemId) => { await api.heroEquip(itemId); await load(); },
    unequip: async (slot) => { await api.heroUnequip(slot); await load(); },
    equipBest: async () => { await api.heroEquipBest(); await load(); },
    dragging, setDragging,
    isNew: (id) => !!seen && !seen.has(id),
    markSeen,
  }), [hero, load, dragging, seen, markSeen]);

  return (
    <div className={`wow ${cinzel.variable}`}>
      <PageTitle title="Heldenreise" sub="Dein Training als Rollenspiel – Klasse, Stufe, Beute und Erfolge aus echten Daten" />
      {err ? <ApiError error={err} /> : !hero ? <Loading /> : (
        <div className="space-y-4">
          <HeroHeader data={hero} onSpec={async (spec) => { await api.heroSpec(spec); await load(); }} />
          <LevelUpBanner level={hero.hero.level} title={hero.hero.title} />
          {reveal && <LootReveal item={reveal} onClose={() => setReveal(null)} />}
          <div className="grid items-start gap-4 xl:grid-cols-2 [&>*]:min-w-0">
            <HeroCharacter data={hero} gear={gear} />
            <div className="space-y-4">
              <HeroVaultCard data={hero} onClaim={claim} />
              <HeroQuestLog data={hero} />
            </div>
          </div>
          <HeroTalentTree data={hero} onChoose={async (row, choice) => { await api.heroTalent(row, choice); await load(); }} />
          <HeroBags items={hero.inventory} gear={gear} />
          <HeroChronicle data={hero} />
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
