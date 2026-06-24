"use client";

import { useEffect, useState } from "react";
import { api, type Report, type CoachStats } from "@/lib/api";
import { Card, CardTitle, PageTitle, Loading, ApiError } from "@/components/ui";
import { Markdown } from "@/components/Markdown";
import { dm } from "@/lib/format";

const fmtUsd = (n: number, known: boolean) => (known ? "$" + n.toFixed(n < 1 ? 4 : 2) : "n/v");
const shortModel = (m: string) => m.split("/").pop() ?? m;

export default function Coach() {
  const [reports, setReports] = useState<Report[] | null>(null);
  const [current, setCurrent] = useState<Report | null>(null);
  const [stats, setStats] = useState<CoachStats | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [actionErr, setActionErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<null | "daily" | "weekly" | "chat">(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    api.coachReports(10).then(setReports).catch((e) => setLoadErr(String(e)));
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

  return (
    <>
      <PageTitle title="Coach" sub="Frag deine Daten – ehrlich-motivierend" />

      {stats && (
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {([
            ["Kosten gesamt", fmtUsd(stats.cost_total_usd, stats.cost_known), `${stats.tokens_total.toLocaleString("de-DE")} Tokens`],
            ["Kosten · 7 Tage", fmtUsd(stats.cost_7d_usd, stats.cost_known), `${stats.reports_7d} Reports`],
            ["Reports gesamt", String(stats.reports_total), "gespeichert"],
            ["Modell", shortModel(stats.model), "OpenRouter"],
          ] as [string, string, string][]).map(([l, v, s], i) => (
            <div key={i} className="rounded-card border border-line bg-surface p-3">
              <div className="text-[11px] text-muted">{l}</div>
              <div className="mt-0.5 break-words font-display text-lg font-bold tracking-tight">{v}</div>
              <div className="text-[10px] text-muted">{s}</div>
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => run("daily")}
          disabled={busy !== null}
          className="rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
        >
          {busy === "daily" ? "erstellt …" : "Täglicher Report"}
        </button>
        <button
          type="button"
          onClick={() => run("weekly")}
          disabled={busy !== null}
          className="rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
        >
          {busy === "weekly" ? "erstellt …" : "Wöchentlicher Report"}
        </button>
      </div>

      {actionErr && (
        <p className="mt-3 rounded-lg border border-bad/30 bg-bad/5 px-3 py-2 text-xs text-bad">
          {actionErr}
        </p>
      )}

      <Card className="mt-4">
        <CardTitle title="Aktueller Report" />
        {current ? (
          <>
            <p className="mb-3 break-words text-[11px] text-muted">
              {current.kind} · {shortModel(current.model)} · {dm(current.created_at)}
              {current.tools_used?.length ? ` · 🔧 ${current.tools_used.join(", ")}` : ""}
            </p>
            <Markdown>{current.content}</Markdown>
          </>
        ) : (
          <p className="text-sm text-muted">
            Erzeuge einen Report oder stelle unten eine Frage.
          </p>
        )}
      </Card>

      <Card className="mt-4">
        <CardTitle title="Frag den Coach" sub="ruft live deine Kennzahlen ab · Enter sendet" />
        <div className="flex gap-2">
          <input
            type="text"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                send();
              }
            }}
            disabled={busy !== null}
            placeholder="z. B. Wie ist mein Trend diese Woche?"
            className="flex-1 rounded-lg border border-line bg-surface-alt px-3 py-2.5 text-sm text-ink placeholder:text-muted focus:border-accent focus:outline-none disabled:opacity-60"
          />
          <button
            type="button"
            onClick={send}
            disabled={busy !== null || !message.trim()}
            className="rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60"
          >
            {busy === "chat" ? "erstellt …" : "Senden"}
          </button>
        </div>
      </Card>

      <Card className="mt-4">
        <CardTitle title="Frühere Reports" />
        {reports.length === 0 ? (
          <p className="text-sm text-muted">Noch keine Reports.</p>
        ) : (
          <ul className="divide-y divide-line">
            {reports.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  onClick={() => setCurrent(r)}
                  className="w-full py-3 text-left hover:opacity-80"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-semibold">{r.kind}</span>
                    <span className="shrink-0 text-[11px] text-muted">
                      {new Date(r.created_at).toLocaleString("de-DE")}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted">
                    {r.content.slice(0, 120)}
                    {r.content.length > 120 ? " …" : ""}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}