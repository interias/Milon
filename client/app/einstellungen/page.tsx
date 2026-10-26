"use client";

import { useEffect, useState } from "react";
import { api, type AppSettings, type SettingsUpdate } from "@/lib/api";
import { Card, CardTitle, PageTitle, Loading, ApiError } from "@/components/ui";
import CoachGoals from "@/components/CoachGoals";

type SecretKey = "anthropic_api_key" | "openrouter_api_key" | "hevy_api_key" | "fddb_pw" | "fddb_cookie" | "fddb_phpsessid";
const ANTHROPIC_MODELS = [
  { id: "claude-opus-5-5", label: "Opus 5.5" },
  { id: "claude-sonnet-5-5", label: "Sonnet 5.5" },
  { id: "claude-haiku-5-5", label: "Haiku 5.5" },
];
const EFFORTS = ["low", "medium", "high"] as const;
const usd = (v: number) => `${v.toFixed(2).replace(".", ",")} $`;
const INPUT =
  "w-full rounded-lg border border-line bg-surface-alt px-3 py-2 text-base text-ink placeholder:text-muted focus:border-accent focus:outline-none sm:text-sm";

function BudgetBar({ b }: { b: AppSettings["llm_budget"] }) {
  const pct = Math.min(100, Math.round(b.ratio * 100));
  const color = b.exceeded ? "var(--color-bad)" : b.warn ? "#b7791f" : "var(--color-accent)";
  return (
    <div aria-label="Monatskosten">
      <div className="mb-1 flex items-baseline justify-between gap-2 text-[11px] text-muted">
        <span>Kosten {b.month}</span>
        <span>{b.budget_usd > 0 ? `${usd(b.spent.anthropic)} von ${usd(b.budget_usd)} · ${Math.round(b.ratio * 100)} %` : `${usd(b.spent.anthropic)} · kein Limit`}</span>
      </div>
      {b.budget_usd > 0 && (
        <div className="h-2 overflow-hidden rounded-full bg-line" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
          <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
        </div>
      )}
      <p className="mt-1 text-[11px] text-muted">Anthropic {usd(b.spent.anthropic)} · OpenRouter {usd(b.spent.openrouter)} (zählt nicht zum Budget)</p>
      {b.exceeded
        ? <p className="mt-1 text-[11px] font-semibold text-bad">Budget ausgeschöpft — der Coach läuft bis Monatsende über OpenRouter.</p>
        : b.warn && <p className="mt-1 text-[11px] font-semibold" style={{ color }}>Achtung: über 80 % des Monatsbudgets verbraucht.</p>}
    </div>
  );
}

