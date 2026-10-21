import { Icon } from "./Tile";

export type Badge = { kind: "gmail" | "icloud" | "app" | string; app: string };

/** Where an item came from, as small coloured marks after its title or date: Gmail's M in red, iCloud's cloud in
 * blue, each on a white chip; any other source by its app's name. One mark per source; nothing when there are none.
 * The app's name is the mark's title (a long press or hover says "Gmail and Calendar"). */
export function SourceBadges({ badges }: { badges?: Badge[] }) {
  if (!badges?.length) return null;
  return (
    <span className="inline-flex items-center gap-1 align-middle ml-1.5" aria-label={badges.map((b) => b.app).join(", ")}>
      {badges.map((b, i) => b.kind === "gmail" ? <span key={i} title={b.app} className="badge-mark badge-gmail"><Icon name="gmail" size={12} stroke={2.4} /></span>
        : b.kind === "icloud" ? <span key={i} title={b.app} className="badge-mark badge-icloud"><Icon name="icloud" size={12} stroke={2.4} /></span>
        : <span key={i} title={b.app} className="badge-mark badge-app">{b.app}</span>)}
    </span>
  );
}
