"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import {
  circumferenceApi, formatCm, signedCm, measurementDate, measurementStamp,
  measurementBounds, measurementStats, measurementSegments, measurementMonths,
  type CircumferenceData, type CircumferenceDefinition, type CircumferenceEntry,
  type CircumferenceInput, type CircumferencePreferences, type CircumferencePeriod,
  type MeasureKey, type MeasurementBounds, type MeasurementStats,
} from "@/lib/circumferences";
import styles from "./BodyCircumferences.module.css";

const PERIODS: [CircumferencePeriod, string][] = [["1m", "1 M"], ["3m", "3 M"], ["6m", "6 M"], ["12m", "1 J"], ["all", "Alles"]];
const errorMessage = (error: unknown) => error instanceof Error ? error.message : "Die Anfrage ist fehlgeschlagen. Bitte erneut versuchen.";
const measureStyle = (color: string) => ({ "--measure": color }) as CSSProperties;

function Dialog({ title, children, onClose, busy = false, wide = false }: {
  title: string; children: ReactNode; onClose: () => void; busy?: boolean; wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null), titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return <dialog ref={ref} aria-labelledby={titleId} className={`${styles.dialog} ${wide ? styles.wideDialog : ""}`}
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className={styles.dialogHead}><h3 id={titleId}>{title}</h3><button type="button" className={styles.closeButton} disabled={busy} onClick={onClose} aria-label="Schließen">×</button></div>
    {children}
  </dialog>;
}

function BodyDiagram({ definitions, active, onSelect }: {
  definitions: CircumferenceDefinition[]; active: MeasureKey; onSelect?: (key: MeasureKey) => void;
}) {
  return <div className={styles.bodyDiagram}>
    <div className={styles.bodyOutline} />
    <svg viewBox="0 0 480 720" role="img" aria-label={`Schematische Messstellen: ${definitions.map(definition => definition.name).join(", ")}`}>
      {definitions.map(definition => {
        const [x, y, width, height] = definition.guide;
        return <g key={definition.key} className={styles.bodyMarker} opacity={active === definition.key ? 1 : .4}
          role={onSelect ? "button" : undefined} tabIndex={onSelect ? 0 : undefined}
          aria-label={`${definition.name}: ${definition.site}`} onClick={() => onSelect?.(definition.key)}
          onKeyDown={event => { if (onSelect && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); onSelect(definition.key); } }}>
          <title>{definition.name} · {definition.site}</title>
          <ellipse cx={x + width / 2} cy={y} rx={width / 2} ry={height / 2} fill={definition.color} fillOpacity=".12" stroke={definition.color} strokeWidth="3.5" />
          <circle cx={x + width} cy={y} r="7" fill={definition.color} stroke="white" strokeWidth="2" />
        </g>;
      })}
    </svg>
  </div>;
}

function MeasureName({ definition, onClick }: { definition: CircumferenceDefinition; onClick: () => void }) {
  return <button type="button" className={styles.measureName} onClick={onClick}>
    <i style={{ background: definition.color }} /><span><strong>{definition.name}</strong><small>{definition.site}</small></span>
  </button>;
}

function Trend({ stat, bounds }: { stat: MeasurementStats; bounds: MeasurementBounds }) {
  const gradientId = useId().replace(/:/g, "");
  if (!stat.count) return <div className={styles.emptyChart}>Hier beginnt dein Verlauf.</div>;
  const width = 420, height = 62, values = stat.points.map(point => point.value);
  const low = Math.min(...values) - .2, high = Math.max(...values) + .2;
  const span = measurementStamp(bounds.end) - measurementStamp(bounds.start);
  const x = (date: string) => span ? 4 + (measurementStamp(date) - measurementStamp(bounds.start)) / span * (width - 8) : width / 2;
  const y = (value: number) => 6 + (high - value) / Math.max(high - low, 1) * (height - 12);
  return <svg className={styles.rowChart} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img"
    aria-label={`${stat.name}: ${stat.count === 1 ? "ein Messwert" : `${formatCm(stat.first!.value)} auf ${formatCm(stat.last!.value)} Zentimeter`}`}>
    <defs><linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1"><stop stopColor={stat.color} stopOpacity=".14" /><stop offset="1" stopColor={stat.color} stopOpacity="0" /></linearGradient></defs>
    <line x1="0" x2={width} y1={height - 1} y2={height - 1} stroke="#edf1f0" />
    {measurementSegments(stat.points).filter(segment => segment.length > 1).map(segment => {
      const path = segment.map((point, index) => `${index ? "L" : "M"}${x(point.date)},${y(point.value)}`).join(" ");
      return <g key={segment[0].date}><path d={`${path} L${x(segment.at(-1)!.date)},${height} L${x(segment[0].date)},${height} Z`} fill={`url(#${gradientId})`} /><path d={path} fill="none" stroke={stat.color} strokeWidth="2" vectorEffect="non-scaling-stroke" /></g>;
    })}
    {stat.points.map((point, index) => <circle key={point.date} cx={x(point.date)} cy={y(point.value)} r={index === stat.count - 1 ? 2.7 : 1.5} fill={stat.color}><title>{measurementDate(point.date, true)} · {formatCm(point.value)} cm</title></circle>)}
  </svg>;
}

