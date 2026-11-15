import { useState } from "react";
import { postJSON } from "../api";

/** Make a bot (Fable's design): one field, "What should it do?". The chief drafts the bot (name, role, instructions,
 * powers) in a conversation of its own, and you check it there or in the bot's details. */
export function NewBotSheet({ onClose }: { onClose: () => void }) {
  const [what, setWhat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function make() {
    const said = what.trim();
    if (!said) return;
    setBusy(true); setError("");
    try {
      const { id } = await postJSON<{ id: string }>("/api/bots/chief/conversations", {});
      const ask = `Make me a new bot: ${said}`;  // the chief knows how (make_bot); its answer gets a "Meet …" chip
      await postJSON(`/api/conversations/${id}/messages`, { text: ask });
      location.hash = `#bot/chief/${id}`;
      onClose();
    } catch {
      setError("Couldn't ask the chief. Try again.");
      setBusy(false);
    }
  }
  return (
    <div className="fixed inset-0 z-50 flex items-end lg:items-center justify-center bg-overlay" onClick={onClose}>
      <div className="glass glass-solid w-full max-w-[520px] rounded-t-[28px] lg:rounded-[28px] p-5 flex flex-col gap-3" onClick={(e) => e.stopPropagation()}>
        <div className="text-[18px] font-bold">Make a bot</div>
        <div className="text-[13.5px] text-muted">Say what it should do. The chief writes its name, role and instructions; you can change any of it after.</div>
        <textarea autoFocus value={what} onChange={(e) => setWhat(e.target.value)} placeholder="Follow my stocks every morning and tell me what moved"
          className="min-h-[96px] rounded-[16px] border border-line-2 bg-transparent px-3 py-2.5 text-[15px]" maxLength={600} />
        <div className="flex flex-wrap gap-2">
          {["Follow my stocks every morning", "Review my code changes", "Plan weekend trips"].map((x) => (
            <button key={x} onClick={() => setWhat(x)} className="chip chip-soft">{x}</button>
          ))}
        </div>
        {error && <div className="text-[13px] text-ember-text">{error}</div>}
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="pill h-11 px-4">Cancel</button>
          <button disabled={busy || !what.trim()} onClick={() => void make()} className="h-11 px-5 rounded-[14px] bg-ember text-on-ember font-semibold disabled:opacity-50">Ask the chief</button>
        </div>
      </div>
    </div>
  );
}
