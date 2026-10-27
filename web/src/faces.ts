/** A drawn face for each voice in an audio story (components/Face.tsx draws it). The name picks the hair, the skin
 * tone and one small extra from fixed sets, so a name gets the same face every time, on every device; the group picks
 * a woman's, a man's or a storybook face. Nothing is fetched: it's all inline SVG. */

export type FaceKind = "woman" | "man" | "storybook";
export type FaceLook = { kind: FaceKind; skin: string; hair: string; hairColour: string; extra: string };

/** Human skin tones, light to deep. */
export const SKINS = ["#F7D9BE", "#EEC39B", "#D9A273", "#B97C4E", "#8C5A36", "#5E3B23"];
/** Hair: near black, dark brown, chestnut, blonde, auburn, grey. */
const HAIR_COLOURS = ["#2B1D14", "#4A2E1E", "#7B4A2A", "#C9974A", "#A3472A", "#8E8A86"];
/** A storybook character's "skin": sage, lavender, honey, sky, clay, stone. */
const STORY_SKINS = ["#B8D99A", "#C9B8F0", "#F5C99B", "#A9D3EE", "#E8B4A0", "#D7CFC4"];
/** The colour of a storybook character's hat or antennae. */
const STORY_TOPS = ["#5B5FC7", "#3F8F7E", "#B5532F", "#7A4FA0"];

const HAIR_STYLES: Record<FaceKind, string[]> = {
  woman: ["long", "bob", "bun", "curls"],
  man: ["crop", "side", "bald", "curls"],
  storybook: ["round-ears", "pointy-ears", "hat", "antennae"],
};
const EXTRAS: Record<FaceKind, string[]> = {
  woman: ["none", "glasses", "earrings", "freckles"],
  man: ["none", "glasses", "beard", "moustache"],
  storybook: ["none", "whiskers", "glasses", "freckles"],
};

/**
 * Decides which kind of face a voice gets from its group: "female" → a woman's face, "male" → a man's, anything else
 * ("Characters", a creature, or no group) → a neutral storybook face. faceKind("female") → "woman";
 * faceKind("Characters") → "storybook".
 */
export function faceKind(group: string): FaceKind {
  const g = group.trim().toLowerCase();
  if (g === "female") return "woman";
  if (g === "male") return "man";
  return "storybook";
}

/** A number from a text that is always the same for the same text (FNV-1a). */
function hashOf(text: string): number {
  let h = 0x811c9dc5;
  for (const ch of text) {
    h ^= ch.codePointAt(0) ?? 0;
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h;
}

/** One of `choices`, picked by the name; each `part` (hair, skin, ...) is picked on its own, so they vary apart. */
function pick(name: string, part: string, choices: string[]): string {
  return choices[hashOf(`${part}:${name}`) % choices.length];
}

/** The face for a name: "Claire" in "female" → always the same woman's face; " claire " is the same name. */
export function faceFor(name: string, group: string): FaceLook {
  const key = name.trim().toLowerCase().split(/\s+/).join(" ");
  const kind = faceKind(group);
  const human = kind !== "storybook";
  const skins = human ? SKINS : STORY_SKINS;
  const hairColours = human ? HAIR_COLOURS : STORY_TOPS;
  return {
    kind,
    skin: pick(key, "skin", skins),
    hair: pick(key, "hair", HAIR_STYLES[kind]),
    hairColour: pick(key, "hair colour", hairColours),
    extra: pick(key, "extra", EXTRAS[kind]),
  };
}
