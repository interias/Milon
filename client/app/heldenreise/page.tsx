"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Cinzel } from "next/font/google";
import { api, type Achievements, type Hero, type HeroItem, type Weather } from "@/lib/api";
import { play } from "@/lib/hero-sound";
import { WelcomeBack, useLastVisit } from "@/components/HeroLife";
import { HeroEvent, HeroTrainer } from "@/components/HeroEvents";
import { HeroDuel, HeroMounts, HeroSagaCard } from "@/components/HeroDuels";
import { HeroAuction, HeroPotions } from "@/components/HeroTrade";
import { PageTitle, Loading, ApiError } from "@/components/ui";
import { HeroBags, HeroCharacter, HeroHeader, HeroLinkContext, HeroLog, HeroLogTicker, HeroPurse, HeroRules, HeroVaultCard, Icon, LootReveal, type Gear } from "@/components/Hero";
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
    sell: async (itemId) => { await api.heroSell(itemId); play("loot", "weiss"); await load(); },
    dust: hero?.dust ?? 0,
    dragging, setDragging,
    isNew: (id) => !!seen && !seen.has(id),
    markSeen,
  }), [hero, load, dragging, seen, markSeen]);

  // Tabs: aktiver Tab steht im Hash (#erfolge usw.), damit Links direkt hinführen.
  const [tab, setTab] = useState<TabKey>("charakter");
  useEffect(() => {
    const read = () => {
      const raw = window.location.hash.slice(1);
      const h = (raw === "erfolge" ? "sammlung" : raw) as TabKey;  // alter Link der Laufen-Seite
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
    // Auf dem Handy beginnt der neue Tab direkt unter der (klebenden) Tab-Leiste.
    const bar = document.querySelector<HTMLElement>("[role=tablist]");
    if (bar && window.innerWidth < 640) {
      const top = bar.getBoundingClientRect().top + window.scrollY - 68;
      if (window.scrollY > top) window.scrollTo({ top });
    }
  };

  const buyThing = useCallback(async (kind: "listing" | "potion", ref: string) => {
    await api.heroBuy(kind, ref);
    play("loot", "lila");
    await load();
  }, [load]);

  const links = useMemo(() => ({
    items: new Map((hero?.inventory ?? []).map((it) => [it.id, it] as const)),
    achievements: new Map((ach?.achievements ?? []).map((a) => [a.name, a] as const)),
  }), [hero, ach]);

  const hints: Partial<Record<TabKey, string>> = {};
  if (hero) {
    if (hero.vault.veteran || hero.vault.claimable.length || (hero.daily?.today && !hero.daily.today.done)) hints.abenteuer = "!";
    const upgrade = hero.inventory.some((it) => !it.equipped && it.ilvl > (hero.equipment[it.slot]?.ilvl ?? 0));
    if (upgrade || hero.inventory.some((it) => !it.equipped && gear.isNew(it.id))) hints.charakter = "▲";
    if (hero.talents.some((r) => r.unlocked && r.options.length && !r.chosen)) hints.talente = "•";
  }

  return (
    <HeroLinkContext.Provider value={links}>
    <div className={`wow ${cinzel.variable}`}>
      <div className="hidden sm:block"><PageTitle title="Heldenreise" sub="Dein Training als Rollenspiel – Klasse, Stufe, Beute und Erfolge aus echten Daten" /></div>
      <h1 className="mb-3 font-display text-xl font-bold sm:hidden" style={{ color: "#ffd100" }}>Heldenreise</h1>
      {err ? <ApiError error={err} /> : !hero ? <Loading /> : (
        <div className="space-y-4">
          <HeroHeader data={hero} onSpec={async (spec) => { await api.heroSpec(spec); await load(); }} onTitle={() => setTitles(true)} fromXp={visit?.fromXp} />
          {visit && !welcomeDone && <WelcomeBack news={visit.news} gained={visit.gained} onClose={() => setWelcomeDone(true)} />}
          {titles && <HeroTitleChooser data={hero} onChoose={async (key) => { await api.heroTitle(key); await load(); }} onClose={() => setTitles(false)} />}
          <LevelUpBanner level={hero.hero.level} title={hero.hero.title} />
          {reveal && <LootReveal item={reveal} onClose={() => setReveal(null)} />}
          <HeroLogTicker data={hero} onOpen={() => choose("log")} />
          <div>
            <div className="min-w-0">
              <div role="tablist" aria-label="Bereiche der Heldenreise"
                   className="wow-tabs sticky top-[61px] z-20 -mx-1 mb-4 grid grid-cols-7 gap-0.5 px-1 pt-2 sm:static sm:mx-0 sm:flex sm:w-0 sm:min-w-full sm:overflow-x-auto sm:overflow-y-hidden sm:px-0 sm:pr-2">
                {TABS.map((t) => (
                  <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} id={`tab-${t.key}`}
                          aria-controls={`panel-${t.key}`} onClick={() => choose(t.key)}
                          className={`wow-tab shrink-0 ${tab === t.key ? "wow-tab-active" : ""}`}>
                    <span className="sm:hidden"><Icon size={18}>{TAB_ICON[t.key]}</Icon></span>
                    <span className="sm:hidden">{t.short}</span>
                    <span className="hidden sm:inline">{t.label}</span>
                    {hints[t.key] && <span className="wow-tab-hint" aria-label="Neues">{hints[t.key]}</span>}
                  </button>
                ))}
              </div>
              <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} key={tab} className="@container ach-fade space-y-4">
                {tab === "charakter" && <>
                  <HeroCharacter data={hero} gear={gear} weather={weather} />
                  <HeroBags items={hero.inventory} gear={gear} data={hero} />
                </>}
                {tab === "abenteuer" && <>
                  <nav aria-label="Abschnitte" className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1 sm:hidden">
                    {JUMPS.map(([id, label]) => (
                      <a key={id} href={`#${id}`} onClick={(e) => {
                           e.preventDefault();
                           const el = document.getElementById(id);
                           if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 128 });
                         }}
                         className="shrink-0 rounded-full border border-[#4b3a22] bg-black/30 px-2.5 py-1 text-[11px] text-[#cfc3a8]">{label}</a>
                    ))}
                  </nav>
                  <div className="grid items-start gap-4 @3xl:grid-cols-2 [&>*]:min-w-0 [&>*]:scroll-mt-32">
                    <div id="ab-gorm"><HeroTrainer data={hero} /></div>
                    <div id="ab-event"><HeroEvent data={hero} /></div>
                  </div>
                  <div className="grid items-start gap-4 @3xl:grid-cols-2 [&>*]:min-w-0 [&>*]:scroll-mt-32">
                    <div id="ab-truhe"><HeroVaultCard data={hero} onClaim={claim} /></div>
                    <div id="ab-auftraege"><HeroQuestLog data={hero} /></div>
                  </div>
                  <div className="grid items-start gap-4 @3xl:grid-cols-2 [&>*]:min-w-0 [&>*]:scroll-mt-32">
                    <div id="ab-bosse"><HeroRaid data={hero} /></div>
                    <div id="ab-instanzen"><HeroDungeons data={hero} /></div>
                  </div>
                  <div id="ab-duell" className="scroll-mt-32"><HeroDuel data={hero} /></div>
                </>}
                {tab === "talente" && <HeroTalentTree data={hero} onChoose={async (row, choice) => { await api.heroTalent(row, choice); await load(); }} />}
                {tab === "handel" && <>
                  <HeroAuction data={hero} gear={gear} onBuy={buyThing} />
                  <div className="grid items-start gap-4 @3xl:grid-cols-2 [&>*]:min-w-0">
                    <HeroPotions data={hero} onBuy={buyThing} onDrink={async (key) => { await api.heroDrink(key); play("quest"); await load(); }} />
                    <HeroPurse data={hero} />
                  </div>
                </>}
                {tab === "chronik" && <>
                  <HeroSagaCard />
                  <HeroChronicle data={hero} />
                  <div className="grid items-start gap-4 @3xl:grid-cols-2 [&>*]:min-w-0">
                    <HeroReputation data={hero} />
                    <HeroRules data={hero} />
                  </div>
                </>}
                {tab === "sammlung" && <>
                  <HeroMounts data={hero} onChoose={async (key) => { await api.heroMount(key); play("equip"); await load(); }} />
                  {ach ? <><AchievementsSummary data={ach} showLevel={false} /><AchievementsGrid data={ach} collapsible /></> : <Loading />}
                </>}
                {tab === "log" && <HeroLog data={hero} listClass="max-h-[70vh]" />}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
    </HeroLinkContext.Provider>
  );
}