function MeasureRow({ stat, bounds, active, onSelect }: {
  stat: MeasurementStats; bounds: MeasurementBounds; active: boolean; onSelect: () => void;
}) {
  return <article className={`${styles.measureRow} ${active ? styles.selected : ""}`} style={measureStyle(stat.color)}>
    <div className={styles.rowTop}><MeasureName definition={stat} onClick={onSelect} />
      <div className={styles.rowDelta}>{signedCm(stat.delta)} <small>cm</small><em>{stat.count === 1 ? "Startwert" : stat.percent == null ? "—" : `${signedCm(stat.percent)} %`}</em></div>
    </div>
    <div className={styles.rowMain}><div className={styles.chartCell}><Trend stat={stat} bounds={bounds} /></div>
      <div className={styles.rowValues}><span>{formatCm(stat.first?.value)} <i>→</i></span><strong>{formatCm(stat.last?.value)} <small>cm</small></strong></div>
    </div>
    <div className={styles.rowMeta}><span>{stat.first ? `${measurementDate(stat.first.date, true)} → ${measurementDate(stat.last!.date, true)}` : "Noch keine Messung"}</span><span>{stat.count} {stat.count === 1 ? "Messung" : "Messungen"}</span></div>
  </article>;
}

function Guide({ definition }: { definition: CircumferenceDefinition }) {
  return <div className={styles.entryGuide}>
    <div className={styles.guideFigure}><BodyDiagram definitions={[definition]} active={definition.key} /></div>
    <div className={styles.guideCopy}><p className={styles.guideLabel}>SO MISST DU</p><h4>{definition.name}</h4><p>{definition.definition}</p><small>Schematische Markierung · rechts am Körper ist links im Bild.</small></div>
  </div>;
}

