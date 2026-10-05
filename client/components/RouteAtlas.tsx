"use client";
import { useState } from "react";
import Link from "next/link";
import { de, de0 } from "@/lib/format";
import { paceLabel } from "@/lib/garmin";
import { routeDate } from "@/lib/run-routes";
import type { RouteAtlasData, RouteFamily } from "@/lib/route-atlas";
import { RouteSegments } from "./RouteSegments";
import { useSyncFeedback } from "./SyncFeedback";
import styles from "./RunRoutes.module.css";

function Contour({ family }: { family: RouteFamily }) {
  if (!family.contour.length) return <span className={styles.missingContour}>GPS-Verlauf fehlt</span>;
  return <svg viewBox="0 0 200 200" aria-hidden="true" className={styles.contour}>
    {family.contour.map((segment, index) => <path key={index} d={segment.map(([x, y], position) => `${position ? "L" : "M"}${x},${y}`).join(" ")} fill="none" stroke="currentColor" strokeWidth="2.8" strokeLinejoin="round" strokeLinecap="round" />)}
    {family.contour[0]?.[0] && <circle cx={family.contour[0][0][0]} cy={family.contour[0][0][1]} r="4" fill="currentColor" stroke="white" strokeWidth="1.5" />}
  </svg>;
}
export function RouteAtlas({ data, selectedId, onSelect }: { data: RouteAtlasData; selectedId: string; onSelect: (id: string) => void }) {
  const feedback = useSyncFeedback();
  const [visibleGroups, setVisibleGroups] = useState(8), [expanded, setExpanded] = useState(false);
  const selected = data.groups.find(group => group.members.some(member => member.activity_id === selectedId)) || data.groups[0];
  const groups = data.groups.slice(0, visibleGroups);
  if (selected && !groups.includes(selected)) groups.push(selected);
  const members = selected?.members || [];
  return <>
    <div className={styles.atlasSummary}><span>{data.groups.length} {data.groups.length === 1 ? "Strecke" : "Strecken"} · {data.total_runs} {data.total_runs === 1 ? "Lauf" : "Läufe"}</span><span>Ab {data.threshold_pct} % Überdeckung</span></div>
    <div className={styles.atlasBody}><div>
    <div className={styles.atlasGrid}>{groups.map((group, index) => <button key={group.anchor_id} type="button" className={`${styles.routeTile} ${selected?.anchor_id === group.anchor_id ? styles.selectedTile : ""}`} aria-pressed={selected?.anchor_id === group.anchor_id} onClick={() => { onSelect(group.latest.activity_id); setExpanded(false); }}>
      <div className={styles.tileTop}><span>{de(group.latest.distance_km, 1)} km</span><span>{group.count}×</span></div>
      <Contour family={group} />
      <strong className={styles.tileTitle}>{group.latest.title || `Runde ${index + 1}`}</strong><span className={styles.tileDate}>Zuletzt {routeDate(group.latest.started_at).split(" · ")[0]}</span>
    </button>)}</div>
    {visibleGroups < data.groups.length && <button type="button" className={styles.moreButton} onClick={() => setVisibleGroups(count => count + 8)}>Weitere Strecken ({data.groups.length - visibleGroups})</button>}
    </div>
    {selected && <div className={styles.family}>
      <div className={styles.familyHeader}><h4>Deine Wiederholungen</h4><span>{selected.count} {selected.count === 1 ? "Aufzeichnung" : "Aufzeichnungen"}</span></div>
      {(selected.changes.pace_seconds || selected.changes.avg_hr) && <div className={styles.changes}>{(["pace_seconds", "avg_hr"] as const).map(key => {
        const change = selected.changes[key];
        if (!change) return null;
        const pace = key === "pace_seconds";
        const format = (value: number) => pace ? paceLabel(value) : de0(value);
        return <div key={key}><span>{pace ? "Ø Pace" : "Ø Puls"} · erster → letzter</span><strong>{format(change.first)} <i>→</i> {format(change.last)} <small>{pace ? "/km" : "bpm"}</small></strong><span>{change.delta > 0 ? "+" : change.delta < 0 ? "−" : "±"}{pace ? paceLabel(Math.abs(change.delta)) : de0(Math.abs(change.delta))} {pace ? "/km" : "bpm"} · {routeDate(change.from).split(" · ")[0]}–{routeDate(change.to).split(" · ")[0]}</span></div>;
      })}</div>}
      <div className={styles.memberList}>{(expanded ? members : members.slice(0, 4)).map(member => <Link key={member.activity_id} href={`/laufen/${member.activity_id}`} className={`${member.activity_id === selectedId ? styles.activeMember : ""} ${feedback?.runs.some(run => run.href === `/laufen/${member.activity_id}`) ? "milon-new-data" : ""}`}>
        <span>{routeDate(member.started_at).split(" · ")[0]}{feedback?.runs.some(run => run.href === `/laufen/${member.activity_id}`) && <small className={styles.newLabel}>Neu</small>}</span><span>{de(member.distance_km, 2)} <small>km</small></span><span>{paceLabel(member.pace_seconds)} <small>/km</small></span><span>{de0(member.avg_hr)} <small>bpm</small></span><span aria-hidden="true">↗</span>
      </Link>)}</div>
      {members.length > 4 && <button className={styles.moreButton} type="button" onClick={() => setExpanded(value => !value)}>{expanded ? "Weniger anzeigen" : `Alle ${members.length} Läufe anzeigen`}</button>}
      {selected.count > 1 && <p className={styles.note}>Beschreibender Verlauf · Wetter und Trainingsziel können die Werte verändern.</p>}
      <RouteSegments activityId={members.some(member => member.activity_id === selectedId) ? selectedId : selected.latest.activity_id} />
    </div>}
    </div>
    <details className={styles.method}><summary>Wie werden Strecken gruppiert?</summary><p>{data.method}</p></details>
  </>;
}
