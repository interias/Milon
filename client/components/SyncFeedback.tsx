"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { FEEDBACK_LIFETIME, readSyncFeedback, SYNC_KINDS, syncFeedbackText, type SyncFeedback as Feedback } from "@/lib/sync-feedback";
import styles from "./SyncFeedback.module.css";

export function useSyncFeedback() {
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  useEffect(() => {
    setFeedback(readSyncFeedback());
    const update = (event: Event) => setFeedback((event as CustomEvent<Feedback | null>).detail);
    window.addEventListener("milon:sync-feedback", update);
    return () => window.removeEventListener("milon:sync-feedback", update);
  }, []);
  useEffect(() => {
    if (!feedback) return;
    const timer = setTimeout(() => setFeedback(null), Math.max(0, feedback.createdAt + FEEDBACK_LIFETIME - Date.now()));
    return () => clearTimeout(timer);
  }, [feedback]);
  return feedback;
}

export function SyncFeedbackNotice() {
  const feedback = useSyncFeedback(), [dismissed, setDismissed] = useState(0);
  const labels = { runs: "Lauf öffnen", nights: "Nacht öffnen", workouts: "Kraft", weights: "Körper", nutrition: "Ernährung" };
  if (!feedback || feedback.createdAt === dismissed || !SYNC_KINDS.some(kind => feedback[kind].length)) return null;
  return <aside className={styles.notice} aria-label="Neu synchronisierte Daten">
    <button type="button" className={styles.close} aria-label="Synchronisierungshinweis schließen" onClick={() => setDismissed(feedback.createdAt)}>×</button>
    <p role="status">{syncFeedbackText(feedback)}</p>
    <div>{SYNC_KINDS.filter(kind => feedback[kind].length).map(kind => <Link key={kind} href={feedback[kind][0].href} onClick={() => setDismissed(feedback.createdAt)}>{labels[kind]} ↗</Link>)}</div>
  </aside>;
}
