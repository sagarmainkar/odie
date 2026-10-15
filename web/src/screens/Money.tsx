import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { getJSON, todayISO } from "../api";
import { Icon } from "../components/Tile";
import { bankStyle, byDay, categoryIcon, money, typeLabel, vsLastMonth, type Account, type Detail, type Overview } from "../money";
import { userLocale } from "../locale";

const ease = [0.2, 0.8, 0.2, 1] as const;

function Card({ a, on, onTap }: { a: Account; on: boolean; onTap: () => void }) {
  const b = bankStyle(a.institution);
  const card = a.type === "credit_card";
  const main = a.balance !== null ? money(a.balance, a.currency ?? "INR") : card && a.available_limit !== null ? money(a.available_limit, a.currency ?? "INR") : null;
  return (
    <motion.button type="button" onClick={onTap} animate={{ y: on ? -6 : 0, scale: on ? 1.02 : 1 }} transition={{ duration: 0.25, ease }}
      className={`snap-center shrink-0 w-[78%] max-w-[330px] aspect-[1.62] rounded-[26px] p-4 text-left text-white relative overflow-hidden ${on ? "ring-2 ring-white/70" : ""}`}
      style={{ background: `linear-gradient(135deg, ${b.from} 0%, ${b.to} 100%)`, boxShadow: on ? "0 18px 36px -16px rgba(20,10,40,.55)" : "0 10px 24px -16px rgba(20,10,40,.45)" }}>
      <span className="absolute -right-10 -top-12 w-44 h-44 rounded-full bg-white/10" />
      <span className="absolute -right-4 bottom-[-60px] w-40 h-40 rounded-full bg-white/[.07]" />
      <div className="relative flex items-center justify-between">
        <span className="px-2.5 h-8 rounded-[10px] grid place-items-center bg-white/20 backdrop-blur-sm text-[13px] font-extrabold tracking-[.08em]">{b.mono}</span>
        <span className="text-[12px] font-semibold text-white/80">{typeLabel(a.type)}</span>
      </div>
      <div className="relative mt-5">
        <div className="text-[12px] text-white/75">{a.balance !== null ? (card ? "Outstanding" : "Balance") : card ? "Available limit" : a.institution}</div>
        <div className={`${main ? "text-[28px]" : "text-[15px] mt-1"} font-extrabold tracking-[-0.02em] tabular-nums leading-tight`}>{main ?? "Balance not in messages"}</div>
      </div>
      <div className="absolute left-4 right-4 bottom-3.5 flex items-center justify-between text-[12.5px] text-white/85">
        <span className="tracking-[.12em] tabular-nums">•• {a.last4}</span>
        <span>{a.balance_as_of ? `as of ${new Date(a.balance_as_of + "T00:00:00").toLocaleDateString(userLocale(), { day: "numeric", month: "short" })}` : a.txn_count ? `${a.txn_count} txns` : ""}</span>
      </div>
    </motion.button>
  );
}

