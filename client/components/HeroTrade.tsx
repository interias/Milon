"use client";

import { useState } from "react";
import type { Hero } from "@/lib/api";
import { Card, CardTitle } from "@/components/ui";
import { Icon, Money, Slot, useItemTip, type Gear } from "@/components/Hero";
import { dm } from "@/lib/format";

const TIP_YELLOW = "#ffd100";
const BTN = "rounded border px-2.5 py-1 font-display text-[11px] font-bold disabled:opacity-40";
const BTN_STYLE = { background: "linear-gradient(180deg, #3b2c18, #1d150c)", borderColor: "#6b5230", color: TIP_YELLOW };
const BAG = <><path d="M6 8V6a6 6 0 0 1 12 0v2" /><path d="M4 8h16l-1.5 12.5a2 2 0 0 1-2 1.5h-9a2 2 0 0 1-2-1.5Z" /></>;

function BuyButton({ price, balance, onBuy }: { price: number; balance: number; onBuy: () => Promise<void> }) {
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const short = balance < price;
  return (
    <button type="button" disabled={busy || short} className={BTN} title={short ? "Zu wenig Gold" : undefined}
            style={confirm ? { background: "linear-gradient(180deg, #b8131a, #6e0b0f)", borderColor: "var(--wow-gold)", color: TIP_YELLOW } : BTN_STYLE}
            onClick={async () => {
              if (!confirm) { setConfirm(true); return; }
              setBusy(true);
              try { await onBuy(); } finally { setBusy(false); setConfirm(false); }
            }}>
      {confirm ? "Sicher?" : "Kaufen"}
    </button>
  );
}

// --- Auktionshaus: Wochenangebot ----------------------------------------------------------
export function HeroAuction({ data, gear, onBuy }: { data: Hero; gear: Gear; onBuy: (kind: "listing" | "potion", ref: string) => Promise<void> }) {
  const { bind, node } = useItemTip(gear);
  const a = data.auction;
  if (!a) return null;
  const balance = data.gold?.balance ?? 0;
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <CardTitle title="Auktionshaus" sub={`Neues Angebot jeden Montag · nächstes am ${dm(a.ends)} · nur einmal kaufbar`} />
        <Money copper={balance} className="text-[13px]" />
      </div>
      <div className="grid gap-2 @xl:grid-cols-2">
        {a.listings.map((l) => {
          const name = l.item?.name ?? l.bag?.name ?? l.mount?.name ?? "";
          const color = l.item ? `var(--rar-${l.item.rarity})` : l.mount ? "var(--rar-orange)" : "#fff";
          return (
            <div key={l.idx} className="flex min-w-0 items-center gap-2.5 rounded-md border border-[#2c2216] bg-black/25 p-2"
                 style={{ opacity: l.sold ? 0.45 : 1 }}>
              {l.item ? <Slot item={l.item} bind={bind(l.item)} />
                : <span className="wow-slot shrink-0 text-xl" style={{ color: TIP_YELLOW }}>{l.mount ? l.mount.glyph : <Icon size={22}>{BAG}</Icon>}</span>}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-semibold" style={{ color }}>{name}</span>
                <span className="block truncate text-[11px] text-muted">
                  {l.item ? `${l.item.slot_label} · Stufe ${l.item.ilvl} · ${l.item.rarity_label}` : l.bag ? `Tasche · ${l.bag.slots} Plätze` : "Reittier · nur im Auktionshaus"}
                </span>
                <Money copper={l.price} className="text-[12px]" />
              </span>
              {l.sold ? <span className="shrink-0 text-[11px] text-muted">verkauft</span>
                : <BuyButton price={l.price} balance={balance} onBuy={() => onBuy("listing", String(l.idx))} />}
            </div>
          );
        })}
      </div>
      {node}
    </Card>
  );
}

// --- Tränke -------------------------------------------------------------------------------
export function HeroPotions({ data, onBuy, onDrink }: { data: Hero; onBuy: (kind: "listing" | "potion", ref: string) => Promise<void>; onDrink: (key: string) => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  if (!data.potions?.length) return null;
  const balance = data.gold?.balance ?? 0;
  return (
    <Card>
      <CardTitle title="Tränke" sub="Getrunken wirkt ein Trank für heute · jede Sorte einmal am Tag · gezielt vor einem Lauf" />
      <div className="space-y-2">
        {data.potions.map((p) => (
          <div key={p.key} className="flex flex-wrap items-center gap-2.5 rounded-md border border-[#2c2216] bg-black/25 p-2">
            <span className="wow-slot shrink-0 text-xl" style={p.active_today ? { borderColor: "#1eff00", boxShadow: "0 0 8px #1eff00" } : undefined}>{p.glyph}</span>
            <span className="min-w-0 flex-1">
              <span className="block text-[13px] font-semibold" style={{ color: "#1eff00" }}>{p.name} <span className="font-normal text-muted">× {p.count}</span></span>
              <span className="block text-[11px] text-white">{p.effect}</span>
              <Money copper={p.price} className="text-[12px]" />
            </span>
            <span className="flex shrink-0 gap-1.5">
              <BuyButton price={p.price} balance={balance} onBuy={() => onBuy("potion", p.key)} />
              <button type="button" disabled={busy != null || p.count < 1 || p.active_today} className={BTN}
                      style={{ ...BTN_STYLE, color: "#1eff00" }}
                      onClick={async () => { setBusy(p.key); try { await onDrink(p.key); } finally { setBusy(null); } }}>
                {p.active_today ? "wirkt heute" : "Trinken"}
              </button>
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}