function EntryDialog({ data, entry, historical, measure, onClose, onSaved }: {
  data: CircumferenceData; entry?: CircumferenceEntry; historical?: boolean; measure: MeasureKey;
  onClose: () => void; onSaved: (entry: CircumferenceEntry) => void;
}) {
  const [date, setDate] = useState(entry?.date || (historical ? "" : data.today));
  const [protocol, setProtocol] = useState<CircumferenceInput["protocol"]>(entry?.protocol || (historical ? "unknown" : "standard"));
  const [values, setValues] = useState<Partial<Record<MeasureKey, string>>>(() => Object.fromEntries(Object.entries(entry?.values || {}).map(([key, value]) => [key, String(value).replace(".", ",")])));
  const [active, setActive] = useState(measure), [saving, setSaving] = useState(false), [error, setError] = useState("");
  const definition = data.definitions.find(definition => definition.key === active) || data.definitions[0];
  const primary = data.definitions.filter(definition => data.preferences.visible_keys.includes(definition.key));
  const extra = data.definitions.filter(definition => !data.preferences.visible_keys.includes(definition.key));
  const [extraOpen, setExtraOpen] = useState(extra.some(definition => entry?.values[definition.key] != null));

  async function save(event: FormEvent) {
    event.preventDefault();
    const parsed: CircumferenceInput["values"] = {};
    for (const definition of data.definitions) {
      const raw = (values[definition.key] || "").trim();
      if (!raw) continue;
      const value = Number(raw.replace(",", "."));
      if (!/^\d+(?:[.,]\d+)?$/.test(raw) || !Number.isFinite(value) || value < 10 || value > 250) { setError(`${definition.name}: Bitte einen Wert zwischen 10 und 250 cm eingeben.`); return; }
      parsed[definition.key] = value;
    }
    if (!date || date > data.today) { setError("Bitte ein gültiges Messdatum bis heute wählen."); return; }
    if (!Object.keys(parsed).length) { setError("Bitte mindestens ein Maß eingeben."); return; }
    setSaving(true); setError("");
    try {
      const input = { date, protocol, values: parsed };
      const result = entry ? await circumferenceApi.update(entry.id, input) : await circumferenceApi.create(input);
      onSaved(result);
    } catch (error) { setError(errorMessage(error)); setSaving(false); }
  }

  function field(definition: CircumferenceDefinition) {
    return <label key={definition.key} className={`${styles.entryField} ${definition.key === active ? styles.activeField : ""}`}>
      <span className={styles.fieldCopy}><strong><i style={{ background: definition.color }} />{definition.name}</strong><small>{definition.site}</small></span>
      <span className={styles.inputWrap}><input aria-label={`${definition.name} in Zentimetern`} type="text" inputMode="decimal" placeholder="—" disabled={saving}
        value={values[definition.key] || ""} onFocus={() => setActive(definition.key)}
        onChange={event => setValues(previous => ({ ...previous, [definition.key]: event.target.value }))} /><span>cm</span></span>
    </label>;
  }

  return <Dialog title={entry ? "Messung bearbeiten" : historical ? "Frühere Maße nachtragen" : "Maße eintragen"} onClose={onClose} busy={saving} wide>
    <form onSubmit={save}>
      <div className={styles.entryContent}>
        <div className={styles.dateRow}><label>Messdatum<input type="date" value={date} max={data.today} required disabled={saving} onChange={event => setDate(event.target.value)} /></label><p>Ein Maß genügt.<br />Alle Angaben in Zentimetern.</p></div>
        <div className={styles.entryWorkspace}><Guide definition={definition} /><div className={styles.fieldsPanel}>
          <div className={styles.entryFields}>{primary.map(field)}</div>
          {!!extra.length && <details className={styles.extraFields} open={extraOpen} onToggle={event => setExtraOpen(event.currentTarget.open)}><summary>Weitere Maße ({extra.length})</summary><div className={styles.entryFields}>{extra.map(field)}</div></details>}
        </div></div>
        {entry && <p className={styles.note}>Ein geleertes Feld entfernt diesen Wert aus der Messung. Andere eingetragene Werte bleiben erhalten.</p>}
        <details className={styles.protocolDetails} open={historical || entry?.protocol === "unknown" ? true : undefined}>
          <summary>Messstellen & ältere Werte</summary><label>Entsprechen die Messstellen der Beschreibung?<select value={protocol} disabled={saving} onChange={event => setProtocol(event.target.value as CircumferenceInput["protocol"])}><option value="standard">Ja, gleiche Messstellen</option><option value="unknown">Unbekannt oder abweichend</option></select></label>
          <p className={styles.note}>Unbekannte oder abweichende Messstellen bleiben im Journal und werden nicht mit den Verlaufskurven vermischt.</p>
        </details>
        {error && <p className={styles.error} role="alert">{error}</p>}
      </div>
      <div className={styles.dialogActions}><button type="button" className={styles.secondary} disabled={saving} onClick={onClose}>Abbrechen</button><button type="submit" className={styles.primary} disabled={saving}>{saving ? "Speichern …" : "Speichern"}</button></div>
    </form>
  </Dialog>;
}

