/** An on/off switch. */
export function Switch({ on, disabled, onChange, label }: { on: boolean; disabled?: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)}
      className="shrink-0 w-11 h-10 flex items-center disabled:opacity-50">
      {/* the track is 26px tall; the button around it is 40px, so a thumb finds it */}
      <span className={`relative w-11 h-[26px] rounded-full transition-colors ${on ? "bg-good" : "bg-dim"}`}>
        <span className={`absolute top-[3px] w-5 h-5 rounded-full bg-white transition-all ${on ? "left-[21px]" : "left-[3px]"}`} />
      </span>
    </button>
  );
}
