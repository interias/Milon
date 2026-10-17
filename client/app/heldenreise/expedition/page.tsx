"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Cinzel } from "next/font/google";
import { api, LiveError, type Hero, type HeroLiveFind, type HeroLiveState } from "@/lib/api";
import { play, setSoundOn, soundOn, unlockAudio } from "@/lib/hero-sound";
import { HeroWorld, type LiveMap } from "@/components/HeroWorld";
import { ApiError, Card, CardTitle, Loading } from "@/components/ui";

const cinzel = Cinzel({ subsets: ["latin"], weight: ["600", "700"], variable: "--font-cinzel" });

const K_TOKEN = "milon.hero.livetoken";
const K_SESSION = "milon.expedition.session";
const K_RUNNING = "milon.expedition.running";
const K_WAKE = "milon.expedition.wake";
const FLUSH_MS = 15_000;
const POLL_MS = 15_000;
const FIND_LABEL: Record<HeroLiveFind["kind"], string> = {
  gebiet: "Neues Gebiet", schrein: "Schrein gefunden", schatz: "Schatz gefunden", abschnitt: "Abschnittsboss besiegt",
  verlies_entdeckt: "Verlies entdeckt", verlies: "Verlies bezwungen",
};

type Fix = { ts: number; lat: number; lon: number; acc: number };
type Geo = "aus" | "wartet" | "aktiv" | "verweigert" | "fehler" | "unsicher" | "nicht_unterstuetzt";

const store = {
  get: (k: string) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k: string, v: string | null) => { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch { /* ohne Speicher */ } },
};

const dist = (m: number) => (m >= 1000 ? `${(Math.round(m / 100) / 10).toString().replace(".", ",")} km` : `${m} m`);

function useNow(ms: number) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), ms); return () => clearInterval(t); }, [ms]);
  return now;
}

function ago(ms: number) {
  const s = Math.max(0, Math.round(ms / 1000));
  return s < 90 ? `${s} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`;
}

function Arrow({ deg }: { deg: number }) {
  return (
    <svg viewBox="-60 -60 120 120" className="h-36 w-36 shrink-0" role="img" aria-label={`Richtungspfeil, ${Math.round(deg)} Grad`} data-testid="arrow" data-deg={Math.round(deg)}>
      <circle r="56" fill="#120d08" stroke="#5a4424" strokeWidth="2" />
      {["N", "O", "S", "W"].map((c, i) => (
        <text key={c} x={Math.sin(i * Math.PI / 2) * 47} y={-Math.cos(i * Math.PI / 2) * 47 + 4} textAnchor="middle" fontSize="10" fill="#8a7a5c">{c}</text>
      ))}
      <g style={{ transform: `rotate(${deg}deg)`, transition: "transform .25s ease-out" }}>
        <path d="M0 -38L20 14L0 5L-20 14Z" fill="#ffd100" stroke="#3a2400" strokeWidth="2.5" strokeLinejoin="round" />
      </g>
    </svg>
  );
}

