/** A bot's creature (Fable's design, 15 Nov): a soft furry shape in the bot's colour with two eyes. The look (shape,
 * colour, eyes) is picked by the server when the bot is made and kept (odie/workers/bots.py look_for); this draws it.
 * Everything drawn comes from the fixed tables below; the colour is checked to be a #rrggbb, so nothing a bot's name
 * or a model wrote can reach the markup. */

export type Look = { shape: string; color: string; eyes: string };

const SHAPES: Record<string, { y: number; d: string }> = {
  hex: { y: 52, d: '<polygon points="50,15 80,32 80,68 50,85 20,68 20,32" stroke-width="16" stroke-linejoin="round"/>' },
  cloud: { y: 54, d: '<circle cx="33" cy="40" r="23"/><circle cx="64" cy="38" r="25"/><circle cx="34" cy="64" r="23"/><circle cx="67" cy="64" r="23"/><circle cx="50" cy="52" r="26"/>' },
  squircle: { y: 52, d: '<rect x="9" y="9" width="82" height="82" rx="27"/>' },
  pent: { y: 54, d: '<polygon points="50,17 82,41 70,80 30,80 18,41" stroke-width="17" stroke-linejoin="round"/>' },
  pill: { y: 50, d: '<rect x="3" y="19" width="94" height="62" rx="31"/>' },
  drop: { y: 57, d: '<path d="M11 82C11 32 27 9 50 9s39 23 39 73c0 11-78 11-78 0z"/>' },
  tri: { y: 62, d: '<path d="M50 9c8 0 13 6 17 13l25 44c7 12 0 24-15 24H23C8 90 1 78 8 66l25-44c4-7 9-13 17-13z"/>' },
  flower: { y: 52, d: '<circle cx="50" cy="50" r="31"/>' + [0, 1, 2, 3, 4, 5, 6, 7].map((i) => `<circle cx="${(50 + 30 * Math.cos(i * Math.PI / 4)).toFixed(1)}" cy="${(50 + 30 * Math.sin(i * Math.PI / 4)).toFixed(1)}" r="14.5"/>`).join("") },
};

const glint = (x: number, y: number) => `<circle cx="${x + 2}" cy="${y - 2.5}" r="2" fill="#fff" opacity=".9"/>`;
const EYES: Record<string, (y: number) => string> = {
  round: (y) => [-13, 13].map((dx) => `<circle cx="${50 + dx}" cy="${y}" r="6.5"/>${glint(50 + dx, y)}`).join(""),
  tall: (y) => [-12, 12].map((dx) => `<ellipse cx="${50 + dx}" cy="${y}" rx="5" ry="8.5"/>${glint(50 + dx, y - 2)}`).join(""),
  calm: (y) => [-13, 13].map((dx) => `<path d="M${50 + dx - 6.5} ${y - 1}q6.5 7 13 0" fill="none" stroke="#221C2E" stroke-width="3.8" stroke-linecap="round"/>`).join(""),
  stern: (y) => [-13, 13].map((dx) => `<rect x="${50 + dx - 6.5}" y="${y - 3.5}" width="13" height="7" rx="3.5" transform="rotate(${dx < 0 ? 20 : -20} ${50 + dx} ${y})"/>`).join(""),
  dots: (y) => [-17, 17].map((dx) => `<circle cx="${50 + dx}" cy="${y}" r="4.2"/>`).join(""),
  side: (y) => [-10, 16].map((dx) => `<circle cx="${50 + dx}" cy="${y}" r="6.5"/><circle cx="${50 + dx + 2.8}" cy="${y - 1}" r="2.2" fill="#fff" opacity=".9"/>`).join("") + `<path d="M${50 + 9} ${y - 12}l14 -3" fill="none" stroke="#221C2E" stroke-width="3.4" stroke-linecap="round"/>`,
};

const FALLBACK: Look = { shape: "squircle", color: "#7C8AA5", eyes: "round" };

/** A look made safe to draw: an unknown shape, eyes or a colour that isn't #rrggbb fall back to the plain look's.
 * {shape: "hex", color: "#8B6CF6", eyes: "round"} -> the same; {shape: "x", color: "red"} -> squircle, slate, round. */
export function safeLook(look: Partial<Look> | null | undefined): Look {
  const shape = look?.shape && SHAPES[look.shape] ? look.shape : FALLBACK.shape;
  const eyes = look?.eyes && EYES[look.eyes] ? look.eyes : FALLBACK.eyes;
  const color = look?.color && /^#[0-9a-fA-F]{6}$/.test(look.color) ? look.color : FALLBACK.color;
  return { shape, color, eyes };
}

/** One colour mixed toward another: ("#000000", "#ffffff", .5) -> "#808080". */
export function mix(a: string, b: string, t: number): string {
  const parts = (x: string) => [1, 3, 5].map((i) => parseInt(x.slice(i, i + 2), 16));
  const A = parts(a);
  const B = parts(b);
  return "#" + A.map((v, i) => Math.round(v + (B[i] - v) * t).toString(16).padStart(2, "0")).join("");
}

let made = 0;

/** The creature's inner SVG (inside a 0 0 100 100 viewBox), with its own gradient id. */
export function creatureSvg(look: Partial<Look> | null | undefined): string {
  const { shape, color, eyes } = safeLook(look);
  const id = `cg${++made}`;
  const s = SHAPES[shape];
  return `<defs><radialGradient id="${id}" gradientUnits="userSpaceOnUse" cx="36" cy="26" r="80"><stop offset="0" stop-color="${mix(color, "#ffffff", 0.5)}"/><stop offset=".48" stop-color="${color}"/><stop offset="1" stop-color="${mix(color, "#24143a", 0.34)}"/></radialGradient></defs>`
    + `<g filter="url(#odie-fuzz)" fill="url(#${id})" stroke="url(#${id})" stroke-width="0">${s.d}</g>`
    + `<g class="eyes" fill="#221C2E">${EYES[eyes](s.y)}</g>`;
}
