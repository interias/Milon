"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

function latestSync(state: { last_sync: string | null }[]): string | null {
  const t = state.map((s) => s.last_sync).filter(Boolean) as string[];
  if (!t.length) return null;
  const max = t.sort().at(-1)!;
  return new Date(max).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

const NAV = [
  { href: "/", label: "Übersicht" },
  { href: "/koerper", label: "Körper" },
  { href: "/ernaehrung", label: "Ernährung" },
  { href: "/gesundheit", label: "Gesundheit" },
  { href: "/laufen", label: "Laufen" },
  { href: "/kraft", label: "Kraft" },
  { href: "/fortschritt", label: "Fortschritt" },
  { href: "/coach", label: "Coach" },
  { href: "/einstellungen", label: "Einstellungen" },
];

// Inline-SVG-Icons (lucide-Pfade, erben die Textfarbe via currentColor — keine Icon-Lib nötig).
const ICON: Record<string, React.ReactNode> = {
  "/": <><rect width="7" height="9" x="3" y="3" rx="1" /><rect width="7" height="5" x="14" y="3" rx="1" /><rect width="7" height="9" x="14" y="12" rx="1" /><rect width="7" height="5" x="3" y="16" rx="1" /></>,
  "/koerper": <><circle cx="12" cy="5" r="1" /><path d="m9 20 3-6 3 6" /><path d="m6 8 6 2 6-2" /><path d="M12 10v4" /></>,
  "/ernaehrung": <><path d="M3 2v7c0 1.1.9 2 2 2h0a2 2 0 0 0 2-2V2" /><path d="M7 2v20" /><path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7" /></>,
  "/gesundheit": <path d="M22 12h-4l-3 9L9 3l-3 9H2" />,
  "/laufen": <><path d="M4 16v-2.38C4 11.5 2.97 10.5 3 8c.03-2.72 1.49-6 4.5-6C9.37 2 10 3.8 10 5.5c0 3.11-2 5.66-2 8.68V16a2 2 0 1 1-4 0Z" /><path d="M20 20v-2.38c0-2.12 1.03-3.12 1-5.62-.03-2.72-1.49-6-4.5-6C14.63 6 14 7.8 14 9.5c0 3.11 2 5.66 2 8.68V20a2 2 0 1 0 4 0Z" /><path d="M16 17h4" /><path d="M4 13h4" /></>,
  "/kraft": <><path d="M14.4 14.4 9.6 9.6" /><path d="M18.657 21.485a2 2 0 1 1-2.829-2.828l-1.767 1.768a2 2 0 1 1-2.829-2.829l6.364-6.364a2 2 0 1 1 2.829 2.829l-1.768 1.767a2 2 0 1 1 2.828 2.829z" /><path d="m21.5 21.5-1.4-1.4" /><path d="M3.9 3.9 2.5 2.5" /><path d="M6.404 12.768a2 2 0 1 1-2.829-2.829l1.768-1.767a2 2 0 1 1-2.828-2.829l2.828-2.828a2 2 0 1 1 2.829 2.828l1.767-1.768a2 2 0 1 1 2.829 2.829z" /></>,
  "/fortschritt": <><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z" /><circle cx="12" cy="13" r="3" /></>,
  "/coach": <path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .962 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.962 0z" />,
  "/einstellungen": <><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" /><circle cx="12" cy="12" r="3" /></>,
};

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.ingestStatus().then((st) => setLast(latestSync(st.state))).catch(() => {});
  }, []);

  // Drawer bei Routenwechsel schließen
  useEffect(() => { setOpen(false); }, [path]);

  async function refresh() {
    if (busy) return;
    setBusy(true);
    try {
      await api.ingestRefresh();
      const st = await api.ingestStatus();
      setLast(latestSync(st.state));
    } catch {
      /* Refresh-Fehler nicht kritisch */
    } finally {
      setBusy(false);
    }
  }

  const brand = (
    <Link href="/" className="flex items-center gap-2.5">
      <span className="h-2.5 w-2.5 rounded-full bg-accent" />
      <span className="font-display text-lg font-extrabold tracking-tight">Milon</span>
    </Link>
  );

  const navList = (
    <nav className="flex flex-col gap-1">
      {NAV.map((n) => {
        const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
        return (
          <Link
            key={n.href}
            href={n.href}
            onClick={() => setOpen(false)}
            className={
              "flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors " +
              (active ? "bg-accent text-white" : "text-muted hover:bg-surface-alt hover:text-ink")
            }
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px] shrink-0" aria-hidden="true">
              {ICON[n.href]}
            </svg>
            {n.label}
          </Link>
        );
      })}
    </nav>
  );

  const foot = (withImg: boolean) => (
    <div className="mt-auto pt-6">
      <button
        type="button"
        onClick={refresh}
        disabled={busy}
        className="w-full rounded-lg border border-line bg-surface-alt px-3 py-2.5 text-sm font-medium text-ink hover:border-accent disabled:opacity-60"
      >
        {busy ? "synchronisiert …" : "↻ Daten aktualisieren"}
      </button>
      {last && <p className="mt-2 px-1 text-[11px] text-muted">zuletzt: {last}</p>}
      {withImg && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src="/img/run-ink-slash.png" alt="" className="mt-6 w-full opacity-90" />
      )}
    </div>
  );

  return (
    <div className="md:flex md:min-h-screen">
      {/* Mobile-Top-Bar */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-bg/90 px-4 py-3 backdrop-blur md:hidden">
        {brand}
        <button
          type="button"
          aria-label="Menü öffnen"
          onClick={() => setOpen(true)}
          className="grid h-9 w-9 place-items-center rounded-lg border border-line bg-surface text-ink"
        >
          <span className="text-lg leading-none">☰</span>
        </button>
      </header>

      {/* Mobile-Drawer */}
      {open && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} aria-hidden />
          <aside className="absolute left-0 top-0 flex h-full w-72 max-w-[85%] flex-col border-r border-line bg-surface px-5 py-5 shadow-2xl">
            <div className="mb-6 flex items-center justify-between">
              {brand}
              <button
                type="button"
                aria-label="Menü schließen"
                onClick={() => setOpen(false)}
                className="grid h-8 w-8 place-items-center rounded-lg text-muted hover:bg-surface-alt"
              >
                ✕
              </button>
            </div>
            {navList}
            {foot(false)}
          </aside>
        </div>
      )}

      {/* Desktop-Sidebar */}
      <aside className="hidden w-60 shrink-0 flex-col border-r border-line bg-surface px-5 py-6 md:flex">
        <div className="mb-8 px-2">{brand}</div>
        {navList}
        {foot(true)}
      </aside>

      <main className="flex-1 px-4 py-6 md:px-10 md:py-8">
        <div className="mx-auto max-w-[1200px]">{children}</div>
      </main>
    </div>
  );
}
