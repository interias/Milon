// Trainings-Konsistenz als GitHub-Style-Heatmap: Spalten = Wochen (Mo–So), Farbe = Level,
// Monatslabels darüber zur Orientierung. Horizontal scrollbar bei langem Zeitraum.
import type { ConsistencyDay } from "@/lib/api";

const COLORS = ["var(--color-line)", "rgba(10,110,102,0.30)", "rgba(10,110,102,0.60)", "#0a6e66"];
const MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];

export function Heatmap({ days }: { days: ConsistencyDay[] }) {
  if (!days.length) return null;
  const first = new Date(days[0].date + "T00:00:00");
  const lead = (first.getDay() + 6) % 7; // Montag = 0
  const cells: (ConsistencyDay | null)[] = [...Array(lead).fill(null), ...days];
  const weeks: (ConsistencyDay | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));

  // Monatslabel je Woche-Spalte (nur wo ein neuer Monat beginnt)
  let lastMonth = -1;
  const monthLabels = weeks.map((w) => {
    const d = w.find(Boolean);
    if (!d) return "";
    const m = new Date(d.date + "T00:00:00").getMonth();
    if (m !== lastMonth) { lastMonth = m; return MONTHS[m]; }
    return "";
  });

  return (
    <div>
      <div className="overflow-x-auto pb-1">
        <div className="inline-flex flex-col gap-[3px]">
          <div className="flex gap-[3px]">
            {monthLabels.map((lbl, i) => (
              <div
                key={i}
                className="h-3 w-3 shrink-0 text-[10px] leading-3 text-muted"
                style={{ overflow: "visible", whiteSpace: "nowrap" }}
              >
                {lbl}
              </div>
            ))}
          </div>
          <div className="flex gap-[3px]">
            {weeks.map((w, wi) => (
              <div key={wi} className="flex flex-col gap-[3px]">
                {Array.from({ length: 7 }).map((_, di) => {
                  const c = w[di];
                  const title = c
                    ? `${c.date}: ${c.trained ? "Training" : c.steps ? `${c.steps.toLocaleString("de-DE")} Schritte` : "frei"}`
                    : "";
                  return (
                    <div
                      key={di}
                      title={title}
                      className="h-3 w-3 shrink-0 rounded-[3px]"
                      style={{ background: c ? COLORS[c.level] : "transparent" }}
                    />
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-2 flex items-center gap-1.5 text-[10px] text-muted">
        <span>weniger</span>
        {COLORS.map((c, i) => <span key={i} className="h-3 w-3 rounded-[3px]" style={{ background: c }} />)}
        <span>mehr · Training = volle Farbe</span>
      </div>
    </div>
  );
}