function PreferencesDialog({ data, onClose, onSave }: {
  data: CircumferenceData; onClose: () => void; onSave: (preferences: CircumferencePreferences) => Promise<void>;
}) {
  const [keys, setKeys] = useState(data.preferences.visible_keys), [saving, setSaving] = useState(false), [error, setError] = useState("");
  async function save(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError("");
    try { await onSave({ ...data.preferences, visible_keys: keys }); onClose(); }
    catch (error) { setSaving(false); setError(errorMessage(error)); }
  }
  return <Dialog title="Welche Maße siehst du?" onClose={onClose} busy={saving}>
    <form onSubmit={save}><div className={styles.dialogContent}><p className={styles.note}>Wähle ein bis vier Maße für deine Übersicht. Im Messjournal bleiben alle Werte erhalten.</p>
      <div className={styles.configOptions}>{data.definitions.map(definition => <label key={definition.key} className={styles.configOption}>
        <input type="checkbox" checked={keys.includes(definition.key)} disabled={saving || (!keys.includes(definition.key) && keys.length >= 4)}
          onChange={event => setKeys(previous => event.target.checked ? [...previous, definition.key] : previous.filter(key => key !== definition.key))} />
        <span><strong>{definition.name}</strong><small>{definition.site}{definition.key === "shoulders_deltoid" ? " · besser zu zweit" : ""}</small></span>
      </label>)}</div><p className={styles.note}>{keys.length} von 4 ausgewählt</p>{error && <p className={styles.error} role="alert">{error}</p>}
    </div><div className={styles.dialogActions}><button type="button" className={styles.secondary} disabled={saving} onClick={onClose}>Abbrechen</button><button type="submit" className={styles.primary} disabled={saving || !keys.length}>{saving ? "Speichern …" : "Anzeige übernehmen"}</button></div></form>
  </Dialog>;
}

type OpenEntry = { entry?: CircumferenceEntry; historical?: boolean };

