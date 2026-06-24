import React from "react";

export function PageTitle({ title, sub }: { title: string; sub?: string }) {
  return (
    <header className="mb-6">
      <h1 className="font-display text-2xl font-extrabold tracking-tight">{title}</h1>
      {sub && <p className="mt-1 text-sm text-muted">{sub}</p>}
    </header>
  );
}

export function Card({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={`rounded-card border border-line bg-surface p-4 shadow-[0_1px_2px_rgba(20,32,31,0.04)] sm:p-5 ${className}`}>
      {children}
    </div>
  );
}

export function CardTitle({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="mb-3">
      <h3 className="text-sm font-semibold">{title}</h3>
      {sub && <p className="text-[11px] text-muted">{sub}</p>}
    </div>
  );
}

export function Kpi(props: {
  label: string;
  sub?: string;
  value: React.ReactNode;
  unit?: string;
  delta?: string;
  deltaKind?: "good" | "bad" | "muted";
  watermark?: string;
  children?: React.ReactNode;
}) {
  const { label, sub, value, unit, delta, deltaKind = "good", watermark, children } = props;
  const deltaCls = deltaKind === "bad" ? "text-bad" : deltaKind === "muted" ? "text-muted" : "text-good";
  return (
    <div className="relative overflow-hidden rounded-card border border-line bg-surface p-4 shadow-[0_1px_2px_rgba(20,32,31,0.04)] sm:p-5">
      {watermark && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={watermark} alt="" className="pointer-events-none absolute -bottom-5 -right-4 w-28 opacity-[0.06]" />
      )}
      <div className="relative">
        <div className="text-sm font-semibold">{label}</div>
        {sub && <div className="text-[11px] text-muted">{sub}</div>}
        <div className="mt-2 flex items-baseline gap-1.5">
          <span className="font-display text-3xl font-extrabold tracking-tight">{value}</span>
          {unit && <span className="text-sm font-semibold text-muted">{unit}</span>}
        </div>
        {delta && <span className={`text-xs font-bold ${deltaCls}`}>{delta}</span>}
        {children}
      </div>
    </div>
  );
}

export function StatRow({ items }: { items: [string, React.ReactNode][] }) {
  return (
    <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 border-t border-line pt-3 text-xs text-muted sm:flex sm:justify-between">
      {items.map(([k, v], i) => (
        <span key={i}>
          {k} <b className="text-ink">{v}</b>
        </span>
      ))}
    </div>
  );
}

export function Loading() {
  return <div className="text-sm text-muted">lädt …</div>;
}

export function ApiError({ error }: { error: string }) {
  return (
    <Card className="border-bad/30">
      <p className="text-sm font-semibold text-bad">Backend nicht erreichbar</p>
      <p className="mt-1 text-xs text-muted">
        {error}. Läuft der Server auf <code>:8000</code>? (Task „Server: FastAPI (Dev)")
      </p>
    </Card>
  );
}
