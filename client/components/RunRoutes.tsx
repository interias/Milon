"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Card } from "@/components/ui";
import { de, de0, dur } from "@/lib/format";
import { projectRunRoute, routeDate, runRoutesApi, type RunRouteDetail, type RunRouteList } from "@/lib/run-routes";
import styles from "./RunRoutes.module.css";

const message = (error: unknown) => error instanceof Error ? error.message : "Die Anfrage ist fehlgeschlagen. Bitte erneut versuchen.";

function RoutePreview({ route }: { route: RunRouteDetail }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [viewport, setViewport] = useState({ width: 640, height: 260 });
  const geometry = useMemo(() => projectRunRoute(route.segments, viewport.width, viewport.height, 42), [route.segments, viewport]);
  const titleId = useId();
  const hasExtent = !!geometry?.hasExtent;
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const observer = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      if (width > 60 && height > 60) setViewport(previous => previous.width === width && previous.height === height ? previous : { width, height });
    });
    observer.observe(svg);
    return () => observer.disconnect();
  }, [route.activity_id, hasExtent]);
  if (!geometry) return <p className={styles.emptyPreview}>Für diesen Lauf ist kein GPS-Streckenverlauf verfügbar.</p>;
  if (!geometry.hasExtent) return <p className={styles.emptyPreview}>{geometry.pointCount === 1 ? "Nur ein GPS-Punkt vorhanden; kein Streckenverlauf." : "Die GPS-Punkte enthalten keinen darstellbaren Streckenverlauf."}</p>;
  const scaleLabel = geometry.scaleMeters >= 1000 ? `${de(geometry.scaleMeters / 1000, 1)} km` : `${de(geometry.scaleMeters, geometry.scaleMeters < 1 ? 1 : 0)} m`;
  return <figure className={styles.figure}>
    <svg ref={svgRef} viewBox={`0 0 ${viewport.width} ${viewport.height}`} preserveAspectRatio="xMidYMid meet" role="img" aria-labelledby={titleId}>
      <title id={titleId}>GPS-Streckenverlauf: {route.title || "Lauf"}. Norden oben. Start als Punkt, Ende als Ring.</title>
      {[.25, .5, .75].map(fraction => <line key={`h${fraction}`} x1="18" x2={viewport.width - 18} y1={viewport.height * fraction} y2={viewport.height * fraction} stroke="#e9efed" strokeWidth="1" />)}
      {[.2, .4, .6, .8].map(fraction => <line key={`v${fraction}`} x1={viewport.width * fraction} x2={viewport.width * fraction} y1="18" y2={viewport.height - 18} stroke="#e9efed" strokeWidth="1" />)}
      {geometry.segments.map((segment, index) => segment.length === 1
        ? <circle key={index} cx={segment[0].x} cy={segment[0].y} r="2.5" fill="#0a6e66" />
        : <path key={index} d={segment.map((point, i) => `${i ? "L" : "M"}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ")} fill="none" stroke="#0a6e66" strokeWidth="2.5" vectorEffect="non-scaling-stroke" strokeLinecap="round" strokeLinejoin="round" />)}
      <circle cx={geometry.start.x} cy={geometry.start.y} r="4.5" fill="#0a6e66" stroke="white" strokeWidth="1.5"><title>Start</title></circle>
      <circle cx={geometry.end.x} cy={geometry.end.y} r="8" fill="none" stroke="#14201f" strokeWidth="2"><title>Ende</title></circle>
      <g className={styles.north} aria-hidden="true"><text x={viewport.width - 27} y="21" textAnchor="middle">N</text><path d={`M${viewport.width - 27} 45V28m-5 7 5-7 5 7`} fill="none" stroke="currentColor" strokeWidth="1.4" /></g>
      <g className={styles.scale} aria-hidden="true"><path d={`M22 ${viewport.height - 34}v5h${geometry.scalePixels}v-5`} fill="none" stroke="currentColor" strokeWidth="1.3" /><text x={22 + geometry.scalePixels / 2} y={viewport.height - 13} textAnchor="middle">{scaleLabel}</text></g>
    </svg>
    <figcaption><span>GPS-Streckenverlauf</span><span className={styles.legend}><span><i className={styles.startMarker} />Start</span><span><i className={styles.endMarker} />Ende</span></span></figcaption>
    {geometry.segments.length > 1 && <p className={styles.segmentNote}>Aufzeichnung unterbrochen · Abschnitte bleiben getrennt.</p>}
  </figure>;
}

export function RunRoutes() {
  const [list, setList] = useState<RunRouteList | null>(null), [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<RunRouteDetail | null>(null), [detailRevision, setDetailRevision] = useState(0);
  const [loading, setLoading] = useState(true), [loadingMore, setLoadingMore] = useState(false), [detailLoading, setDetailLoading] = useState(false);
  const [syncing, setSyncing] = useState(false), [nextOffset, setNextOffset] = useState(0);
  const [listError, setListError] = useState(""), [detailError, setDetailError] = useState(""), [syncError, setSyncError] = useState(""), [feedback, setFeedback] = useState("");
  const listRequest = useRef<{ revision: number; controller: AbortController | null }>({ revision: 0, controller: null });
  const detailRequest = useRef(0), syncController = useRef<AbortController | null>(null);
  const selectId = useId();

  const loadList = useCallback(async (offset = 0) => {
    listRequest.current.controller?.abort();
    const controller = new AbortController(), revision = ++listRequest.current.revision;
    listRequest.current.controller = controller;
    if (offset) setLoadingMore(true); else { setLoading(true); setLoadingMore(false); }
    setListError("");
    try {
      const result = await runRoutesApi.list(offset, controller.signal);
      if (controller.signal.aborted || revision !== listRequest.current.revision) return false;
      setList(previous => offset && previous ? { ...result, items: Array.from(new Map([...previous.items, ...result.items].map(item => [item.activity_id, item])).values()) } : result);
      setNextOffset(result.items.length ? offset + result.items.length : result.total);
      if (!offset) {
        setSelectedId(previous => result.items.some(item => item.activity_id === previous) ? previous : result.items[0]?.activity_id || "");
        setDetailRevision(previous => previous + 1);
      }
      return true;
    } catch (error) {
      if (!controller.signal.aborted && revision === listRequest.current.revision) setListError(message(error));
      return false;
    } finally {
      if (!controller.signal.aborted && revision === listRequest.current.revision) { setLoading(false); setLoadingMore(false); }
    }
  }, []);

  useEffect(() => {
    void loadList();
    const refresh = (event: Event) => {
      if ((event as CustomEvent<{ source?: string }>).detail?.source !== "garmin-routes") void loadList();
    };
    window.addEventListener("milon:data-refresh", refresh);
    return () => {
      listRequest.current.controller?.abort(); listRequest.current.revision++;
      syncController.current?.abort();
      window.removeEventListener("milon:data-refresh", refresh);
    };
  }, [loadList]);

  useEffect(() => {
    const controller = new AbortController(), revision = ++detailRequest.current;
    setDetail(null); setDetailError("");
    if (!selectedId) { setDetailLoading(false); return () => controller.abort(); }
    setDetailLoading(true);
    runRoutesApi.detail(selectedId, controller.signal).then(result => {
      if (!controller.signal.aborted && revision === detailRequest.current) setDetail(result);
    }).catch(error => {
      if (!controller.signal.aborted && revision === detailRequest.current) setDetailError(message(error));
    }).finally(() => {
      if (!controller.signal.aborted && revision === detailRequest.current) setDetailLoading(false);
    });
    return () => controller.abort();
  }, [selectedId, detailRevision]);

  async function synchronize() {
    if (syncController.current) return;
    const controller = new AbortController(); syncController.current = controller;
    setSyncing(true); setSyncError(""); setFeedback("");
    try {
      const result = await runRoutesApi.sync(controller.signal);
      if (controller.signal.aborted) return;
      if (result.error) throw new Error(result.error);
      const loaded = await loadList();
      if (controller.signal.aborted) return;
      setFeedback(result.mode === "not_configured" ? "Garmin ist noch nicht verbunden." : loaded ? "Garmin-Strecken aktualisiert." : "Garmin importiert. Bitte die Streckenliste erneut laden.");
      window.dispatchEvent(new CustomEvent("milon:data-refresh", { detail: { source: "garmin-routes" } }));
    } catch (error) {
      if (!controller.signal.aborted) {
        setSyncError(message(error));
        // A failed import may still have saved some activities.
        await loadList();
      }
    }
    finally { if (!controller.signal.aborted) { setSyncing(false); syncController.current = null; } }
  }

  const selected = list?.items.find(item => item.activity_id === selectedId);
  const route = detail?.activity_id === selectedId ? detail : null;
  const current = route || selected;
  const busy = loading || loadingMore || syncing;
  const previousSyncFailed = list?.sync?.status === "error";

  return <Card className={styles.card}>
    <div className={styles.header}><div><h3 className="text-sm font-semibold">Gelaufene Strecken</h3><p className="text-[11px] text-muted">Deine Garmin-Läufe mit GPS</p></div><button type="button" className={styles.refreshButton} disabled={busy} onClick={() => void synchronize()}>{syncing ? "Garmin wird aktualisiert …" : "Garmin aktualisieren"}</button></div>
    {syncError && <p className={styles.error} role="alert">{syncError}</p>}
    {feedback && <p className={styles.feedback} role="status">{feedback}</p>}
    {listError && <div className={styles.errorRow} role="alert"><span>{listError}</span><button type="button" disabled={busy} onClick={() => void loadList()}>Erneut laden</button></div>}
    {!list && loading ? <p className={styles.loading} role="status">Strecken werden geladen …</p> : list && !list.items.length ? <div className={styles.empty}><p>Noch keine Garmin-Strecken importiert.</p><span>{list.configured === false ? "Garmin Connect ist noch nicht für den Import verbunden." : "Aktualisiere Garmin, um aufgezeichnete Läufe zu übernehmen."}</span></div> : list && <>
      <div className={styles.selection}><label htmlFor={selectId} className="sr-only">Lauf auswählen</label><select id={selectId} value={selectedId} disabled={loading || syncing} onChange={event => setSelectedId(event.target.value)}>{list.items.map(item => <option key={item.activity_id} value={item.activity_id}>{routeDate(item.started_at)} · {item.title || "Lauf"}</option>)}</select>{nextOffset < list.total && <button type="button" className={styles.olderButton} disabled={busy} onClick={() => void loadList(nextOffset)}>{loadingMore ? "Lädt …" : "Ältere laden"}</button>}</div>
      {current && <div className={styles.metrics}>
        {current.distance_km != null && <span><strong>{de(current.distance_km, 2)}</strong> km</span>}
        {current.duration_seconds != null && <span><strong>{dur(current.duration_seconds)}</strong> <small>Dauer</small></span>}
        {current.elevation_gain_m != null && <span><strong>↗ {de0(current.elevation_gain_m)}</strong> m <small>Anstieg</small></span>}
      </div>}
      {detailLoading ? <p className={styles.emptyPreview} role="status">GPS-Verlauf wird geladen …</p> : detailError ? <div className={styles.emptyPreview}><p className={styles.error} role="alert">{detailError}</p><button type="button" className={styles.retryButton} onClick={() => setDetailRevision(value => value + 1)}>Verlauf erneut laden</button></div> : route ? <RoutePreview route={route} /> : null}
      {current?.matched_external_id && <p className={styles.matchNote}>Mit deinem vorhandenen Lauf verknüpft.</p>}
      {nextOffset < list.total && <p className={styles.count}>{list.items.length} von {list.total} Läufen geladen</p>}
    </>}
    {list?.sync?.last_sync && <p className={`${styles.syncNote} ${previousSyncFailed ? styles.failedSync : ""}`}>{previousSyncFailed ? "Letzter Import fehlgeschlagen" : "Letzter Import"} · {routeDate(list.sync.last_sync)}{previousSyncFailed && <span>Bitte Garmin erneut aktualisieren.</span>}</p>}
  </Card>;
}
