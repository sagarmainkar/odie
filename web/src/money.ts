import type { IconName } from "./components/Tile";
import { userLocale } from "./locale";

export type Account = {
  key: string; institution: string; type: string; last4: string; label: string | null;
  balance: number | null; available_limit: number | null; balance_as_of: string | null; currency?: string;
  month_out: number; month_in: number; last_month_out: number; txn_count: number; last_txn: string | null;
};
export type Txn = { date: string; direction: "debit" | "credit"; amount: number; currency: string; counterparty: string | null; category: string | null };
export type Detail = Account & { transactions: Txn[]; by_category: { category: string; amount: number }[]; top_merchants: { name: string; amount: number; count: number }[] };
export type Overview = { available: boolean; accounts: Account[]; summary: { total_balance: number; month_out: number; month_in: number; last_month_out: number } | null };

/** ₹1,85,300 (Indian grouping, no paise for big amounts); other currencies keep their symbol. */
export function money(v: number, currency = "INR"): string {
  const sym = currency === "INR" ? "₹" : currency === "USD" ? "$" : currency === "EUR" ? "€" : `${currency} `;
  const abs = Math.abs(v);
  const n = abs.toLocaleString(currency === "INR" ? "en-IN" : "en-US", { maximumFractionDigits: abs >= 1000 ? 0 : 2, minimumFractionDigits: abs >= 1000 || Number.isInteger(abs) ? 0 : 2 });
  return `${v < 0 ? "-" : ""}${sym}${n}`;
}

// Bank badges: the bank's colours and a short monogram (no logo images: they'd be hotlinked and copyrighted).
const BANKS: [RegExp, string, string, string][] = [
  [/hdfc/i, "HDFC", "#0b3d91", "#1f63c6"], [/icici/i, "ICICI", "#ae2c2b", "#f28a2e"], [/\bsbi\b|state bank/i, "SBI", "#1d3f9b", "#22a7e0"],
  [/axis/i, "AXIS", "#7a1240", "#b5245f"], [/kotak/i, "KOTAK", "#c1121f", "#ee3b44"], [/cosmos/i, "COSMOS", "#0f5b4b", "#1f9c7f"],
  [/yes bank/i, "YES", "#0b4fa0", "#2f86d8"], [/idfc/i, "IDFC", "#8f1d2c", "#c63a46"], [/indusind/i, "INDUS", "#7b2b1c", "#b8582f"],
  [/amex|american express/i, "AMEX", "#0d5ea8", "#3d8fd8"], [/bank of baroda|\bbob\b/i, "BOB", "#c4521c", "#f0873f"],
];

export function bankStyle(institution: string): { mono: string; from: string; to: string } {
  const hit = BANKS.find(([re]) => re.test(institution));
  if (hit) return { mono: hit[1], from: hit[2], to: hit[3] };
  const mono = institution.replace(/bank|ltd|limited/gi, "").trim().split(/\s+/)[0]?.slice(0, 5).toUpperCase() || "BANK";
  return { mono, from: "#3e3a6e", to: "#7d6fd8" };
}

export function typeLabel(type: string): string {
  return { savings: "Savings", current: "Current", credit_card: "Credit card", loan: "Loan", wallet: "Wallet" }[type] ?? type.replace(/_/g, " ");
}

const CAT: Record<string, IconName> = {
  groceries: "food", food: "food", dining: "food", travel: "plane", fuel: "flame", shopping: "photo", subscriptions: "refresh",
  investment: "chart", transfer: "send", bills: "bell", utilities: "bell", health: "heart", entertainment: "star", rent: "bed",
};
export function categoryIcon(cat: string | null): IconName { return CAT[cat ?? ""] ?? "rupee"; }

/** Transactions grouped by day, newest first, with a friendly label. */
export function byDay(txns: Txn[], today: string): { label: string; items: Txn[] }[] {
  const yest = new Date(Date.parse(today) - 86400000).toISOString().slice(0, 10);
  const out: { label: string; items: Txn[] }[] = [];
  for (const t of txns) {
    const label = t.date === today ? "Today" : t.date === yest ? "Yesterday"
      : new Date(t.date + "T00:00:00").toLocaleDateString(userLocale(), { weekday: "short", day: "numeric", month: "short" });
    if (out.at(-1)?.label === label) out.at(-1)!.items.push(t); else out.push({ label, items: [t] });
  }
  return out;
}

/** "▲ 23% vs last month" for spending; "" when there's nothing to compare. */
export function vsLastMonth(now: number, last: number): string {
  if (!last) return "";
  const pct = Math.round(((now - last) / last) * 100);
  return pct === 0 ? "same as last month" : `${pct > 0 ? "▲" : "▼"} ${Math.abs(pct)}% vs last month`;
}
