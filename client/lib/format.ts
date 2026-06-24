// Deutsche Zahlenformatierung.
export const de = (n: number | null | undefined, d = 1): string =>
  n == null ? "–" : n.toLocaleString("de-DE", { minimumFractionDigits: d, maximumFractionDigits: d });

export const de0 = (n: number | null | undefined): string =>
  n == null ? "–" : Math.round(n).toLocaleString("de-DE");

export const pace = (p: number | null | undefined): string => {
  if (!p) return "–";
  const m = Math.floor(p);
  const s = Math.round((p - m) * 60);
  return `${m}:${String(s).padStart(2, "0")}`;
};

// Kürzt ISO-Datum auf TT.MM.
export const dm = (iso: string): string => {
  const d = new Date(iso);
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}.`;
};

// Ist das (lokale) Datum heute? Vergleich über die lokale Kalenderdatum-Zeichenkette
// (vermeidet UTC-Verschiebung von toISOString nahe Mitternacht).
export const isToday = (iso: string | null | undefined): boolean => {
  if (!iso) return false;
  const n = new Date();
  const local = `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, "0")}-${String(n.getDate()).padStart(2, "0")}`;
  return iso.slice(0, 10) === local;
};