export default function Expedition() {
  const [token, setToken] = useState<string | null>(null);
  const [tokenInput, setTokenInput] = useState("");
  const [authErr, setAuthErr] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [hero, setHero] = useState<Hero | null>(null);
  const [heroErr, setHeroErr] = useState<string | null>(null);
  const [st, setSt] = useState<HeroLiveState | null>(null);
  const [mySession, setMySession] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [watchPick, setWatchPick] = useState<string | null>(null);
  const [visible, setVisible] = useState(true);
  const [geo, setGeo] = useState<Geo>("aus");
  const [acc, setAcc] = useState<number | null>(null);
  const [lastFix, setLastFix] = useState<number | null>(null);
  const [sent, setSent] = useState(0);
  const [postErr, setPostErr] = useState<string | null>(null);
  const [wake, setWake] = useState(false);
  const [wakeMsg, setWakeMsg] = useState<string | null>(null);
  const [sound, setSound] = useState(false);
  const [heading, setHeading] = useState<number | null>(null);
  const [compass, setCompass] = useState<"aus" | "warte" | "aktiv" | "keiner" | "verweigert">("aus");
  const [news, setNews] = useState<HeroLiveFind[]>([]);
  const now = useNow(5000);

  // Start-up: read the device-local settings (token, session, switches) once.
  useEffect(() => {
    setToken(store.get(K_TOKEN));
    setMySession(store.get(K_SESSION));
    setRunning(store.get(K_RUNNING) === "1");
    setWake(store.get(K_WAKE) === "1");
    setSound(soundOn());
    setReady(true);
  }, []);
  useEffect(() => {
    const on = () => setVisible(document.visibilityState === "visible");
    on();
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);

  // Session shown on the page: the own one while running, otherwise one picked from the server (e.g. the watch).
  const sessions = hero?.world.available ? hero.world.live?.sessions ?? [] : [];
  const viewSession = running ? mySession
    : watchPick && sessions.includes(watchPick) ? watchPick
    : mySession && sessions.includes(mySession) ? mySession
    : sessions[sessions.length - 1] ?? mySession;
  const tokenRef = useRef(token); tokenRef.current = token;
  const sessionRef = useRef(viewSession); sessionRef.current = viewSession;

  const authFail = useCallback((e: unknown) => {
    if (e instanceof LiveError && e.status === 403) setAuthErr("Die Live-Schnittstelle ist am Server aus (HERO_LIVE_TOKEN nicht gesetzt).");
    else if (e instanceof LiveError && e.status === 401) setAuthErr("Der Token passt nicht zum Server.");
    else return false;
    return true;
  }, []);

  const refresh = useCallback(async () => {
    const [h, s] = await Promise.allSettled([
      api.hero(),
      tokenRef.current && sessionRef.current ? api.heroLiveState(tokenRef.current, sessionRef.current) : Promise.resolve(null),
    ]);
    if (h.status === "fulfilled") { setHero(h.value); setHeroErr(null); } else setHeroErr(String(h.reason));
    if (s.status === "fulfilled") { if (s.value) { setSt(s.value); setAuthErr(null); } }
    else authFail(s.reason);
  }, [authFail]);
  const refreshRef = useRef(refresh); refreshRef.current = refresh;

  useEffect(() => {
    if (!ready) return;
    refreshRef.current();
    if (!visible) return;
    const t = setInterval(() => refreshRef.current(), POLL_MS);
    return () => clearInterval(t);
  }, [ready, visible, token, viewSession]);

  // New finds: the first state of a session only seeds the list silently (page reload mid-run).
  const seen = useRef<{ session: string | null; ids: Set<string> }>({ session: null, ids: new Set() });
  useEffect(() => {
    if (!st) return;
    if (seen.current.session !== st.session) { seen.current = { session: st.session, ids: new Set(st.finds.map((f) => f.id)) }; setNews([]); return; }
    const fresh = st.finds.filter((f) => !seen.current.ids.has(f.id));
    if (!fresh.length) return;
    fresh.forEach((f) => seen.current.ids.add(f.id));
    setNews((n) => [...fresh, ...n]);
    try { navigator.vibrate?.([200, 100, 200]); } catch { /* nicht unterstützt */ }
    play("find");
  }, [st]);

  // Own position: only while the page is visible and an expedition runs; points stay in memory until sent.
  const buf = useRef<Fix[]>([]);
  useEffect(() => {
    if (!running) { setGeo("aus"); return; }
    if (!visible) return;
    if (typeof navigator === "undefined" || !navigator.geolocation) { setGeo("nicht_unterstuetzt"); return; }
    if (!window.isSecureContext) { setGeo("unsicher"); return; }
    setGeo((g) => (g === "aktiv" ? g : "wartet"));
    const id = navigator.geolocation.watchPosition(
      (p) => {
        const fix = { ts: p.timestamp, lat: p.coords.latitude, lon: p.coords.longitude, acc: p.coords.accuracy };
        const last = buf.current[buf.current.length - 1];
        if (!last || last.ts !== fix.ts) buf.current.push(fix);
        if (buf.current.length > 2000) buf.current.splice(0, buf.current.length - 2000);
        setGeo("aktiv"); setAcc(Math.round(fix.acc)); setLastFix(Date.now());
      },
      (e) => setGeo(e.code === 1 ? "verweigert" : e.code === 3 ? "wartet" : "fehler"),
      { enableHighAccuracy: true, maximumAge: 0, timeout: 30_000 },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [running, visible]);

  const flushing = useRef(false);
  const flush = useCallback(async () => {
    const tk = tokenRef.current, sid = store.get(K_SESSION);
    if (!tk || !sid || !buf.current.length || flushing.current) return;
    flushing.current = true;
    const batch = buf.current.splice(0, 2000);
    try {
      const r = await api.heroLivePost(tk, sid, batch);
      setSent((n) => n + r.accepted); setPostErr(null); setAuthErr(null);
      await refreshRef.current();
    } catch (e) {
      buf.current.unshift(...batch);  // keep for the next try
      if (!authFail(e)) setPostErr("Senden fehlgeschlagen – neuer Versuch in 15 s.");
    } finally { flushing.current = false; }
  }, [authFail]);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => void flush(), FLUSH_MS);
    return () => clearInterval(t);
  }, [running, flush]);
  useEffect(() => { if (!visible) void flush(); }, [visible, flush]);

  // Screen wake lock (released by the browser whenever the page is hidden, so request again when visible).
  const wakeSupported = typeof navigator !== "undefined" && "wakeLock" in navigator;
  useEffect(() => {
    if (!wake || !visible || !wakeSupported) { setWakeMsg(null); return; }
    let lock: WakeLockSentinel | null = null, dead = false;
    navigator.wakeLock.request("screen")
      .then((l) => { if (dead) void l.release(); else { lock = l; setWakeMsg("Bildschirm bleibt an."); } })
      .catch(() => setWakeMsg("Der Browser erlaubt das gerade nicht."));
    return () => { dead = true; void lock?.release().catch(() => {}); };
  }, [wake, visible, wakeSupported]);

  // Compass: Android delivers absolute alpha, iOS a ready-made webkitCompassHeading.
  const compassOn = compass === "warte" || compass === "aktiv";
  useEffect(() => {
    if (!compassOn) return;
    let got = false, last = -99;
    const on = (e: Event) => {
      const o = e as DeviceOrientationEvent & { webkitCompassHeading?: number };
      let h: number | null = null;
      if (typeof o.webkitCompassHeading === "number") h = o.webkitCompassHeading;
      else if ((e.type === "deviceorientationabsolute" || o.absolute) && o.alpha != null) h = (360 - o.alpha) % 360;
      if (h == null) return;
      got = true;
      if (Math.abs(((h - last + 540) % 360) - 180) > 2) { last = h; setHeading(Math.round(h)); }
      setCompass("aktiv");
    };
    window.addEventListener("deviceorientationabsolute", on);
    window.addEventListener("deviceorientation", on);
    const t = setTimeout(() => { if (!got) { setCompass("keiner"); setHeading(null); } }, 3000);
    return () => { window.removeEventListener("deviceorientationabsolute", on); window.removeEventListener("deviceorientation", on); clearTimeout(t); };
  }, [compassOn]);
  const enableCompass = async () => {
    const D = window.DeviceOrientationEvent as unknown as { requestPermission?: () => Promise<string> } | undefined;
    if (!D) { setCompass("keiner"); return; }
    try {
      if (typeof D.requestPermission === "function" && (await D.requestPermission()) !== "granted") { setCompass("verweigert"); return; }
    } catch { setCompass("verweigert"); return; }
    setCompass("warte");
  };

  const saveToken = () => {
    const t = tokenInput.trim();
    if (!t) return;
    store.set(K_TOKEN, t); setToken(t); setTokenInput(""); setAuthErr(null);
  };
  const forgetToken = () => { store.set(K_TOKEN, null); setToken(null); setSt(null); };
  const start = () => {
    unlockAudio();
    const sid = `hh-${Date.now().toString(36)}`;
    store.set(K_SESSION, sid); store.set(K_RUNNING, "1");
    buf.current = []; seen.current = { session: null, ids: new Set() };
    setMySession(sid); setRunning(true); setSent(0); setNews([]); setSt(null); setPostErr(null); setAcc(null); setLastFix(null);
  };
  const stop = async () => {
    await flush();
    store.set(K_RUNNING, "0"); setRunning(false);
  };
  const setTarget = useCallback(async (kind: "poi" | "dungeon", id: string) => {
    if (!tokenRef.current || !sessionRef.current) return;
    try { await api.heroLiveTarget(tokenRef.current, sessionRef.current, { kind, id }); await refreshRef.current(); }
    catch (e) { if (!authFail(e)) setPostErr("Ziel konnte nicht gesetzt werden."); }
  }, [authFail]);
  const clearTarget = async () => {
    if (!token || !viewSession) return;
    try { await api.heroLiveTarget(token, viewSession, null); await refresh(); } catch (e) { authFail(e); }
  };

  const ownRoute = hero?.world.available ? hero.world.live?.routes.find((r) => r.session === viewSession) : undefined;
  const pos = ownRoute?.points.length ? ownRoute.points[ownRoute.points.length - 1] : null;
  const target = st?.target ?? null;
  const live = useMemo<LiveMap | undefined>(() => ({
    own: viewSession ?? null, pos: pos ? [pos[0], pos[1]] : null, heading,
    target: target ? { kind: target.kind, id: target.id, chosen: target.chosen } : null,
    setTarget: token && viewSession ? setTarget : undefined,
  }), [viewSession, pos?.[0], pos?.[1], heading, target?.kind, target?.id, target?.chosen, token, setTarget]);  // eslint-disable-line react-hooks/exhaustive-deps

  const arrowDeg = target?.bearing_deg != null ? target.bearing_deg - (heading ?? 0) : null;
  const lastPoint = st?.last_ts ? now - st.last_ts : null;
  const geoText: Record<Geo, string> = {
    aus: "Ortung aus", wartet: "Warte auf GPS-Signal …", aktiv: `Ortung aktiv${acc != null ? ` · ±${acc} m` : ""}`,
    verweigert: "Ortung vom Browser abgelehnt – in den Seiteneinstellungen erlauben.",
    fehler: "Position derzeit nicht verfügbar.",
    unsicher: "Ortung braucht eine gesicherte Verbindung (HTTPS oder localhost).",
    nicht_unterstuetzt: "Dieser Browser kann nicht orten.",
  };

  return (
    <div className={`wow ${cinzel.variable} space-y-3 p-3 sm:p-4`}>
      <div className="flex items-baseline justify-between gap-2">
        <h1 className="font-display text-xl font-bold" style={{ color: "#ffd100" }}>Expedition</h1>
        <Link href="/heldenreise#abenteuer" className="text-[12px] text-muted hover:text-[#ffd100]">← Heldenreise</Link>
      </div>

      {news.length > 0 && (
        <div role="status" data-testid="news" className="rounded-md border border-[#6fd3e8] bg-[#0c2a30] p-2.5 text-[13px] text-[#d8f4fa]">
          <div className="flex items-start justify-between gap-2">
            <div>
              {news.slice(0, 3).map((f) => <p key={f.id}><b>{FIND_LABEL[f.kind]}:</b> {f.name}{f.xp ? ` · ${f.xp} EP` : ""} <span className="text-[11px] opacity-70">(vorläufig)</span></p>)}
              {news.length > 3 && <p className="text-[11px] opacity-70">und {news.length - 3} weitere</p>}
            </div>
            <button type="button" aria-label="Hinweis schließen" onClick={() => setNews([])} className="text-lg leading-none opacity-70 hover:opacity-100">×</button>
          </div>
        </div>
      )}

      {!ready ? <Loading /> : !token ? (
        <Card>
          <CardTitle title="Live-Token" sub="Einmalig auf diesem Gerät hinterlegen (steht in server/.env als HERO_LIVE_TOKEN). Er wird nur hier im Browser gespeichert." />
          <form onSubmit={(e) => { e.preventDefault(); saveToken(); }} className="flex gap-2">
            <input type="password" autoComplete="off" value={tokenInput} onChange={(e) => setTokenInput(e.target.value)} aria-label="Live-Token"
                   className="min-w-0 flex-1 rounded border border-[#4b3a22] bg-black/40 px-2 py-2 text-base text-[#efe3c8]" />
            <button type="submit" className="rounded border border-[#5a4424] bg-[#2a2013] px-3 py-2 text-sm text-[#ffd100]">Speichern</button>
          </form>
        </Card>
      ) : (
        <>
          {authErr && <p role="alert" className="rounded border border-bad/50 bg-black/40 p-2 text-[13px] text-bad">{authErr} <button type="button" className="underline" onClick={forgetToken}>Token ändern</button></p>}

          <Card>
            <button type="button" onClick={running ? stop : start} data-testid="startstop"
                    className={`w-full rounded-md border px-4 py-3 font-display text-base font-bold ${running ? "border-[#7a2a22] bg-[#3a1511] text-[#ff8a7a]" : "border-[#8a6a1e] bg-[#3a2c0c] text-[#ffd100]"}`}>
              {running ? "Expedition beenden" : "Expedition starten"}
            </button>
            <div className="mt-2 space-y-0.5 text-[12px] text-muted" data-testid="status">
              <p>{running ? geoText[geo] : "Keine eigene Ortung."}{running && <> · gesendet: {sent}</>}</p>
              {running && !visible && <p>Seite im Hintergrund – Ortung pausiert.</p>}
              {postErr && <p className="text-bad">{postErr}</p>}
              <p>{st?.active
                ? <>Letzter Punkt vor {lastPoint != null ? ago(lastPoint) : "?"} · {st.points} Punkte · {String(st.revealed.km2).replace(".", ",")} km² neu aufgedeckt (vorläufig)</>
                : viewSession ? "Auf dem Server liegt für diese Session noch kein Punkt." : "Noch keine Session."}</p>
              {!running && sessions.length > 0 && (
                <label className="flex items-center gap-2">Session anzeigen:
                  <select value={viewSession ?? ""} onChange={(e) => setWatchPick(e.target.value)} className="rounded border border-[#4b3a22] bg-black/40 px-1 py-1 text-[#efe3c8]">
                    {sessions.map((s) => <option key={s} value={s}>{s === mySession ? `${s} (Handy)` : s}</option>)}
                  </select>
                </label>
              )}
            </div>
          </Card>

          <Card>
            {target ? (
              <div className="flex items-center gap-3" data-testid="target">
                {arrowDeg != null ? <Arrow deg={arrowDeg} /> : <div className="grid h-36 w-36 shrink-0 place-items-center rounded-full border border-[#5a4424] text-center text-[12px] text-muted">keine Position</div>}
                <div className="min-w-0 flex-1">
                  <p className="text-[11px] uppercase tracking-wide text-muted">{target.chosen ? "Ziel" : "Nächstes Ziel"} · {target.label} · Stufe {target.level}</p>
                  <p className="wow-title truncate text-[15px] text-[#ffd100]">{target.name}</p>
                  <p className="font-display text-3xl font-bold tabular-nums" data-testid="distance">{target.distance_m != null ? dist(target.distance_m) : "–"}</p>
                  <p className="text-[11px] text-muted">{heading != null ? "Pfeil zeigt zum Ziel (Kompass)" : "Pfeil relativ zu Norden (oben)"}</p>
                  {target.chosen && <button type="button" onClick={clearTarget} className="mt-1 text-[11px] text-muted underline hover:text-[#ffd100]">Ziel entfernen</button>}
                </div>
              </div>
            ) : <p className="text-[13px] text-muted">Noch kein Ziel. Wähle in der Karte einen Ort oder ein Verlies und tippe „Als Ziel setzen“{viewSession ? "" : " (vorher Expedition starten)"}.</p>}
            {st?.dungeon && (
              <div className="mt-3 border-t border-[#3a2d1a] pt-2" data-testid="dungeon">
                <p className="text-[12px]"><b style={{ color: "#c08cff" }}>{st.dungeon.name}</b>{st.dungeon.provisional_cleared ? " · vorläufig bezwungen" : st.dungeon.cleared ? " · bezwungen" : ""}</p>
                <ul className="mt-1 space-y-1">
                  {st.dungeon.segments.map((s, i) => (
                    <li key={i} className="text-[11px]">
                      <div className="flex justify-between gap-2"><span style={{ color: s.cleared || s.provisional ? "#40c040" : undefined }}>{s.cleared || s.provisional ? "✔ " : ""}{st.dungeon!.discovered || st.dungeon!.provisional ? s.boss : "???"}</span><span className="tabular-nums text-muted">{Math.round(s.coverage * 100)} %</span></div>
                      <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-[#0a0807]"><div className="h-full rounded-full" style={{ width: `${Math.min(100, s.coverage / 0.8 * 100)}%`, background: s.cleared || s.provisional ? "#40c040" : "#c08cff" }} /></div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>

          {heroErr ? <ApiError error={heroErr} /> : !hero ? <Loading /> : <HeroWorld data={hero} live={live} compact />}

          {st && st.finds.length > 0 && (
            <Card>
              <CardTitle title="Funde dieser Expedition" sub="Vorläufig – endgültig zählt es nach der Synchronisation des Laufs." />
              <ul className="space-y-0.5 text-[13px]" data-testid="finds">
                {st.finds.map((f) => <li key={f.id}><span className="text-muted">{FIND_LABEL[f.kind]}:</span> {f.name}{f.xp ? ` · ${f.xp} EP` : ""}</li>)}
              </ul>
            </Card>
          )}

          <Card>
            <CardTitle title="Einstellungen" />
            <div className="space-y-2 text-[13px]">
              <label className="flex items-center justify-between gap-3">
                <span>Bildschirm anlassen{!wakeSupported && <span className="text-[11px] text-muted"> (vom Browser nicht unterstützt)</span>}</span>
                <input type="checkbox" className="h-5 w-5" checked={wake} disabled={!wakeSupported}
                       onChange={(e) => { setWake(e.target.checked); store.set(K_WAKE, e.target.checked ? "1" : "0"); }} />
              </label>
              {wake && wakeMsg && <p className="text-[11px] text-muted">{wakeMsg}</p>}
              <label className="flex items-center justify-between gap-3">
                <span>Klänge bei Funden</span>
                <input type="checkbox" className="h-5 w-5" checked={sound} onChange={(e) => { setSound(e.target.checked); setSoundOn(e.target.checked); unlockAudio(); }} />
              </label>
              <div className="flex items-center justify-between gap-3">
                <span>Kompass{compass === "keiner" && <span className="text-[11px] text-muted"> (kein Signal – Pfeil bleibt relativ zu Norden)</span>}{compass === "verweigert" && <span className="text-[11px] text-muted"> (abgelehnt)</span>}</span>
                {compassOn ? <button type="button" onClick={() => { setCompass("aus"); setHeading(null); }} className="rounded border border-[#4b3a22] px-2 py-1 text-[12px]">aus ({heading != null ? `${heading}°` : "…"})</button>
                  : <button type="button" onClick={enableCompass} className="rounded border border-[#4b3a22] px-2 py-1 text-[12px] text-[#ffd100]">aktivieren</button>}
              </div>
              <div className="flex items-center justify-between gap-3">
                <span>Live-Token</span>
                <button type="button" onClick={forgetToken} className="rounded border border-[#4b3a22] px-2 py-1 text-[12px]">auf diesem Gerät löschen</button>
              </div>
            </div>
            <p className="mt-2 text-[10px] text-muted">Das Handy ortet nur, solange diese Seite sichtbar ist. Die Uhr-App liefert die durchgehende Spur; ohne eigene Ortung zeigt die Seite den letzten Stand vom Server. Positionen werden nur im Arbeitsspeicher gepuffert und an den Server gesendet, nicht im Browser gespeichert.</p>
          </Card>
        </>
      )}
    </div>
  );
}
