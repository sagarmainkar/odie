import { Icon } from "./Tile";

export type Badge = { kind: "gmail" | "icloud" | "app" | string; app: string };

/** Where an item came from, as small marks after its title: Gmail's M, iCloud's cloud, or the app's name for anything
 * else. One mark per source; nothing when there are none. */
export function SourceBadges({ badges }: { badges?: Badge[] }) {
  if (!badges?.length) return null;
  return (
    <span className="inline-flex items-center gap-1 align-middle ml-1.5 text-muted" aria-label={badges.map((b) => b.app).join(", ")}>
      {badges.map((b, i) => b.kind === "gmail" ? <span key={i} title={b.app}><Icon name="gmail" size={13} stroke={2} /></span>
        : b.kind === "icloud" ? <span key={i} title={b.app}><Icon name="icloud" size={14} stroke={2} /></span>
        : <span key={i} className="text-[10.5px] font-semibold uppercase tracking-[0.04em]">{b.app}</span>)}
    </span>
  );
}
