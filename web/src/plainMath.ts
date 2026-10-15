// Models often write symbols as LaTeX ("Pune $\rightarrow$ Goa"); the chat has no maths renderer, so turn the common
// ones into the characters. Real formulas (fractions, roots…) are left as written, and code is never touched.

const SYMBOLS: Record<string, string> = {
  rightarrow: "→", to: "→", longrightarrow: "⟶", leftarrow: "←", gets: "←", longleftarrow: "⟵", leftrightarrow: "↔",
  Rightarrow: "⇒", implies: "⇒", Leftarrow: "⇐", Leftrightarrow: "⇔", iff: "⇔", mapsto: "↦", uparrow: "↑", downarrow: "↓",
  times: "×", cdot: "·", div: "÷", pm: "±", mp: "∓", approx: "≈", sim: "∼", simeq: "≃", equiv: "≡", neq: "≠", ne: "≠",
  leq: "≤", le: "≤", geq: "≥", ge: "≥", ll: "≪", gg: "≫", infty: "∞", degree: "°", circ: "∘", checkmark: "✓", check: "✓",
  star: "★", bullet: "•", ldots: "…", dots: "…", cdots: "⋯", in: "∈", notin: "∉", subset: "⊂", cup: "∪", cap: "∩",
  forall: "∀", exists: "∃", therefore: "∴", because: "∵", sum: "∑", prod: "∏", sqrt: "√", partial: "∂", nabla: "∇",
  alpha: "α", beta: "β", gamma: "γ", delta: "δ", Delta: "Δ", epsilon: "ε", theta: "θ", lambda: "λ", mu: "μ", pi: "π",
  rho: "ρ", sigma: "σ", Sigma: "Σ", tau: "τ", phi: "φ", omega: "ω", Omega: "Ω", quad: " ", qquad: " ",
  euro: "€", pounds: "£", rupee: "₹",
};
const NAMES = Object.keys(SYMBOLS).sort((a, b) => b.length - a.length).join("|");
const CMD = new RegExp(`\\\\{1,2}(${NAMES})(?![a-zA-Z])`, "g");  // one backslash, or two when the model escaped it

/** The inside of $…$ as plain text, or null when it's a real formula we can't flatten. */
function flatten(math: string): string | null {
  const out = math
    .replace(/\\\\(?=[a-zA-Z%$&#_,;:! ])/g, "\\")  // "\\rightarrow" → "\rightarrow"
    .replace(/\\text(?:bf|it|rm)?\{([^{}]*)\}/g, "$1")
    .replace(/\^\s*\{?\\circ\}?/g, "°")
    .replace(/\\([%$&#_])/g, "$1")
    .replace(/\\[,;:! ]/g, " ")
    .replace(CMD, (_, name: string) => SYMBOLS[name])
    .replace(/\s+/g, " ")
    .trim();
  return /[\\{}^_]/.test(out) ? null : out;
}

function plainProse(text: string): string {
  const inline = (s: string, open: RegExp) =>
    s.replace(open, (whole, inner: string) => (/\\/.test(inner) ? flatten(inner) ?? whole : whole));
  let s = inline(text, /\$([^$\n]+?)\$/g);       // only spans with a \command: "$120 to $200" stays money
  s = inline(s, /\\\((.+?)\\\)/g);
  return s.replace(CMD, (_, name: string) => SYMBOLS[name]);  // a bare "\rightarrow" outside dollars
}

/** Replace LaTeX symbols in a reply with their characters, outside code spans and fenced blocks. */
export function plainMath(text: string): string {
  if (!text.includes("\\")) return text;
  return text.split(/(```[\s\S]*?(?:```|$)|`[^`\n]*`)/g).map((part, i) => (i % 2 ? part : plainProse(part))).join("");
}