const JUMPS: [string, string][] = [["ab-gorm", "Gorm"], ["ab-event", "Event"], ["ab-truhe", "Truhe"], ["ab-auftraege", "Aufträge"],
  ["ab-bosse", "Bosse"], ["ab-instanzen", "Instanzen"], ["ab-duell", "Duell"]];
type TabKey = "charakter" | "abenteuer" | "talente" | "handel" | "chronik" | "sammlung" | "log";
const TABS: { key: TabKey; label: string; short: string }[] = [
  { key: "charakter", label: "Charakter", short: "Held" },
  { key: "abenteuer", label: "Abenteuer", short: "Reise" },
  { key: "talente", label: "Talente", short: "Talente" },
  { key: "handel", label: "Handel", short: "Handel" },
  { key: "chronik", label: "Chronik", short: "Saga" },
  { key: "sammlung", label: "Sammlung", short: "Erfolge" },
  { key: "log", label: "Log", short: "Log" },
];
const TAB_ICON: Record<TabKey, React.ReactNode> = {
  charakter: <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z" />,
  abenteuer: <><circle cx="12" cy="12" r="10" /><path d="m16.24 7.76-2.12 6.36-6.36 2.12 2.12-6.36 6.36-2.12z" /></>,
  talente: <path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z" />,
  handel: <><circle cx="8" cy="8" r="6" /><path d="M18.09 10.37A6 6 0 1 1 10.34 18" /><path d="M7 6h1v4" /><path d="m16.71 13.88.7.71-2.82 2.82" /></>,
  chronik: <><path d="M15 12h-5" /><path d="M15 8h-5" /><path d="M19 17V5a2 2 0 0 0-2-2H4" /><path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3" /></>,
  log: <><path d="M14 2v4a2 2 0 0 0 2 2h4" /><path d="M4 22h14a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v4" /><path d="m3 15 2 2 4-4" /></>,
  sammlung: <><path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6" /><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18" /><path d="M4 22h16" /><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22" /><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22" /><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z" /></>,
};
