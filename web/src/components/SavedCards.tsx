import { useCallback, useEffect, useState } from "react";
import { userLocale } from "../locale";
import { sinceText, type SavedCard } from "../signin";
import { Tile } from "./Tile";

type Adding = { number: string; expiry: string; name: string; label: string };
const EMPTY: Adding = { number: "", expiry: "", name: "", label: "" };

/** Settings → Browser → Saved cards (odie/signin/wallet.py): kept in this Mac's Keychain, listed as "Visa •••• 4242".
 * On a payment page, the page view's card button types one in; the user types the CVV and the bank's OTP. */
export function SavedCards() {
  const [cards, setCards] = useState<SavedCard[]>([]);
  const [adding, setAdding] = useState<Adding | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const call = useCallback(async (url: string, method: string, body?: unknown) => {
    setBusy(true); setError("");
    try {
      const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) { setError(data.detail || "That didn't work. Try again."); return false; }
      setCards(data.cards ?? []);
      return true;
    } catch {
      setError("Odie didn't answer. Try again.");
      return false;
    } finally { setBusy(false); }
  }, []);
  useEffect(() => { void call("/api/wallet/cards", "GET"); }, [call]);

  const save = async () => { if (adding && await call("/api/wallet/cards", "POST", adding)) setAdding(null); };
  const remove = (c: SavedCard) => { if (confirm(`Delete ${c.label}? It's removed from this Mac's Keychain.`)) void call(`/api/wallet/cards/${c.id}`, "DELETE"); };
  const field = "h-11 rounded-full bg-well px-4 text-body outline-none";

  return (
    <>
      <div className="px-4 pt-3 pb-1 text-small font-semibold text-muted">Saved cards</div>
      {cards.map((c) => (
        <div key={c.id} className="flex items-center gap-3 px-4 py-3 min-h-14 border-b border-line">
          <Tile icon="rupee" color="green" small />
          <div className="flex-1 min-w-0">
            <div className="text-body leading-5 font-medium truncate">{c.label}</div>
            <div className="text-small leading-[18px] text-muted truncate">Expires {c.expiry} · {c.last_used ? `used ${sinceText(c.last_used, userLocale())}` : `saved ${sinceText(c.saved_at, userLocale())}`}</div>
          </div>
          <button disabled={busy} onClick={() => remove(c)} className="text-ui font-semibold text-warn-ink shrink-0 h-11 px-1">Delete</button>
        </div>
      ))}
      {adding ? (
        <form className="px-4 py-3 flex flex-col gap-2 border-b border-line" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <input value={adding.number} onChange={(e) => setAdding({ ...adding, number: e.target.value })} placeholder="Card number" aria-label="Card number"
            inputMode="numeric" autoComplete="cc-number" className={field} />
          <div className="flex gap-2">
            <input value={adding.expiry} onChange={(e) => setAdding({ ...adding, expiry: e.target.value })} placeholder="MM/YY" aria-label="Expiry"
              inputMode="numeric" autoComplete="cc-exp" className={`${field} w-28 min-w-0`} />
            <input value={adding.name} onChange={(e) => setAdding({ ...adding, name: e.target.value })} placeholder="Name on card" aria-label="Name on card"
              autoComplete="cc-name" className={`${field} flex-1 min-w-0`} />
          </div>
          <input value={adding.label} onChange={(e) => setAdding({ ...adding, label: e.target.value })} placeholder="Its name in Odie (optional)" aria-label="Card name"
            autoComplete="off" className={field} />
          <div className="flex gap-2">
            <button disabled={busy || !adding.number.trim() || !adding.expiry.trim()} className="pill pill-solid h-10 text-ui shadow-none disabled:opacity-40">Save</button>
            <button type="button" onClick={() => { setAdding(null); setError(""); }} className="pill h-10 text-ui shadow-none">Cancel</button>
          </div>
          <div className="text-small leading-[18px] text-muted">Kept in this Mac's Keychain, without the CVV. On a payment page, tap the card button and Odie's browser types it in; the AI only ever sees the last four digits. You type the CVV and the bank's OTP.</div>
        </form>
      ) : (
        <button disabled={busy} onClick={() => setAdding(EMPTY)} className="w-full flex items-center gap-3 px-4 py-3 min-h-14 border-b border-line text-left active:bg-well">
          <Tile icon="plus" color="green" small />
          <span className="flex-1 text-body font-medium">Add a card</span>
        </button>
      )}
      {error && <div className="px-4 py-2 text-small text-warn-ink border-b border-line">{error}</div>}
    </>
  );
}