export function BodyCircumferences() {
  const [data, setData] = useState<CircumferenceData | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState("");
  const [preferenceBusy, setPreferenceBusy] = useState(false), [deletingId, setDeletingId] = useState<number | null>(null);
  const [selected, setSelected] = useState<MeasureKey>("abdomen_navel"), [entry, setEntry] = useState<OpenEntry | null>(null);
  const [configOpen, setConfigOpen] = useState(false), [guideOpen, setGuideOpen] = useState(false), [notice, setNotice] = useState("");
  const [journalOpen, setJournalOpen] = useState(false), [journalMode, setJournalMode] = useState<"entries" | "months">("entries");

  const load = useCallback(async (signal?: AbortSignal, savedMessage?: string) => {
    setLoading(true); setError("");
    try { const result = await circumferenceApi.get(signal); setData(result); }
    catch (error) { if (!signal?.aborted) setError(savedMessage ? `${savedMessage} Die Ansicht konnte anschließend nicht neu geladen werden. ${errorMessage(error)}` : errorMessage(error)); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, []);
  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(""), 4500); return () => clearTimeout(timer); }, [notice]);

  const bounds = useMemo(() => data ? measurementBounds(data.entries, data.preferences.period, data.today) : null, [data]);
  const stats = useMemo(() => data && bounds ? measurementStats(data.definitions, data.entries, bounds) : [], [data, bounds]);

  async function savePreferences(preferences: CircumferencePreferences) {
    setPreferenceBusy(true);
    try {
      const saved = await circumferenceApi.preferences(preferences);
      setData(previous => previous ? { ...previous, preferences: saved } : previous);
      setError("");
    } finally { setPreferenceBusy(false); }
  }
  function changePreferences(update: Partial<CircumferencePreferences>) {
    if (!data) return;
    void savePreferences({ ...data.preferences, ...update }).catch(error => setError(errorMessage(error)));
  }
  function entrySaved(saved: CircumferenceEntry) {
    setData(previous => previous ? { ...previous, entries: [...previous.entries.filter(entry => entry.id !== saved.id), saved].sort((a, b) => b.date.localeCompare(a.date)) } : previous);
    setEntry(null); setNotice("Messung gespeichert.");
    void load(undefined, "Die Messung wurde gespeichert.");
  }
  async function remove(entry: CircumferenceEntry) {
    if (!window.confirm(`Messung vom ${measurementDate(entry.date, true)} mit allen enthaltenen Maßen dauerhaft löschen?`)) return;
    setDeletingId(entry.id); setError("");
    try {
      await circumferenceApi.remove(entry.id);
      setData(previous => previous ? { ...previous, entries: previous.entries.filter(item => item.id !== entry.id) } : previous);
      setNotice("Messung gelöscht.");
      await load(undefined, "Die Messung wurde gelöscht.");
    } catch (error) { setError(errorMessage(error)); }
    finally { setDeletingId(null); }
  }

  if (!data || !bounds) return <section className={styles.root} aria-label="Körpermaße"><div className={styles.loadingCard}><h2>Körpermaße</h2>{loading ? <p role="status">Körpermaße werden geladen …</p> : <><p className={styles.error} role="alert">{error}</p><button type="button" className={styles.secondary} onClick={() => void load()}>Erneut versuchen</button></>}</div></section>;

  const busy = loading || preferenceBusy || deletingId != null;
  const visible = data.preferences.visible_keys.map(key => stats.find(stat => stat.key === key)).filter((stat): stat is MeasurementStats => !!stat);
  const current = visible.find(stat => stat.key === selected) || visible[0];
  const allCurrent = data.definitions.find(definition => definition.key === selected) || current;
  const rows = visible.map(stat => <MeasureRow key={stat.key} stat={stat} bounds={bounds} active={stat.key === current.key} onSelect={() => setSelected(stat.key)} />);
  const figure = <div className={styles.figurePanel}><BodyDiagram definitions={visible} active={current.key} onSelect={setSelected} /><div className={styles.figureCaption}><strong style={{ color: current.color }}>{current.name}</strong><span>{current.site}</span><button type="button" className={styles.textButton} onClick={() => { setSelected(current.key); setGuideOpen(true); }}>So misst du ↗</button></div></div>;

  return <section className={styles.root} aria-label="Körpermaße">
    <header className={styles.header}><div><h2>Körpermaße</h2><p>Dein Verlauf. Einmal pro Woche.</p></div><button type="button" className={styles.primary} disabled={busy} onClick={() => setEntry({})}>＋ Messung</button></header>
    {error && <div className={styles.errorBar} role="alert"><span>{error}</span><button type="button" className={styles.textButton} disabled={loading} onClick={() => void load()}>Erneut laden</button></div>}
    <div className={styles.card} aria-busy={busy}>
      <div className={styles.toolbar}><div className={styles.segmented} aria-label="Zeitraum">{PERIODS.map(([period, label]) => <button key={period} type="button" aria-pressed={data.preferences.period === period} disabled={busy} onClick={() => changePreferences({ period })}>{label}</button>)}</div><span className={styles.periodRange}>{measurementDate(bounds.start, true)} – {measurementDate(bounds.end, true)}</span><button type="button" className={styles.textButton} disabled={busy} onClick={() => setConfigOpen(true)}>Anzeige ändern ⚙</button></div>
      <div className={styles.viewBar}><div className={`${styles.segmented} ${styles.subtle}`} aria-label="Ansicht"><button type="button" aria-pressed={data.preferences.layout === "rows"} disabled={busy} onClick={() => changePreferences({ layout: "rows" })}>Zeilen</button><button type="button" aria-pressed={data.preferences.layout === "atlas"} disabled={busy} onClick={() => changePreferences({ layout: "atlas" })}>Körperatlas</button></div>{loading && <span className={styles.note} role="status">Aktualisieren …</span>}</div>
      <div className={styles.view}>{data.preferences.layout === "rows" ? <div className={styles.rows}>{figure}<div className={styles.rowsList}><div className={styles.rowsLegend}><span>Maß & Verlauf</span><span>Start → zuletzt · Veränderung</span></div>{rows}</div></div> : <div className={styles.atlas}><div className={styles.atlasSide}>{rows.slice(0, Math.ceil(rows.length / 2))}</div>{figure}<div className={styles.atlasSide}>{rows.slice(Math.ceil(rows.length / 2))}</div></div>}</div>
      <div className={styles.cardFoot}><span>Eigene cm-Skala je Verlauf · Δ = erster → letzter Wert im Zeitraum</span><span>Markierung oder Maß anklicken</span></div>
    </div>
    <details className={styles.journal} open={journalOpen} onToggle={event => setJournalOpen(event.currentTarget.open)}>
      <summary><span>Messjournal <small>{data.entries.length} {data.entries.length === 1 ? "Eintrag" : "Einträge"}</small></span><span className={styles.summaryHint}>Werte & Monatsansicht</span></summary>
      <div className={styles.journalToolbar}><div className={styles.segmented}><button type="button" aria-pressed={journalMode === "entries"} onClick={() => setJournalMode("entries")}>Messungen</button><button type="button" aria-pressed={journalMode === "months"} onClick={() => setJournalMode("months")}>Monate</button></div><button type="button" className={styles.textButton} disabled={busy} onClick={() => setEntry({ historical: true })}>＋ Frühere Messung</button></div>
      {journalMode === "entries" ? <div className={styles.tableScroll}><table><thead><tr><th scope="col">Datum</th>{data.definitions.map(definition => <th key={definition.key} scope="col">{definition.name}<small>cm</small></th>)}<th scope="col"><span className={styles.srOnly}>Aktionen</span></th></tr></thead><tbody>
        {data.entries.map(item => <tr key={item.id}><td>{measurementDate(item.date, true)}{item.protocol === "unknown" && <small>Messstelle unbekannt</small>}</td>{data.definitions.map(definition => <td key={definition.key}>{formatCm(item.values[definition.key])}</td>)}<td className={styles.entryActions}><button type="button" className={styles.textButton} disabled={busy} onClick={() => setEntry({ entry: item })} aria-label={`Messung vom ${measurementDate(item.date, true)} bearbeiten`}>Bearbeiten</button><button type="button" className={styles.deleteButton} disabled={busy} onClick={() => void remove(item)} aria-label={`Messung vom ${measurementDate(item.date, true)} löschen`}>{deletingId === item.id ? "Löschen …" : "Löschen"}</button></td></tr>)}
        {!data.entries.length && <tr><td colSpan={data.definitions.length + 2} className={styles.emptyTable}>Noch keine Messungen. Neue und ältere Werte kannst du hier eintragen.</td></tr>}
      </tbody></table></div> : <><p className={styles.journalNote}>Letzter vergleichbarer Messwert je Monat im gewählten Zeitraum. Δ zum ersten Messwert; unbekannte Messstellen bleiben ausgeklammert.</p><div className={styles.tableScroll}><table><thead><tr><th scope="col">Monat</th>{visible.map(stat => <th key={stat.key} scope="col">{stat.name}<small>cm · Δ zum Start</small></th>)}</tr></thead><tbody>{measurementMonths(visible, bounds).map(month => <tr key={month.month}><td>{month.label}</td>{month.values.map(value => <td key={value.key}>{formatCm(value.point?.value)}{value.point && <small>{measurementDate(value.point.date)} · {value.delta == null ? "Startwert" : `${signedCm(value.delta)} cm`}</small>}</td>)}</tr>)}</tbody></table></div></>}
    </details>
    <details className={styles.method}><summary>Messroutine & Hinweise</summary><p>Einmal pro Woche unter ähnlichen Bedingungen messen, ohne Trainings-Pump. Das Band liegt an, ohne einzuschneiden. Messstelle, Körperseite und Haltung beibehalten. Bauch und Taille nach normalem Ausatmen ablesen.</p><p>Die Kurven zeigen Umfangsänderungen. Daraus lässt sich kein exakter Körperfettanteil oder Muskelzuwachs berechnen. Einzelne Schwankungen können auch durch Verdauung, Flüssigkeit oder die Messweise entstehen.</p></details>
    {entry && <EntryDialog data={data} entry={entry.entry} historical={entry.historical} measure={current.key} onClose={() => setEntry(null)} onSaved={entrySaved} />}
    {configOpen && <PreferencesDialog data={data} onClose={() => setConfigOpen(false)} onSave={savePreferences} />}
    {guideOpen && <Dialog title="Deine Messstelle" onClose={() => setGuideOpen(false)}><div className={styles.dialogContent}><label className={styles.guideSelect}>Maß<select value={allCurrent.key} onChange={event => setSelected(event.target.value as MeasureKey)}>{data.definitions.map(definition => <option key={definition.key} value={definition.key}>{definition.name} · {definition.site}</option>)}</select></label><Guide definition={allCurrent} /></div><div className={styles.dialogActions}><button type="button" className={styles.primary} onClick={() => setGuideOpen(false)}>Verstanden</button></div></Dialog>}
    {notice && <p className={styles.notice} role="status">{notice}</p>}
  </section>;
}
