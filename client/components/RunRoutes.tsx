"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Card } from "@/components/ui";
import { RunWeeklyZones } from "@/components/RunIntensityZones";
import { RouteAtlas } from "@/components/RouteAtlas";
import { loadRouteAtlas, type RouteAtlasData } from "@/lib/route-atlas";
import { routeDate, runRoutesApi } from "@/lib/run-routes";
import { captureSyncInventory, finishManualSync } from "@/lib/sync-feedback";
import styles from "./RunRoutes.module.css";

const message = (error: unknown) => error instanceof Error ? error.message : "Die Anfrage ist fehlgeschlagen. Bitte erneut versuchen.";
export function RunRoutes() {
  const [data, setData] = useState<RouteAtlasData | null>(null), [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true), [syncing, setSyncing] = useState(false);
  const [error, setError] = useState(""), [syncError, setSyncError] = useState(""), [feedback, setFeedback] = useState("");
  const request = useRef<{ revision: number; controller: AbortController | null }>({ revision: 0, controller: null });
  const syncController = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    request.current.controller?.abort();
    const controller = new AbortController(), revision = ++request.current.revision;
    request.current.controller = controller;
    setLoading(true); setError("");
    try {
      const result = await loadRouteAtlas(controller.signal);
      if (controller.signal.aborted || revision !== request.current.revision) return false;
      setData(result);
      const requested = new URLSearchParams(window.location.search).get("lauf");
      const ids = new Set(result.groups.flatMap(group => group.members.map(member => member.activity_id)));
      setSelectedId(previous => ids.has(previous) ? previous : requested && ids.has(requested) ? requested : result.groups[0]?.latest.activity_id || "");
      return true;
    } catch (issue) {
      if (!controller.signal.aborted && revision === request.current.revision) setError(message(issue));
      return false;
    } finally {
      if (!controller.signal.aborted && revision === request.current.revision) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
    const refresh = (event: Event) => {
      if ((event as CustomEvent<{ source?: string }>).detail?.source !== "garmin-routes") void load();
    };
    window.addEventListener("milon:data-refresh", refresh);
    return () => { request.current.controller?.abort(); request.current.revision++; syncController.current?.abort(); window.removeEventListener("milon:data-refresh", refresh); };
  }, [load]);
  async function synchronize() {
    if (syncController.current) return;
    const controller = new AbortController(); syncController.current = controller;
    setSyncing(true); setSyncError(""); setFeedback("");
    const before = await captureSyncInventory();
    try {
      const result = await runRoutesApi.sync(controller.signal);
      if (controller.signal.aborted) return;
      if (result.error) throw new Error(result.error);
      const loaded = await load();
      if (controller.signal.aborted) return;
      const feedback = await finishManualSync(before, "garmin-routes");
      if (controller.signal.aborted) return;
      setFeedback(result.mode === "not_configured" ? "Garmin ist noch nicht verbunden." : loaded ? feedback : "Garmin importiert. Bitte den Atlas erneut laden.");
    } catch (issue) {
      if (!controller.signal.aborted) { setSyncError(message(issue)); await load(); await finishManualSync(before, "garmin-routes"); }
    } finally { if (!controller.signal.aborted) { setSyncing(false); syncController.current = null; } }
  }
  return <section id="strecken" className={styles.section}><Card className={styles.card}>
    <div className={styles.header}><div><h3>Dein Streckenatlas</h3><p>Deine Runden · lokal aus Garmin-GPS</p></div><button type="button" className={styles.refreshButton} disabled={loading || syncing} onClick={() => void synchronize()}>{syncing ? "Garmin wird aktualisiert …" : "Garmin aktualisieren"}</button></div>
    {syncError && <p className={styles.error} role="alert">{syncError}</p>}
    {feedback && <p className={styles.feedback} role="status">{feedback}</p>}
    {error && <div className={styles.errorRow} role="alert"><span>{error}</span><button type="button" disabled={loading || syncing} onClick={() => void load()}>Erneut laden</button></div>}
    {!data && loading ? <p className={styles.loading} role="status">Deine Strecken werden gruppiert …</p> : data && !data.groups.length ? <p className={styles.loading}>{data.configured === false ? "Verbinde Garmin Connect, um deine Strecken zu importieren." : "Noch keine GPS-Strecken importiert. Aktualisiere Garmin, um deine Läufe zu übernehmen."}</p> : data && <RouteAtlas data={data} selectedId={selectedId} onSelect={setSelectedId} />}
    <RunWeeklyZones />
    {data?.sync?.last_sync && <p className={styles.syncNote}>{data.sync.status === "error" ? "Letzter Import fehlgeschlagen · bitte erneut aktualisieren" : "Letzter Import"} · {routeDate(data.sync.last_sync)}</p>}
  </Card></section>;
}