export default function Einstellungen() {
  const [s, setS] = useState<AppSettings | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [model, setModel] = useState("");
  const [provider, setProvider] = useState("");
  const [aModel, setAModel] = useState("claude-opus-5-5");
  const [effort, setEffort] = useState("medium");
  const [budget, setBudget] = useState("100");
  const [scheduler, setScheduler] = useState(true);
  const [hrMax, setHrMax] = useState("");
  const [ftp, setFtp] = useState("");
  const [stride, setStride] = useState("");
  const [padIncline, setPadIncline] = useState("");
  const [padUpload, setPadUpload] = useState(true);
  const [places, setPlaces] = useState<string[]>([]);
  const [newPlace, setNewPlace] = useState("");
  const [fddbUser, setFddbUser] = useState("");
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  function setPad(d: AppSettings) {
    setStride(String(d.walkpad_stride_m ?? "")); setPadIncline(String(d.walkpad_incline_pct ?? "")); setPadUpload(d.walkpad_garmin_upload ?? true);
  }

  function applyLlm(d: AppSettings) {
    setProvider(d.llm_provider); setAModel(d.anthropic_model); setEffort(d.anthropic_effort);
    setBudget(String(d.llm_monthly_budget_usd));
  }

  useEffect(() => {
    api.settingsGet()
      .then((d) => { setS(d); applyLlm(d); setModel(d.openrouter_model); setScheduler(d.scheduler_enabled); setHrMax(String(d.run_hr_max ?? "")); setFtp(String(d.bike_ftp ?? "")); setPad(d); setPlaces(d.weather_places ?? []); })
      .catch((e) => setErr(String(e)));
  }, []);

  async function save() {
    if (!s) return;
    setBusy(true);
    setMsg(null);
    try {
      const body: SettingsUpdate = { scheduler_enabled: scheduler };
      if (model && model !== s.openrouter_model) body.openrouter_model = model;
      if (provider !== s.llm_provider) body.llm_provider = provider;
      if (aModel !== s.anthropic_model) body.anthropic_model = aModel;
      if (effort !== s.anthropic_effort) body.anthropic_effort = effort;
      const bud = parseFloat(budget.replace(",", "."));
      if (!Number.isNaN(bud) && bud >= 0 && bud !== s.llm_monthly_budget_usd) body.llm_monthly_budget_usd = bud;
      const hr = parseFloat(hrMax);
      if (!Number.isNaN(hr) && hr >= 0 && hr !== s.run_hr_max) body.run_hr_max = hr;
      const watts = parseFloat(ftp);
      if (!Number.isNaN(watts) && watts >= 0 && watts !== s.bike_ftp) body.bike_ftp = watts;
      const strideM = parseFloat(stride.replace(",", "."));
      if (!Number.isNaN(strideM) && strideM !== s.walkpad_stride_m) body.walkpad_stride_m = strideM;
      const inc = parseFloat(padIncline.replace(",", "."));
      if (!Number.isNaN(inc) && inc !== s.walkpad_incline_pct) body.walkpad_incline_pct = inc;
      if (padUpload !== s.walkpad_garmin_upload) body.walkpad_garmin_upload = padUpload;
      const wanted = newPlace.trim() ? [...places, newPlace.trim()] : places;
      if (JSON.stringify(wanted) !== JSON.stringify(s.weather_places ?? [])) body.weather_places = wanted;
      if (fddbUser.trim()) body.fddb_user = fddbUser.trim();
      (["anthropic_api_key", "openrouter_api_key", "hevy_api_key", "fddb_pw", "fddb_cookie", "fddb_phpsessid"] as SecretKey[]).forEach((k) => {
        if (secrets[k]?.trim()) body[k] = secrets[k].trim();
      });
      const updated = await api.settingsUpdate(body);
      setS(updated);
      applyLlm(updated);
      setModel(updated.openrouter_model);
      setScheduler(updated.scheduler_enabled);
      setHrMax(String(updated.run_hr_max ?? ""));
      setFtp(String(updated.bike_ftp ?? ""));
      setPad(updated);
      setPlaces(updated.weather_places ?? []);
      setNewPlace("");
      setSecrets({});
      setFddbUser("");
      setMsg("Gespeichert ✓");
    } catch (e) {
      setMsg("Fehler: " + String(e));
    } finally {
      setBusy(false);
    }
  }

  if (err) return (<><PageTitle title="Einstellungen" /><CoachGoals /><ApiError error={err} /></>);
  if (!s) return (<><PageTitle title="Einstellungen" /><CoachGoals /><Loading /></>);

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
      <PageTitle title="Einstellungen" sub="Coach-Ziele, Keys, Modell & Automatik · lokal gespeichert" />

      <CoachGoals />

      <div className="grid gap-4 md:grid-cols-2">
        <Card className="md:col-span-2">
          <CardTitle title="Coach · KI-Anbieter" sub="Anthropic (Claude) oder OpenRouter — greift sofort, ohne .env-Editieren" />
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-3">
              <div>
                <span className="mb-1 block text-[11px] text-muted">Anbieter</span>
                <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Anbieter">
                  {([["", "Automatisch"], ["anthropic", "Anthropic"], ["openrouter", "OpenRouter"]] as const).map(([v, l]) => (
                    <button key={v} type="button" role="radio" aria-checked={provider === v} onClick={() => setProvider(v)}
                      className={`rounded-lg border px-3 py-2 text-sm font-semibold ${provider === v ? "border-accent bg-accent text-white" : "border-line bg-surface-alt text-ink"}`}>{l}</button>
                  ))}
                </div>
                <p className="mt-1 text-[11px] text-muted">
                  Automatisch = Anthropic, sobald ein Key gesetzt ist, sonst OpenRouter. Aktiv: <strong>{s.llm_provider_resolved === "anthropic" ? "Anthropic" : "OpenRouter"}</strong>.
                  Bei Ausfall oder ausgeschöpftem Budget springt der Coach selbst auf OpenRouter.
                </p>
              </div>
              <label className="block">
                <span className="mb-1 block text-[11px] text-muted">Anthropic-Modell</span>
                <select value={aModel} onChange={(e) => setAModel(e.target.value)} className={INPUT}>
                  {ANTHROPIC_MODELS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                </select>
              </label>
              <div>
                <span className="mb-1 block text-[11px] text-muted">Effort</span>
                <div className="flex gap-2" role="radiogroup" aria-label="Effort">
                  {EFFORTS.map((e) => (
                    <button key={e} type="button" role="radio" aria-checked={effort === e} onClick={() => setEffort(e)}
                      className={`rounded-lg border px-3 py-2 text-sm font-semibold ${effort === e ? "border-accent bg-accent text-white" : "border-line bg-surface-alt text-ink"}`}>{e}</button>
                  ))}
                </div>
              </div>
              {secret("anthropic_api_key", "Anthropic API-Key")}
            </div>
            <div className="space-y-3">
              <label className="block">
                <span className="mb-1 block text-[11px] text-muted">OpenRouter-Modell</span>
                <input type="text" value={model} onChange={(e) => setModel(e.target.value)} className={INPUT} placeholder="z. B. deepseek/deepseek-v4-flash" />
              </label>
              {secret("openrouter_api_key", "OpenRouter API-Key")}
              <label className="block">
                <span className="mb-1 block text-[11px] text-muted">Monatsbudget Anthropic (USD, 0 = kein Limit)</span>
                <input type="number" inputMode="decimal" min={0} step={1} value={budget} onChange={(e) => setBudget(e.target.value)} className={INPUT} />
              </label>
              <BudgetBar b={s.llm_budget} />
            </div>
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
          <CardTitle title="Laufen · Puls-Zonen" sub="Basis für die Karte „Pace je Puls-Zone“ auf der Laufen-Seite" />
          <label className="block max-w-xs">
            <span className="mb-1 block text-[11px] text-muted">Maximalpuls (HFmax) in bpm</span>
            <input
              type="number" inputMode="numeric" min={0} max={230} step={1}
              value={hrMax} onChange={(e) => setHrMax(e.target.value)}
              placeholder="z. B. 180" className={INPUT}
            />
          </label>
          <p className="mt-2 text-[11px] text-muted">
            Zonen-Grenzen: Z1 &lt;70 % · Z2 70–80 % · Z3 80–90 % · Z4 ≥90 % von HFmax.
            <strong> 0</strong> = automatisch aus den Daten ableiten (robustes 95.-Perzentil, Boden 180) —
            fest eingetragen ist robuster gegen Sensor-Ausreißer.
          </p>
        </Card>

        <Card className="md:col-span-2">
          <CardTitle title="Rad · FTP" sub="Basis für Leistungszonen, IF und TSS der Indoor-Fahrten (Zwift/Rolle)" />
          <label className="block max-w-xs">
            <span className="mb-1 block text-[11px] text-muted">FTP in Watt</span>
            <input
              type="number" inputMode="numeric" min={0} max={1000} step={1}
              value={ftp} onChange={(e) => setFtp(e.target.value)}
              placeholder="0 = automatisch" className={INPUT}
            />
          </label>
          <p className="mt-2 text-[11px] text-muted">
            <strong>0</strong> = automatisch: eFTP aus deinen Fahrten (95 % der besten 20 min der letzten 90 Tage),
            ohne brauchbare Fahrt Garmins FTP. Solange nur lockere Fahrten vorliegen (Wert unter 85 % der Garmin-FTP), gilt Garmins FTP als Untergrenze. Ein fester Wert übersteuert die Schätzung.
          </p>
        </Card>

        <Card className="md:col-span-2">
          <CardTitle title="Laufband" sub="Walking-Pad unterm Schreibtisch · Sessions kommen vom Recorder auf dem PC (tools/walkpad)" />
          <div className="flex flex-wrap gap-4">
            <label className="block w-40">
              <span className="mb-1 block text-[11px] text-muted">Schrittlänge in m</span>
              <input type="number" inputMode="decimal" min={0.3} max={1.5} step={0.01} value={stride} onChange={(e) => setStride(e.target.value)} className={INPUT} />
            </label>
            <label className="block w-40">
              <span className="mb-1 block text-[11px] text-muted">Steigung in % (neue Walks)</span>
              <input type="number" inputMode="decimal" min={0} max={15} step={1} value={padIncline} onChange={(e) => setPadIncline(e.target.value)} className={INPUT} />
            </label>
            <label className="flex items-center gap-2 self-end pb-2 text-sm">
              <input type="checkbox" checked={padUpload} onChange={(e) => setPadUpload(e.target.checked)} />Walks zu Garmin Connect hochladen
            </label>
          </div>
          <p className="mt-2 text-[11px] text-muted">
            Das Pad meldet keine Schritte: Schritte = Distanz ÷ Schrittlänge (gilt auch rückwirkend). Kalibrieren: 100 Schritte zählen und
            die Distanz-Anzeige des Pads durch 100 teilen. Die Steigung stellst du am Pad von Hand ein; sie wird nicht übertragen.
          </p>
        </Card>

        <Card className="md:col-span-2">
          <CardTitle title="Wetter · Orte" sub="Tagesverlauf oben auf der Übersicht (Open-Meteo, ohne Konto) · auf der Karte durchblätterbar" />
          {places.length > 0 && <ul className="mb-3 max-w-md divide-y divide-line rounded-lg border border-line">
            {places.map((name, i) => <li key={name} className="flex items-center gap-2 px-3 py-2 text-sm">
              <span className="min-w-0 flex-1 truncate">{name}</span>
              {i === 0 ? <span className="text-[11px] font-semibold text-accent">Standard</span>
                : <button type="button" onClick={() => setPlaces([name, ...places.filter((p) => p !== name)])} className="text-[11px] text-muted underline underline-offset-4">Als Standard</button>}
              <button type="button" aria-label={`${name} entfernen`} onClick={() => setPlaces(places.filter((p) => p !== name))} className="px-1 text-muted hover:text-bad">✕</button>
            </li>)}
          </ul>}
          <label className="block max-w-md">
            <span className="mb-1 block text-[11px] text-muted">Ort hinzufügen</span>
            <input type="text" value={newPlace} onChange={(e) => setNewPlace(e.target.value)} placeholder="z. B. Köln" className={INPUT} />
          </label>
          <p className="mt-2 text-[11px] text-muted">
            Neue Orte werden beim Speichern gesucht und als gerundete Koordinate in server/.env abgelegt; nur diese geht an Open-Meteo.
            Höchstens 8 Orte; ohne Orte ist die Wetterkarte ausgeblendet.
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