function DetailPanel({ d }: { d: Detail }) {
  const max = Math.max(1, ...d.by_category.map((c) => c.amount));
  const ask = `Analyze my ${d.institution} ${typeLabel(d.type).toLowerCase()} ••${d.last4}: its transactions of the last 60 days. Patterns, unusual or repeating spends, subscriptions, and how this month compares with last.`;
  return (
    <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 10 }} transition={{ duration: 0.28, ease }} className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2">
        <div className="glass glass-solid rounded-[20px] px-3.5 py-3">
          <div className="text-[12px] font-semibold text-muted">Spent this month</div>
          <div className="text-[20px] font-extrabold tabular-nums">{money(d.month_out)}</div>
          {vsLastMonth(d.month_out, d.last_month_out) && <span className="chip chip-soft mt-1">{vsLastMonth(d.month_out, d.last_month_out)}</span>}
        </div>
        <div className="glass glass-solid rounded-[20px] px-3.5 py-3">
          <div className="text-[12px] font-semibold text-muted">Received</div>
          <div className="text-[20px] font-extrabold tabular-nums text-good">{money(d.month_in)}</div>
        </div>
      </div>

      {d.by_category.length > 0 && (
        <div className="glass rounded-[22px] px-4 py-3.5 flex flex-col gap-2.5">
          <div className="text-[13px] font-bold text-muted">Where it went this month</div>
          {d.by_category.map((c) => (
            <div key={c.category} className="flex items-center gap-2.5">
              <span className="w-7 h-7 rounded-[9px] grid place-items-center bg-ember-tint text-ember-text shrink-0"><Icon name={categoryIcon(c.category)} size={14} stroke={2.2} /></span>
              <div className="flex-1 min-w-0">
                <div className="flex justify-between text-[13.5px]"><span className="capitalize">{c.category}</span><span className="tabular-nums font-semibold">{money(c.amount)}</span></div>
                <div className="h-1.5 mt-1 rounded-full bg-well overflow-hidden"><div className="h-full rounded-full bg-brand chart-draw" style={{ width: `${(c.amount / max) * 100}%` }} /></div>
              </div>
            </div>
          ))}
        </div>
      )}

      {d.top_merchants.length > 1 && (
        <div className="glass rounded-[22px] px-4 py-3.5">
          <div className="text-[13px] font-bold text-muted mb-1.5">Top this month</div>
          {d.top_merchants.map((m) => (
            <div key={m.name} className="flex justify-between text-[14px] py-1"><span className="truncate pr-3">{m.name}{m.count > 1 ? <span className="text-dim"> · {m.count}×</span> : null}</span><span className="tabular-nums">{money(m.amount)}</span></div>
          ))}
        </div>
      )}

      <div className="glass rounded-[22px] overflow-hidden">
        <div className="px-4 pt-3.5 pb-1 text-[13px] font-bold text-muted">Transactions</div>
        {d.transactions.length === 0 && <div className="px-4 pb-3.5 text-[14px] text-muted">None in the messages yet.</div>}
        {byDay(d.transactions, todayISO()).map((g) => (
          <div key={g.label}>
            <div className="px-4 pt-2.5 pb-1 text-[12px] font-semibold text-dim">{g.label}</div>
            {g.items.map((t, i) => (
              <div key={i} className="flex items-center gap-3 px-4 py-2.5 border-b border-line last:border-b-0">
                <span className={`w-9 h-9 rounded-[12px] grid place-items-center shrink-0 ${t.direction === "credit" ? "bg-good-tint text-good" : "bg-well text-ink-2"}`}>
                  <Icon name={t.direction === "credit" ? "up" : categoryIcon(t.category)} size={16} stroke={2.2} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-[14.5px] font-medium truncate">{t.counterparty ?? (t.direction === "credit" ? "Credit" : "Debit")}</div>
                  <div className="text-[12px] text-muted capitalize">{t.category ?? (t.direction === "credit" ? "received" : "spent")}</div>
                </div>
                <span className={`text-[15px] font-semibold tabular-nums ${t.direction === "credit" ? "text-good" : ""}`}>{t.direction === "credit" ? "+" : "−"}{money(t.amount, t.currency)}</span>
              </div>
            ))}
          </div>
        ))}
      </div>

      <button type="button" onClick={() => { location.hash = `#chat?q=${encodeURIComponent(ask)}`; }} className="pill pill-solid h-11 self-start text-[14.5px] shadow-none">
        <Icon name="spark" size={15} /> Analyze with Odie
      </button>
      <div className="text-[11.5px] text-dim -mt-1">The view above is worked out on this computer. Analyze sends this account's transactions to your chat model.</div>
    </motion.div>
  );
}

/** #money: accounts from the SMS ledger as cards; tap one for its month, categories and transactions. */
export function Money() {
  const [o, setO] = useState<Overview | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  useEffect(() => { getJSON<Overview>("/api/money").then(setO).catch(() => setO({ available: false, accounts: [], summary: null })); }, []);
  useEffect(() => {
    setDetail(null);
    if (sel) getJSON<Detail>(`/api/money/${encodeURIComponent(sel)}`).then(setDetail).catch(() => {});
  }, [sel]);
  const s = o?.summary;
  return (
    <div className="h-full overflow-y-auto no-scrollbar safe-top flex flex-col gap-5 pb-10">
      <div className="flex items-center gap-3 px-[18px]">
        {/* A desktop has the rail for going back to Today (hidden! with "!": .pill sets its own display, which would win). */}
        <a href="#today" aria-label="Back" className="pill w-11 px-0 lg:hidden!">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 6l-6 6 6 6" /></svg>
        </a>
        <div className="text-[21px] font-bold tracking-[-0.015em]">Money</div>
      </div>
      {o && !o.available && <div className="px-[18px] text-[14px] text-muted">The message ledger isn't set up on this computer.</div>}
      {o?.available && o.accounts.length === 0 && <div className="px-[18px] text-[14px] text-muted">No accounts in your messages yet.</div>}
      {s && o!.accounts.length > 0 && (
        <div className="mx-[18px] glass rounded-[26px] px-4 py-3.5">
          <div className="text-[12px] font-semibold tracking-[.06em] uppercase text-ember-text">Across your accounts</div>
          <div className="text-[32px] leading-[38px] font-extrabold tracking-[-0.03em] tabular-nums">{money(s.total_balance)}</div>
          <div className="flex flex-wrap gap-1.5 mt-1.5">
            <span className="chip chip-soft">↓ {money(s.month_out)} spent this month</span>
            <span className="chip chip-good">↑ {money(s.month_in)} received</span>
            {vsLastMonth(s.month_out, s.last_month_out) && <span className="chip chip-soft">{vsLastMonth(s.month_out, s.last_month_out)}</span>}
          </div>
        </div>
      )}
      {o && o.accounts.length > 0 && (
        <div className="flex gap-3 overflow-x-auto no-scrollbar snap-x snap-mandatory px-[18px] pt-2 pb-3 -mb-2">
          {o.accounts.map((a) => <Card key={a.key} a={a} on={sel === a.key} onTap={() => setSel(sel === a.key ? null : a.key)} />)}
          <span className="shrink-0 w-2" />
        </div>
      )}
      <div className="px-[18px]">
        <AnimatePresence mode="wait">
          {sel && detail && detail.key === sel && <DetailPanel key={sel} d={detail} />}
          {!sel && o && o.accounts.length > 0 && (
            <motion.div key="hint" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="text-[13px] text-muted text-center">
              Tap a card for its month and transactions.
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
