import { usePersona } from "../persona";
import { Orb } from "./Orb";
import { Icon } from "./Tile";

/** Today's way into Chat: a floating frosted bar with the orb, like a message field. On a desktop it centres under Today's
 *  column, beside the 84px rail (half of it: 42px), and is a little wider. */
export function AskBar({ pending }: { pending: number }) {
  const { name } = usePersona();
  return (
    <a href="#chat" className="glass fixed left-1/2 lg:left-[calc(50%+42px)] -translate-x-1/2 bottom-[max(env(safe-area-inset-bottom),14px)] w-[calc(100%-28px)] max-w-[452px] lg:max-w-[560px] z-20 h-[62px] rounded-full pl-2.5 pr-2 flex items-center gap-3 text-[16px] text-muted active:scale-[.98] transition-transform">
      <Orb size={40} />
      <span className="flex-1 min-w-0 truncate">Ask {name} anything</span>
      {pending > 0 && <span className="chip chip-warn">{pending} waiting</span>}
      <span className="w-[46px] h-[46px] rounded-full grid place-items-center bg-solid text-on-solid"><Icon name="mic" size={20} /></span>
    </a>
  );
}
