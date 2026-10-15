import { useCallback, useEffect, useState } from "react";
import type { OrbState } from "./components/Orb";
import { Chat } from "./screens/Chat";
import { Settings } from "./screens/Settings";
import { Brain } from "./screens/Brain";
import { SampleChat } from "./screens/SampleChat";
import { Money } from "./screens/Money";
import { Today } from "./screens/Today";
import { Setup } from "./screens/Setup";
import { Private } from "./screens/Private";
import { Wash } from "./components/Wash";
import { AskBar } from "./components/AskBar";
import { Rail } from "./components/Rail";
import { ReminderCurtain } from "./components/ReminderCurtain";
import { getJSON } from "./api";
import { useLive } from "./live";
import { useProfile } from "./profile";
import { usePersona } from "./persona";
import { has, tabFor, useCaps } from "./capabilities";
import { useUpdate } from "./update";
import { PRIVATE_EVENT, codeFromHash, needsPairing, type PairStatus } from "./devices";
import { columnWidth, showsRail } from "./layout";

export type Tab = "chat" | "today" | "settings" | "brain" | "sample" | "money" | "setup";

function tabFromHash(): Tab {
  const h = location.hash.replace("#", "").split("?")[0];
  return h === "chat" || h === "settings" || h === "brain" || h === "sample" || h === "money" || h === "setup" ? (h as Tab) : "today";
}

/** While pairing is on, a browser that isn't paired sees only the Private screen (nothing else mounts, so nothing
 * else asks the server). An API that answers "private" later (this browser was removed) brings it back. A pairing
 * link pairs this browser even while pairing is off, so it is ready when pairing goes on. */
export default function App() {
  const [status, setStatus] = useState<PairStatus | null | undefined>(undefined);  // undefined: not asked yet
  const [locked, setLocked] = useState(false);
  useEffect(() => {
    getJSON<PairStatus>("/api/pair/status").then((s) => { setStatus(s); setLocked(needsPairing(s) || (!s.paired && !!codeFromHash(location.hash))); }).catch(() => setStatus(null));
    const on = () => setLocked(true);
    window.addEventListener(PRIVATE_EVENT, on);
    return () => window.removeEventListener(PRIVATE_EVENT, on);
  }, []);
  if (status === undefined) return <div className="h-full"><Wash /></div>;
  if (locked) return <div className="h-full flex flex-col text-ink max-w-[520px] mx-auto"><Wash /><div className="flex-1 min-h-0"><Private status={status} /></div></div>;
  return <Main />;
}

function Main() {
  const [hashTab, setTab] = useState<Tab>(tabFromHash());
  const caps = useCaps();
  const [setupDone, setSetupDone] = useState(true);
  useEffect(() => { getJSON<{ done: boolean }>("/api/setup").then((s) => setSetupDone(s.done)).catch(() => {}); }, []);
  // A new install opens on Setup (Settings and Brain stay reachable, to do a step by hand).
  const wanted = !setupDone && hashTab !== "settings" && hashTab !== "brain" ? "setup" : hashTab;
  const tab = tabFor(wanted, caps);  // a tab for something this install doesn't have opens Today
  const [orb, setOrb] = useState<OrbState>("idle");
  const [pending, setPending] = useState(0);
  useProfile();  // early, so the locale is remembered before most screens draw
  const persona = usePersona();
  useEffect(() => { document.title = persona.name; }, [persona.name]);
  // Once an hour, and on coming back to the app: is a newer Odie on origin? (Only the installed copy can update.)
  const update = useUpdate(has(caps, "update") && caps !== null);
  const loadPending = useCallback(() => {
    getJSON<unknown[]>("/api/approvals").then((a) => setPending(a.length)).catch(() => {});
  }, []);
  useEffect(() => {
    const on = () => setTab(tabFromHash());
    window.addEventListener("hashchange", on);
    loadPending();
    return () => window.removeEventListener("hashchange", on);
  }, [loadPending]);
  // The Ask bar shows approvals waiting in Chat.
  useLive(useCallback((e: { type: string }) => { if (e.type === "approval" || e.type === "approval_done") loadPending(); }, [loadPending]), loadPending);
  // On a phone and a tablet: one centred column. On a desktop (lg): the rail of tabs, then the column (layout.ts).
  return (
    <div className="h-full lg:flex text-ink">
      <Wash />
      {showsRail(tab) && <Rail tab={tab} caps={caps} pending={pending} orb={orb} updateReady={!!update.info?.behind} />}
      <div className={`h-full flex flex-col mx-auto w-full lg:flex-1 lg:min-w-0 ${columnWidth(tab)}`}>
        <div className="flex-1 min-h-0">
          {/* Chat stays mounted so a streaming answer survives a trip to Today. */}
          <div className={tab === "chat" ? "h-full" : "hidden"}><Chat orb={orb} setOrb={setOrb} /></div>
          {tab === "today" && <Today />}
          {tab === "settings" && <Settings />}
          {tab === "brain" && <Brain />}
          {tab === "sample" && <SampleChat />}
          {tab === "money" && <Money />}
          {tab === "setup" && <Setup />}
        </div>
      </div>
      {tab === "today" && <AskBar pending={pending} />}
      <ReminderCurtain />
    </div>
  );
}
