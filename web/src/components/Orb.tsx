import { motion } from "framer-motion";

export type OrbState = "idle" | "listening" | "thinking" | "speaking" | "approval";

/** The CSS mood for a state: idle breathes, the rest are named (is-thinking rolls its eyes, is-speaking talks…). */
export function moodClass(state: OrbState): string {
  return state === "idle" ? "breathe" : `is-${state}`;
}

/**
 * Odie's presence: a face. One colour and still when idle (a blink now and then); listening it opens its eyes wide
 * and breathes faster; thinking it rolls its eyes under a spinning dotted ring and turns iridescent; speaking it
 * moves its mouth; waiting for a tap it raises a brow in a warm glow. The same face is the app's icon. All the motion
 * is CSS (styles.css, .face-*), so it costs nothing while idle and stops under reduced motion.
 */
export function Orb({ state = "idle", size = 40, halo = false }: { state?: OrbState; size?: number; halo?: boolean }) {
  const mood = moodClass(state);
  return (
    <span className={`orb ${mood} ${halo ? "orb-halo" : ""}`} style={{ width: size, height: size, ["--s" as string]: `${size}px` }} role="img" aria-label={state}>
      <svg className="face" viewBox="-100 -100 200 200" aria-hidden="true">
        <defs>
          <linearGradient id="odie-iris" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#7D8CFF" /><stop offset=".55" stopColor="#B08BFF" /><stop offset="1" stopColor="#FF9CC8" /></linearGradient>
          <radialGradient id="odie-shine" cx=".35" cy=".25" r=".6"><stop offset="0" stopColor="#fff" stopOpacity=".5" /><stop offset="1" stopColor="#fff" stopOpacity="0" /></radialGradient>
        </defs>
        <circle className="face-ring" r="96" fill="none" strokeWidth="6" strokeDasharray="20 15" strokeLinecap="round" />
        <circle className="face-body" r="86" />
        <circle r="86" fill="url(#odie-shine)" />
        <path className="face-brow" d="M-46 -44 Q-30 -54 -14 -46" fill="none" strokeWidth="6" strokeLinecap="round" />
        {/* The outer group places the eye; the inner one blinks (a CSS transform would override the placing one). */}
        {[-30, 30].map((ex) => (
          <g key={ex} transform={`translate(${ex}, -10)`}>
            <g className="face-eye">
              <ellipse rx="16" ry="21" fill="#fff" />
              <g className="face-pupil"><circle r="9" fill="#1C1B22" /><circle cx="3" cy="-4" r="2.8" fill="#fff" /></g>
            </g>
          </g>
        ))}
        <path className="face-mouth" d="M-14 28 Q0 42 14 28" fill="none" strokeWidth="6" strokeLinecap="round" />
      </svg>
    </span>
  );
}

export function SpeakingBars() {
  return (
    <span className="inline-flex items-center gap-[3px] h-5" aria-hidden>
      {[0, 0.15, 0.3, 0.45, 0.6].map((d) => (
        <motion.span key={d} className="w-1 rounded bg-iris" animate={{ height: [6, 18, 6] }}
          transition={{ duration: 0.9, repeat: Infinity, delay: d, ease: "easeInOut" }} />
      ))}
    </span>
  );
}
