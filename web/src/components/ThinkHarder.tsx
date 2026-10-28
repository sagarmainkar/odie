import { Icon as Glyph, Tile } from "./Tile";

/** By the composer while this chat thinks harder, so it shows without opening the + menu. A tap opens the menu (its
 * switch turns it off). Off: nothing. */
export function ThinkChip({ on, onTap }: { on: boolean; onTap: () => void }) {
  if (!on) return null;
  return (
    <button type="button" onClick={onTap} aria-label="Think harder is on for this chat" className="pill pill-flat h-[42px] text-[14px]">
      <Glyph name="brain" size={17} /> Think harder
    </button>
  );
}

/** The + menu's switch for this chat's Think harder. disabled: while the change is saved, or before Odie said what it is. */
export function ThinkSwitch({ on, disabled, onToggle }: { on: boolean; disabled: boolean; onToggle: () => void }) {
  return (
    <button type="button" role="menuitemcheckbox" aria-checked={on} onClick={onToggle} disabled={disabled}
      className="w-full flex items-center gap-3 p-2 rounded-2xl text-[15px] font-semibold text-left active:bg-well disabled:opacity-50">
      <Tile icon="brain" color="blue" small /><span className="flex-1">Think harder</span>
      <span className={`relative w-11 h-[26px] rounded-full transition-colors ${on ? "bg-good" : "bg-dim"}`}>
        <span className={`absolute top-[3px] w-5 h-5 rounded-full bg-white transition-all ${on ? "left-[21px]" : "left-[3px]"}`} />
      </span>
    </button>
  );
}
