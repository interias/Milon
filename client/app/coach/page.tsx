"use client";

import { useEffect, useState } from "react";
import { api, type Report, type CoachStats } from "@/lib/api";
import { Card, CardTitle, PageTitle, Loading, ApiError } from "@/components/ui";
import { Markdown } from "@/components/Markdown";
import { CoachThinking } from "@/components/CoachThinking";
import { RunAnalysisDialog } from "@/components/RunAnalysisDialog";

const fmtUsd = (n: number, known: boolean) => (known ? "$" + n.toFixed(n < 1 ? 4 : 2) : "n/v");
const reportLabel = (kind: string) => kind === "daily" ? "Tagesreport" : kind === "weekly" ? "Wochenreport" : "Antwort";
const shortModel = (m: string) => m.split("/").pop() ?? m;

export default function Coach() {
  const [reports, setReports] = useState<Report[] | null>(null);
  const [current, setCurrent] = useState<Report | null>(null);
  const [stats, setStats] = useState<CoachStats | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<null | "daily" | "weekly" | "chat">(null);
  const [message, setMessage] = useState("");

  const [panel, setPanel] = useState<"history" | "usage" | null>(null);

  useEffect(() => {
    api.coachReports(10).then((items) => { setReports(items); setCurrent((selected) => selected ?? items[0] ?? null); }).catch((e) => setLoadErr(String(e)));
    api.coachStats().then(setStats).catch(() => {});
  }, []);

  async function refreshList() {
    try {
      setReports(await api.coachReports(10));
      setStats(await api.coachStats());
    } catch {
      /* Liste/Stats nicht kritisch */
    }
  }

  async function run(kind: "daily" | "weekly") {
    if (busy) return;
    setActionErr(null);
    setBusy(kind);
    try {
      const rep = kind === "daily" ? await api.coachDaily() : await api.coachWeekly();
      setCurrent(rep);
      await refreshList();
    } catch (e) {
      setActionErr(String(e));
    } finally {
      setBusy(null);
    }
  }

  async function send() {
    const msg = message.trim();
    if (!msg || busy) return;
    setActionErr(null);
    setBusy("chat");
    try {
      const rep = await api.coachAsk(msg);
      setCurrent(rep);
      setMessage("");
      await refreshList();
    } catch (e) {
      setActionErr(String(e));
    } finally {
      setBusy(null);
    }
  }

  if (loadErr) return (<><PageTitle title="Coach" /><ApiError error={loadErr} /></>);
  if (!reports) return (<><PageTitle title="Coach" /><Loading /></>);

  return <>
    <CoachThinking busy={busy} />
    <PageTitle title="Coach" sub="Frag deine Daten" />
    <Card>
      <CardTitle title="Frag den Coach" sub="Ruft deine Kennzahlen ab · Enter sendet" />
      <form onSubmit={(event) => { event.preventDefault(); void send(); }} className="flex flex-wrap gap-2">
        <input aria-label="Frage an den Coach" type="text" value={message} onChange={(event) => setMessage(event.target.value)}
          disabled={busy !== null} placeholder="Wie ist mein Trend diese Woche?"
          className="min-w-0 flex-1 basis-48 rounded-lg border border-line bg-surface-alt px-3 py-2.5 text-base text-ink placeholder:text-muted focus:border-accent focus:outline-none disabled:opacity-60 sm:text-sm" />
        <button type="submit" disabled={busy !== null || !message.trim()}
          className="rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60">{busy === "chat" ? "Erstellt …" : "Senden"}</button>
      </form>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={() => run("daily")} disabled={busy !== null} className="rounded border border-line px-3 py-2 text-xs disabled:opacity-60">Tagesreport erstellen</button>
        <button type="button" onClick={() => run("weekly")} disabled={busy !== null} className="rounded border border-line px-3 py-2 text-xs disabled:opacity-60">Wochenreport erstellen</button>
      </div>
      {busy && <p role="status" className="mt-3 text-xs text-muted">{busy === "chat" ? "Antwort" : reportLabel(busy)} wird erstellt …</p>}
      {actionErr && <p role="alert" className="mt-3 rounded border border-bad/30 bg-bad/5 px-3 py-2 text-sm text-bad">{actionErr}</p>}
    </Card>
    <div className="mt-4 flex flex-wrap gap-2">
      <button type="button" onClick={() => setPanel("history")} className="rounded border border-line px-3 py-2 text-sm">Verlauf</button>
      <button type="button" onClick={() => setPanel("usage")} className="rounded border border-line px-3 py-2 text-sm">Details & Nutzung</button>
    </div>
    <Card className="mt-4">
      <CardTitle title={current ? reportLabel(current.kind) : "Antwort"} />
      {current ? <>
        <p className="mb-3 text-xs text-muted">Gespeichert am {new Date(current.created_at).toLocaleString("de-DE")}</p>
        <Markdown>{current.content}</Markdown>
      </> : <p className="text-sm text-muted">Stelle eine Frage oder erstelle einen Report.</p>}
    </Card>
    {panel === "history" && <RunAnalysisDialog title="Verlauf · letzte zehn Einträge" onClose={() => setPanel(null)}>
      {reports.length ? <ul className="divide-y divide-line">{reports.map((report) => <li key={report.id}>
        <button type="button" aria-current={current?.id === report.id ? "true" : undefined}
          onClick={() => { setCurrent(report); setPanel(null); }} className="w-full rounded py-3 text-left hover:bg-surface-alt">
          <div className="flex flex-wrap justify-between gap-2 text-sm"><span className="font-semibold">{reportLabel(report.kind)}{current?.id === report.id ? " · ausgewählt" : ""}</span><span className="text-xs text-muted">{new Date(report.created_at).toLocaleString("de-DE")}</span></div>
          <p className="mt-1 break-words text-xs text-muted">{report.content.slice(0, 120)}{report.content.length > 120 ? " …" : ""}</p>
        </button>
      </li>)}</ul> : <p className="text-sm text-muted">Noch keine gespeicherten Antworten.</p>}
    </RunAnalysisDialog>}
    {panel === "usage" && <RunAnalysisDialog title="Details & Nutzung" onClose={() => setPanel(null)}>
      {stats ? <dl className="grid grid-cols-2 gap-4 text-sm">
        {([
          ["Kosten gesamt", fmtUsd(stats.cost_total_usd, stats.cost_known)],
          ["Kosten · 7 Tage", fmtUsd(stats.cost_7d_usd, stats.cost_known)],
          ["Tokens gesamt", stats.tokens_total.toLocaleString("de-DE")],
          ["Tokens · 7 Tage", stats.tokens_7d.toLocaleString("de-DE")],
          ["Gespeicherte Einträge", String(stats.reports_total)],
          ["Einträge · 7 Tage", String(stats.reports_7d)],
          ["Aktuell eingestelltes Modell", shortModel(stats.model)],
        ] as [string, string][]).map(([label, value]) => <div key={label}><dt className="text-xs text-muted">{label}</dt><dd className="mt-1 break-words font-semibold">{value}</dd></div>)}
      </dl> : <p className="text-sm text-muted">Nutzungsdaten derzeit nicht verfügbar.</p>}
      {current && <section className="mt-5 border-t border-line pt-4 text-sm">
        <h3 className="font-semibold">Angezeigte Antwort</h3>
        <p className="mt-2 break-words">Modell: {current.model}</p>
        <p className="mt-1">Kosten: {current.cost_usd == null ? "nicht verfügbar" : fmtUsd(current.cost_usd, true)}</p>
        <p className="mt-2 break-words text-xs text-muted">Verwendete Tools: {current.tools_used?.length ? current.tools_used.join(", ") : "keine protokolliert"}</p>
      </section>}
    </RunAnalysisDialog>}
  </>;
}
