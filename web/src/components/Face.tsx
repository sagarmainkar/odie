import type { ReactNode } from "react";
import { faceFor, type FaceLook } from "../faces";

/** The eyes, mouth and outlines. */
const INK = "#2A1E18";
const CHEEKS = "#F28B82";

/**
 * A small, friendly face for one voice in a story, drawn on a 64×64 grid: a soft background and shoulders in the
 * speaker's tone (so the face matches their colour in the transcript), the head, hair and one extra. The name always
 * draws the same face (faces.ts). It's decoration: whoever shows it names the person for a screen reader.
 */
export function Face({ name, group, tone = "var(--t-brand)" }: { name: string; group: string; tone?: string }) {
  const look = faceFor(name, group);
  const background = `color-mix(in srgb, ${tone} 24%, var(--t-surface-2))`;
  return (
    <svg viewBox="0 0 64 64" width="100%" height="100%" aria-hidden data-face={look.kind} style={{ display: "block" }}>
      <rect width="64" height="64" style={{ fill: background }} />
      <path d="M8 66 C10 51 21 46 32 46 C43 46 54 51 56 66 Z" style={{ fill: tone }} />
      {look.kind === "storybook" ? <StorybookHead look={look} /> : <PersonHead look={look} />}
    </svg>
  );
}

/** A woman's or a man's head: hair behind, neck, head and ears, the face, hair in front, then the extra. */
function PersonHead({ look }: { look: FaceLook }) {
  return (
    <g>
      <HairBehind look={look} />
      <rect x="27" y="38" width="10" height="10" rx="3" fill={look.skin} />
      <rect x="27" y="38" width="10" height="4" fill="rgba(0,0,0,.08)" />
      <circle cx="19" cy="31" r="3" fill={look.skin} />
      <circle cx="45" cy="31" r="3" fill={look.skin} />
      <ellipse cx="32" cy="29" rx="13" ry="14" fill={look.skin} />
      <Features eyeSize={1.8} />
      <HairInFront look={look} />
      <Extra look={look} />
    </g>
  );
}

/** A storybook character: a round head in a storybook colour, ears or a hat or antennae, bigger eyes and a nose. */
function StorybookHead({ look }: { look: FaceLook }) {
  return (
    <g>
      <StorybookTop look={look} behind />
      <circle cx="32" cy="31" r="15" fill={look.skin} />
      <ellipse cx="32" cy="34" rx="2.2" ry="1.5" fill={INK} />
      <Features eyeSize={2.3} />
      <StorybookTop look={look} />
      <Extra look={look} />
    </g>
  );
}

/** Eyes with a glint, rosy cheeks and a smile. */
function Features({ eyeSize }: { eyeSize: number }) {
  return (
    <g>
      <circle cx="24.5" cy="34.5" r="2.4" fill={CHEEKS} opacity=".35" />
      <circle cx="39.5" cy="34.5" r="2.4" fill={CHEEKS} opacity=".35" />
      <circle cx="27" cy="29.5" r={eyeSize} fill={INK} />
      <circle cx="37" cy="29.5" r={eyeSize} fill={INK} />
      <circle cx="27.6" cy="28.9" r=".7" fill="#FFFFFF" />
      <circle cx="37.6" cy="28.9" r=".7" fill="#FFFFFF" />
      <path d="M28.5 36 Q32 39 35.5 36" stroke={INK} strokeWidth="1.6" strokeLinecap="round" fill="none" />
    </g>
  );
}

/** The hair that falls behind the head: long hair, a bob, or curls at the sides; nothing for short styles. */
function HairBehind({ look }: { look: FaceLook }) {
  const c = look.hairColour;
  if (look.hair === "long") return <path d="M15 30 C15 12 49 12 49 30 L51 50 C44 55 20 55 13 50 Z" fill={c} />;
  if (look.hair === "bob") return <path d="M16 29 C16 12 48 12 48 29 L48 41 C44 43 42 41 42 37 L22 37 C22 41 20 43 16 41 Z" fill={c} />;
  if (look.hair === "curls" && look.kind === "woman") {
    return <g fill={c}><circle cx="17" cy="33" r="5.5" /><circle cx="47" cy="33" r="5.5" /><circle cx="18" cy="41" r="4.5" /><circle cx="46" cy="41" r="4.5" /></g>;
  }
  return null;
}

