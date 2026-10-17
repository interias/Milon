"use client";

import { useEffect, useState } from "react";
import { api, LiveError, type Hero, type HeroKeystonePreview, type HeroLiveState } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";

const mmss = (s: number) => {
  const t = Math.max(0, Math.round(s));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), r = t % 60;
  return `${h ? `${h}:${String(m).padStart(2, "0")}` : m}:${String(r).padStart(2, "0")}`;
};
const dist = (m: number) => (m >= 1000 ? `${(Math.round(m / 100) / 10).toString().replace(".", ",")} km` : `${m} m`);

const EVENT_STATUS: Record<string, string> = {
  active: "läuft", reached: "erreicht (vorläufig)", missed: "verpasst", declined: "abgelehnt",
  confirmed: "bestätigt", rejected: "nicht bestätigt", expired: "abgelaufen",
};

// Stone card of the expedition page: activate a stone, show time left and (only once triggered) the live event.
export function ExpeditionStone({ token, session, hero, state, onChanged, onAuthError }: {
  token: string; session: string | null; hero: Hero | null; state: HeroLiveState | null;
  onChanged: () => Promise<void>; onAuthError: (e: unknown) => boolean;
}) {
  const dungeons = hero?.world.available ? hero.world.dungeons.filter((d) => d.discovered) : [];
  const [dungeon, setDungeon] = useState("");
  const [preview, setPreview] = useState<HeroKeystonePreview | null>(null);
  const [level, setLevel] = useState<number | null>(null);
  const [chosen, setChosen] = useState<string[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ks = state?.keystone ?? null;
  const ev = state?.event ?? null;

  // Countdown between polls: the server value is the base, the local clock fills the gap.
  const [base, setBase] = useState<{ rem: number; at: number } | null>(null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { setBase(ks && ks.remaining_s != null ? { rem: ks.remaining_s, at: Date.now() } : null); }, [ks?.id, ks?.remaining_s]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const remaining = ks ? (base ? Math.max(0, base.rem - (now - base.at) / 1000) : ks.time_limit_s) : null;

  useEffect(() => {
    setPreview(null); setLevel(null); setChosen([]);
    if (!dungeon) return;
    let dead = false;
    api.heroKeystonePreview(token, dungeon)
      .then((p) => { if (!dead) { setPreview(p); setLevel(p.suggested_level.level); } })
      .catch((e) => { if (!dead && !onAuthError(e)) setMsg("Vorschau nicht verfügbar."); });
    return () => { dead = true; };
  }, [dungeon, token]);  // eslint-disable-line react-hooks/exhaustive-deps

  const activate = async () => {
    if (!session || !preview || level == null) return;
    setBusy(true); setMsg(null);
    try { await api.heroKeystoneActivate(token, session, preview.dungeon, level, chosen); await onChanged(); }
    catch (e) { if (!onAuthError(e)) setMsg(e instanceof LiveError ? "Der Stein ließ sich nicht aktivieren." : "Aktivieren fehlgeschlagen."); }
    finally { setBusy(false); }
  };
  const abort = async () => {
    if (!session) return;
    setBusy(true);
    try { await api.heroKeystoneAbort(token, session); await onChanged(); } catch (e) { onAuthError(e); } finally { setBusy(false); }
  };
  const decline = async () => {
    if (!session) return;
    try { await api.heroEventDecline(token, session); await onChanged(); } catch (e) { onAuthError(e); }
  };

  return (
    <>
      <Card>
        <CardTitle title="Stein" sub="Optional: ein Verlies mit Zeitlimit und Affixen laufen. Ohne Stein läuft alles wie bisher." />
        {ks ? (
          <div className="space-y-2" data-testid="stone-active">
            <p className="text-[13px]"><b style={{ color: "#ffd100" }}>{ks.name}</b> · Stein +{ks.level}{ks.provisional ? " (vorläufig)" : ""}</p>
            <p className="font-display text-3xl font-bold tabular-nums" data-testid="stone-remaining" data-seconds={remaining != null ? Math.round(remaining) : ""}>
              {remaining != null ? mmss(remaining) : "–"}
            </p>
            <p className="text-[11px] text-muted">{ks.clock_started ? "Restzeit" : "Zeitlimit – die Uhr startet mit dem ersten Punkt"} · {ks.segments_cleared}/{ks.segments_total} Abschnitte</p>
            {ks.affixes.length > 0 && (
              <ul className="text-[12px]" data-testid="stone-affixes">
                {ks.affixes.map((a) => <li key={a.key}><b>{a.name}</b> <span className="text-muted">– {a.desc}</span></li>)}
              </ul>
            )}
            <button type="button" onClick={abort} disabled={busy} data-testid="stone-abort" className="rounded border border-[#4b3a22] px-2 py-1 text-[12px] text-muted">Stein abbrechen</button>
          </div>
        ) : !session ? (
          <p className="text-[13px] text-muted" data-testid="stone-hint">Starte zuerst die Expedition, dann kannst du einen Stein aktivieren.</p>
        ) : dungeons.length === 0 ? (
          <p className="text-[13px] text-muted" data-testid="stone-hint">Noch kein Verlies entdeckt.</p>
        ) : (
          <form data-testid="stone-form" onSubmit={(e) => { e.preventDefault(); void activate(); }} className="space-y-2 text-[13px]">
            <label className="block">Verlies
              <select value={dungeon} onChange={(e) => setDungeon(e.target.value)} data-testid="stone-dungeon"
                      className="mt-0.5 w-full rounded border border-[#4b3a22] bg-black/40 px-2 py-2 text-base text-[#efe3c8]">
                <option value="">– wählen –</option>
                {dungeons.map((d) => <option key={d.key} value={d.key}>{d.name}</option>)}
              </select>
            </label>
            {preview && level != null && <>
              <label className="block">Stufe
                <select value={level} onChange={(e) => setLevel(Number(e.target.value))} data-testid="stone-level"
                        className="mt-0.5 w-full rounded border border-[#4b3a22] bg-black/40 px-2 py-2 text-base text-[#efe3c8]">
                  {preview.levels.map((l) => <option key={l} value={l}>+{l}{l === preview.suggested_level.level ? " (Vorschlag)" : ""} · {mmss(preview.time_limits[String(l)] ?? 0)}</option>)}
                </select>
              </label>
              <p className="text-[11px] text-muted">{preview.suggested_level.reason}</p>
              <fieldset data-testid="stone-affixes-pick" className="space-y-1">
                <legend className="text-[12px] text-muted">Affixe (optional)</legend>
                <p className="text-[12px]"><b>{preview.week_affix.name}</b> <span className="text-muted">– Wochen-Affix: {preview.week_affix.desc}</span></p>
                {preview.affixes.map((a) => (
                  <label key={a.key} className="flex items-start gap-2">
                    <input type="checkbox" className="mt-0.5 h-5 w-5" checked={chosen.includes(a.key)}
                           onChange={(e) => setChosen((c) => (e.target.checked ? [...c, a.key] : c.filter((k) => k !== a.key)))} />
                    <span><b>{a.name}</b> <span className="text-muted">– {a.desc}</span></span>
                  </label>
                ))}
              </fieldset>
              <button type="submit" disabled={busy} data-testid="stone-activate"
                      className="w-full rounded-md border border-[#8a6a1e] bg-[#3a2c0c] px-4 py-3 font-display text-base font-bold text-[#ffd100]">Stein aktivieren</button>
            </>}
            {msg && <p role="alert" className="text-[12px] text-bad">{msg}</p>}
          </form>
        )}
      </Card>

      {ev && (
        <Card>
          <div data-testid="event-box" data-status={ev.status} className="space-y-1">
            <p className="text-[11px] uppercase tracking-wide text-muted">Ereignis · {EVENT_STATUS[ev.status] ?? ev.status}</p>
            <p className="wow-title text-[15px] text-[#ffd100]">{ev.name}</p>
            <p className="text-[13px]">{ev.text}</p>
            {ev.status === "active" && <p className="text-[13px] tabular-nums" data-testid="event-distance">
              {ev.distance_m != null ? dist(ev.distance_m) : "–"}{ev.remaining_s != null ? ` · noch ${mmss(ev.remaining_s)}` : ""}
              {ev.progress != null ? ` · ${Math.round(ev.progress * 100)} %` : ""}
            </p>}
            {ev.reward && <p className="text-[11px] text-muted">Belohnung: {ev.reward.xp} EP{ev.reward.loot ? " und Beute" : ""}{ev.provisional ? " (vorläufig)" : ""}</p>}
            {ev.status === "active" && <button type="button" onClick={decline} data-testid="event-decline" className="rounded border border-[#4b3a22] px-2 py-1 text-[12px] text-muted">Ablehnen</button>}
          </div>
        </Card>
      )}
    </>
  );
}
