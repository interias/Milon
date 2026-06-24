"use client";

import { useEffect, useState } from "react";
import { api, type AppSettings, type SettingsUpdate } from "@/lib/api";
import { Card, CardTitle, PageTitle, Loading, ApiError } from "@/components/ui";

type SecretKey = "openrouter_api_key" | "hevy_api_key" | "fddb_pw" | "fddb_cookie" | "fddb_phpsessid";
const INPUT =
  "w-full rounded-lg border border-line bg-surface-alt px-3 py-2 text-base text-ink placeholder:text-muted focus:border-accent focus:outline-none sm:text-sm";

export default function Einstellungen() {
  const [s, setS] = useState<AppSettings | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [scheduler, setScheduler] = useState(true);
  const [fddbUser, setFddbUser] = useState("");
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    api.settingsGet()
      .then((d) => { setS(d); setModel(d.openrouter_model); setScheduler(d.scheduler_enabled); })
      .catch((e) => setErr(String(e)));
  }, []);

  async function save() {
    if (!s) return;
    setBusy(true);
    setMsg(null);
    try {
      const body: SettingsUpdate = { scheduler_enabled: scheduler };
      if (model && model !== s.openrouter_model) body.openrouter_model = model;
      if (fddbUser.trim()) body.fddb_user = fddbUser.trim();
      (["openrouter_api_key", "hevy_api_key", "fddb_pw", "fddb_cookie", "fddb_phpsessid"] as SecretKey[]).forEach((k) => {
        if (secrets[k]?.trim()) body[k] = secrets[k].trim();
      });
      const updated = await api.settingsUpdate(body);
      setS(updated);
      setModel(updated.openrouter_model);
      setScheduler(updated.scheduler_enabled);
      setSecrets({});
      setFddbUser("");
      setMsg("Gespeichert ✓");
    } catch (e) {
      setMsg("Fehler: " + String(e));
    } finally {
      setBusy(false);
    }
  }

  if (err) return (<><PageTitle title="Einstellungen" /><ApiError error={err} /></>);
  if (!s) return (<><PageTitle title="Einstellungen" /><Loading /></>);

  const secret = (key: SecretKey, label: string) => (
    <label className="block">
      <span className="mb-1 block text-[11px] text-muted">
        {label}{" "}
        {s.keys[key].set
          ? <span className="text-good">· gesetzt {s.keys[key].hint}</span>
          : <span className="text-bad">· nicht gesetzt</span>}
      </span>
      <input
        type="password"
        value={secrets[key] ?? ""}
        onChange={(e) => setSecrets((v) => ({ ...v, [key]: e.target.value }))}
        placeholder="neu setzen (leer = unverändert)"
        className={INPUT}
        autoComplete="new-password"
      />
    </label>
  );

  return (
    <>
      <PageTitle title="Einstellungen" sub="Keys, Coach-Modell & Automatik · wird in server/.env gespeichert" />

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardTitle title="LLM-Coach (OpenRouter)" />
          <div className="space-y-3">
            <label className="block">
              <span className="mb-1 block text-[11px] text-muted">Modell</span>
              <input type="text" value={model} onChange={(e) => setModel(e.target.value)} className={INPUT} placeholder="z. B. deepseek/deepseek-v4-flash" />
            </label>
            {secret("openrouter_api_key", "OpenRouter API-Key")}
          </div>
        </Card>

        <Card>
          <CardTitle title="Automatik" sub="Geplante Syncs (Hevy / FDDB / Health Connect)" />
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <input type="checkbox" checked={scheduler} onChange={(e) => setScheduler(e.target.checked)} className="h-5 w-5" style={{ accentColor: "var(--color-accent)" }} />
            Scheduler aktiv
          </label>
          <p className="mt-2 text-[11px] text-muted">
            Hevy alle 6 h · FDDB täglich · HC-Ordner-Scan alle 10 min. Manuell über „↻ Daten aktualisieren".
          </p>
        </Card>

        <Card className="md:col-span-2">
          <CardTitle title="Quellen-Zugänge" />
          <div className="grid gap-3 sm:grid-cols-2">
            {secret("hevy_api_key", "Hevy API-Key")}
            <label className="block">
              <span className="mb-1 block text-[11px] text-muted">
                FDDB Benutzer {s.fddb_user_masked && <span className="text-muted">· {s.fddb_user_masked}</span>}
              </span>
              <input type="text" value={fddbUser} onChange={(e) => setFddbUser(e.target.value)} placeholder="E-Mail (leer = unverändert)" className={INPUT} />
            </label>
            {secret("fddb_pw", "FDDB Passwort")}
            {secret("fddb_cookie", "FDDB Cookie (fddb)")}
            {secret("fddb_phpsessid", "FDDB PHPSESSID")}
          </div>
        </Card>
      </div>

      {msg && <p className={`mt-3 text-sm font-semibold ${msg.startsWith("Fehler") ? "text-bad" : "text-good"}`}>{msg}</p>}

      <button
        type="button" onClick={save} disabled={busy}
        className="mt-4 w-full rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-60 sm:w-auto"
      >
        {busy ? "speichert …" : "Speichern"}
      </button>
    </>
  );
}
