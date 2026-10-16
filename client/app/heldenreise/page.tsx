"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Cinzel } from "next/font/google";
import { api, type Achievements, type Hero, type HeroItem, type Weather } from "@/lib/api";
import { play } from "@/lib/hero-sound";
import { WelcomeBack, useLastVisit } from "@/components/HeroLife";
import { HeroEvent, HeroTrainer } from "@/components/HeroEvents";
import { HeroDuel, HeroMounts } from "@/components/HeroDuels";
import { PageTitle, Loading, ApiError } from "@/components/ui";
import { HeroBags, HeroCharacter, HeroHeader, HeroLog, HeroRules, HeroVaultCard, LootReveal, type Gear } from "@/components/Hero";
import { HeroChronicle, LevelUpBanner } from "@/components/HeroVisuals";
import { HeroQuestLog, HeroTalentTree } from "@/components/HeroTalents";
import { HeroDungeons, HeroRaid } from "@/components/HeroBosses";
import { HeroReputation, HeroTitleChooser } from "@/components/HeroSocial";
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
    api.weather(0, 0).then(setWeather).catch(() => {});
  }, [load]);
  const [weather, setWeather] = useState<Weather | null>(null);
  const visit = useLastVisit(hero);
  const [welcomeDone, setWelcomeDone] = useState(false);
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
  const [titles, setTitles] = useState(false);
  const gear = useMemo<Gear>(() => ({
    equipment: hero?.equipment ?? {},
    equip: async (itemId) => { await api.heroEquip(itemId); play("equip"); await load(); },
    unequip: async (slot) => { await api.heroUnequip(slot); play("equip"); await load(); },
    equipBest: async () => { await api.heroEquipBest(); play("equip"); await load(); },
    disenchant: async (itemId) => { await api.heroDisenchant(itemId); play("chest"); await load(); },
    upgrade: async (itemId) => { await api.heroUpgrade(itemId); play("loot", "lila"); await load(); },
    dust: hero?.dust ?? 0,
    dragging, setDragging,
    isNew: (id) => !!seen && !seen.has(id),
    markSeen,
  }), [hero, load, dragging, seen, markSeen]);

  // Tabs: aktiver Tab steht im Hash (#erfolge usw.), damit Links direkt hinführen.
  const [tab, setTab] = useState<TabKey>("charakter");
  useEffect(() => {
    const read = () => {
      const h = window.location.hash.slice(1) as TabKey;
      if (TABS.some((t) => t.key === h)) setTab(h);
    };
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);
  const choose = (key: TabKey) => {
    setTab(key);
    play("click");
    history.replaceState(null, "", `#${key}`);
  };

  const hints: Partial<Record<TabKey, string>> = {};
  if (hero) {
    if (hero.vault.veteran || hero.vault.claimable.length || (hero.daily?.today && !hero.daily.today.done)) hints.abenteuer = "!";
    const upgrade = hero.inventory.some((it) => !it.equipped && it.ilvl > (hero.equipment[it.slot]?.ilvl ?? 0));
    if (upgrade || hero.inventory.some((it) => !it.equipped && gear.isNew(it.id))) hints.charakter = "▲";
    if (hero.talents.some((r) => r.unlocked && r.options.length && !r.chosen)) hints.talente = "•";
  }

  return (
    <div className={`wow ${cinzel.variable}`}>
      <PageTitle title="Heldenreise" sub="Dein Training als Rollenspiel – Klasse, Stufe, Beute und Erfolge aus echten Daten" />
      {err ? <ApiError error={err} /> : !hero ? <Loading /> : (
        <div className="space-y-4">
          <HeroHeader data={hero} onSpec={async (spec) => { await api.heroSpec(spec); await load(); }} onTitle={() => setTitles(true)} fromXp={visit?.fromXp} />
          {visit && !welcomeDone && <WelcomeBack news={visit.news} gained={visit.gained} onClose={() => setWelcomeDone(true)} />}
          {titles && <HeroTitleChooser data={hero} onChoose={async (key) => { await api.heroTitle(key); await load(); }} onClose={() => setTitles(false)} />}
          <LevelUpBanner level={hero.hero.level} title={hero.hero.title} />
          {reveal && <LootReveal item={reveal} onClose={() => setReveal(null)} />}
          <div className="xl:hidden"><HeroLog data={hero} listClass="max-h-36" /></div>
          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
            <div className="min-w-0">
              <div role="tablist" aria-label="Bereiche der Heldenreise" className="wow-tabs mb-4 flex gap-1 overflow-x-auto overflow-y-hidden pr-2 pt-2">
                {TABS.map((t) => (
                  <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} id={`tab-${t.key}`}
                          aria-controls={`panel-${t.key}`} onClick={() => choose(t.key)}
                          className={`wow-tab shrink-0 ${tab === t.key ? "wow-tab-active" : ""}`}>
                    {t.label}
                    {hints[t.key] && <span className="wow-tab-hint" aria-label="Neues">{hints[t.key]}</span>}
                  </button>
                ))}
              </div>
              <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} key={tab} className="@container ach-fade space-y-4">
                {tab === "charakter" && <>
                  <HeroCharacter data={hero} gear={gear} weather={weather} />
                  <HeroBags items={hero.inventory} gear={gear} />
                  <HeroMounts data={hero} onChoose={async (key) => { await api.heroMount(key); play("equip"); await load(); }} />
                </>}
                {tab === "abenteuer" && <>
                  <div className="grid items-start gap-4 @3xl:grid-cols-2 [&>*]:min-w-0">
                    <HeroTrainer data={hero} />
                    <HeroEvent data={hero} />
                  </div>
                  <div className="grid items-start gap-4 @3xl:grid-cols-2 [&>*]:min-w-0">
                    <HeroVaultCard data={hero} onClaim={claim} />
                    <HeroQuestLog data={hero} />
                  </div>
                  <div className="grid items-start gap-4 @3xl:grid-cols-2 [&>*]:min-w-0">
                    <HeroRaid data={hero} />
                    <HeroDungeons data={hero} />
                  </div>
                  <HeroDuel data={hero} />
                </>}
                {tab === "talente" && <HeroTalentTree data={hero} onChoose={async (row, choice) => { await api.heroTalent(row, choice); await load(); }} />}
                {tab === "chronik" && <>
                  <HeroChronicle data={hero} />
                  <div className="grid items-start gap-4 @3xl:grid-cols-2 [&>*]:min-w-0">
                    <HeroReputation data={hero} />
                    <HeroRules data={hero} />
                  </div>
                </>}
                {tab === "erfolge" && (ach
                  ? <><AchievementsSummary data={ach} showLevel={false} /><AchievementsGrid data={ach} /></>
                  : <Loading />)}
              </div>
            </div>
            <aside className="hidden xl:sticky xl:top-4 xl:block" aria-label="Kampflog">
              <HeroLog data={hero} listClass="max-h-[calc(100vh-9rem)]" />
            </aside>
          </div>
        </div>
      )}
    </div>
  );
}

type TabKey = "charakter" | "abenteuer" | "talente" | "chronik" | "erfolge";
const TABS: { key: TabKey; label: string }[] = [
  { key: "charakter", label: "Charakter" },
  { key: "abenteuer", label: "Abenteuer" },
  { key: "talente", label: "Talente" },
  { key: "chronik", label: "Chronik" },
  { key: "erfolge", label: "Erfolge" },
];
