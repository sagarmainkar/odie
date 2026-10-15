import { useEffect, useState } from "react";
import { getJSON } from "../api";
import { bankStyle, money, type Overview } from "../money";
import { Icon } from "./Tile";

/** Today: one line of money (total, this month's spend) with the bank badges; opens #money. Hidden without the ledger. */
export function MoneyCard() {
  const [o, setO] = useState<Overview | null>(null);
  useEffect(() => { getJSON<Overview>("/api/money").then(setO).catch(() => {}); }, []);
  if (!o?.available || !o.summary || o.accounts.length === 0) return null;
  const banks = [...new Map(o.accounts.map((a) => [bankStyle(a.institution).mono, bankStyle(a.institution)])).values()].slice(0, 4);
  return (
    <a href="#money" className="glass rounded-[26px] px-4 py-3.5 flex items-center gap-3 active:scale-[.99] transition-transform">
      <div className="flex -space-x-2 shrink-0">
        {banks.map((b) => (
          <span key={b.mono} className="w-9 h-9 rounded-full grid place-items-center text-white text-[9px] font-extrabold tracking-[.04em] border-2 border-surface-2"
            style={{ background: `linear-gradient(135deg, ${b.from}, ${b.to})` }}>{b.mono.slice(0, 4)}</span>
        ))}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[12px] font-semibold text-muted">Money</div>
        <div className="text-[17px] font-bold tabular-nums leading-tight">{money(o.summary.total_balance)}</div>
        <div className="text-[12px] text-muted truncate">↓ {money(o.summary.month_out)} spent this month · {o.accounts.length} accounts</div>
      </div>
      <span className="text-dim inline-flex rotate-180"><Icon name="back" size={16} /></span>
    </a>
  );
}
