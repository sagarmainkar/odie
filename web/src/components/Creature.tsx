import { useMemo } from "react";
import { creatureSvg, safeLook, type Look } from "../creature";
import { Avatar } from "./Avatar";

export type Mood = "" | "working" | "wants" | "selected";

/** The fur filter every creature shares: drawn once, anywhere on the page. */
export function FuzzFilter() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
      <filter id="odie-fuzz" x="-12%" y="-12%" width="124%" height="124%">
        <feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves={2} seed={7} result="n" />
        <feDisplacementMap in="SourceGraphic" in2="n" scale={6} xChannelSelector="R" yChannelSelector="G" />
        <feGaussianBlur stdDeviation={0.7} />
      </filter>
    </svg>
  );
}

/** A bot's creature. mood: working (a turning ring, the eyes look around), wants (an amber halo: it waits on your
 * tap), selected (an outline, in the drawer). Odie itself is drawn with its own face (Avatar), never a creature. */
export function Creature({ look, size = 52, mood = "", odie = false, title }: { look?: Partial<Look> | null; size?: number; mood?: Mood; odie?: boolean; title?: string }) {
  const svg = useMemo(() => (odie ? "" : creatureSvg(look)), [look, odie]);
  const color = safeLook(look).color;
  const style = { ["--s" as string]: `${size}px`, ["--c" as string]: odie ? "#7D8CFF" : color, width: size, height: size };
  return (
    <span className={`creature ${mood}`} style={style} title={title} aria-hidden={title ? undefined : true}>
      {odie ? <Avatar size={size} /> : <svg viewBox="0 0 100 100" dangerouslySetInnerHTML={{ __html: svg }} />}
    </span>
  );
}