/** The hair over the top of the head, one shape per style. */
function HairInFront({ look }: { look: FaceLook }) {
  const c = look.hairColour;
  const shapes: Record<string, ReactNode> = {
    long: <path d="M19 27 C19 12 45 12 45 27 C41 21 34 19 27 21 C23 22 20 24 19 27 Z" fill={c} />,
    bob: <path d="M19 25 C19 13 45 13 45 25 Z" fill={c} />,
    bun: <g fill={c}><circle cx="32" cy="12" r="6" /><path d="M19 26 C19 13 45 13 45 26 C40 20 24 20 19 26 Z" /></g>,
    curls: <g fill={c}><circle cx="21" cy="21" r="5.5" /><circle cx="26.5" cy="16" r="5.5" /><circle cx="32" cy="14.5" r="5.5" /><circle cx="37.5" cy="16" r="5.5" /><circle cx="43" cy="21" r="5.5" /></g>,
    crop: <path d="M19 25 C19 13 45 13 45 25 C40 20.5 24 20.5 19 25 Z" fill={c} />,
    side: <path d="M19 27 C18 13 46 12 45 26 C42 20 36 18.5 30 21 C26 19 22 22 19 27 Z" fill={c} />,
    bald: <g fill={c}><path d="M18.5 31 C18 25 19.5 21.5 22 20 L22.5 28 Z" /><path d="M45.5 31 C46 25 44.5 21.5 42 20 L41.5 28 Z" /></g>,
  };
  return shapes[look.hair] ?? null;
}

/** A storybook character's ears, hat or antennae. Ears sit behind the head (`behind`); a hat and antennae in front. */
function StorybookTop({ look, behind = false }: { look: FaceLook; behind?: boolean }) {
  const earsBehind = look.hair === "round-ears" || look.hair === "pointy-ears";
  if (behind !== earsBehind) return null;
  if (look.hair === "round-ears") {
    return <g><circle cx="19" cy="19" r="6.5" fill={look.skin} /><circle cx="45" cy="19" r="6.5" fill={look.skin} /><circle cx="19" cy="19" r="3.2" fill="rgba(0,0,0,.12)" /><circle cx="45" cy="19" r="3.2" fill="rgba(0,0,0,.12)" /></g>;
  }
  if (look.hair === "pointy-ears") {
    return <g fill={look.skin}><path d="M17 27 L19.5 8 L30 18 Z" /><path d="M47 27 L44.5 8 L34 18 Z" /></g>;
  }
  if (look.hair === "hat") {
    return <g fill={look.hairColour}><path d="M19 21 L33 1 L45 21 Z" /><ellipse cx="32" cy="21" rx="17" ry="3.2" /></g>;
  }
  return (
    <g stroke={look.hairColour} strokeWidth="1.8" strokeLinecap="round" fill={look.hairColour}>
      <path d="M27 17 L23 7" /><path d="M37 17 L41 7" /><circle cx="23" cy="7" r="2.4" /><circle cx="41" cy="7" r="2.4" />
    </g>
  );
}

/** The one extra the name picked: glasses, earrings, freckles, a beard, a moustache or whiskers (or none). */
function Extra({ look }: { look: FaceLook }) {
  const c = look.hairColour;
  const extras: Record<string, ReactNode> = {
    glasses: (
      <g stroke={INK} strokeWidth="1.3" fill="rgba(255,255,255,.18)">
        <circle cx="27" cy="29.5" r="4.2" /><circle cx="37" cy="29.5" r="4.2" /><path d="M31.2 29.5 L32.8 29.5" />
      </g>
    ),
    earrings: <g fill="#F2C14E"><circle cx="19" cy="36" r="1.7" /><circle cx="45" cy="36" r="1.7" /></g>,
    freckles: (
      <g fill={INK} opacity=".35">
        <circle cx="23.5" cy="33" r=".7" /><circle cx="25.5" cy="34.5" r=".7" /><circle cx="40.5" cy="33" r=".7" /><circle cx="38.5" cy="34.5" r=".7" />
      </g>
    ),
    beard: <path d="M19.5 32 C20.5 43 27 46.5 32 46.5 C37 46.5 43.5 43 44.5 32 C42.5 38 38 40.5 32 40.5 C26 40.5 21.5 38 19.5 32 Z" fill={c} />,
    moustache: <path d="M27 34.6 Q32 31.8 37 34.6 Q32 36.2 27 34.6 Z" fill={c} />,
    whiskers: (
      <g stroke={INK} strokeWidth=".9" strokeLinecap="round" opacity=".55">
        <path d="M24 35 L15 33.5" /><path d="M24 36.5 L15 37.5" /><path d="M40 35 L49 33.5" /><path d="M40 36.5 L49 37.5" />
      </g>
    ),
  };
  return extras[look.extra] ?? null;
}
