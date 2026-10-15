// Scoring one saved model reply for the blocks eval (scripts/blocks_eval.sh). It reads the reply with the app's own
// parser (readBlocks), so "dropped" means exactly what the phone would drop, with the parser's own reasons.
import { parseImages } from "../../components/ImageStrip";
import { readBlocks, type Block, type Diagnostic } from "../parse";

/** What a question wants drawn. `expect`: groups of kinds; every group needs at least one of its kinds drawn.
 *  [] means the reply should have no blocks at all. `nice`: kinds that make it better but aren't required. */
export type Expectation = { expect: string[][]; nice?: string[] };

export type Verdict = "pass" | "partial" | "fail";

export type ReplyScore = {
  fences: number;            // ```odie-blocks and ```odie-images fences in the reply
  other_fences: string[];    // the language of every other code fence (e.g. "json"): blocks in the wrong fence show here
  parsed: boolean;           // every block fence was a JSON list the app could read
  kinds: string[];           // every kind drawn, containers and their children included, in order
  dropped: Diagnostic[];     // what the parser dropped or redrew, path prefixed with the fence number ("f1:0.rows.2")
  missing: string[];         // expectation groups not met, each written "table" or "calculator|table|chart"
  nice_used: string[];       // the nice-to-have kinds that were drawn
  verdict: Verdict;
  reasons: string[];         // why it isn't a pass, in words
};

export type Fence = { lang: string; code: string };

/**
 * Every fenced code block in a reply, with its language, read line by line the way Markdown does: a line starting with
 * ``` opens a fence, the next line that is only backticks closes it, and a fence never closed runs to the end.
 *   "Here:\n```odie-blocks\n[{\"type\":\"divider\"}]\n```\nDone." → [{lang: "odie-blocks", code: "[{\"type\":\"divider\"}]"}]
 */
export function fencesIn(text: string): Fence[] {
  const out: Fence[] = [];
  let open: { lang: string; lines: string[] } | null = null;
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (open === null) {
      if (trimmed.startsWith("```")) open = { lang: trimmed.slice(3).trim().split(/\s/)[0], lines: [] };
      continue;
    }
    if (/^```+$/.test(trimmed)) {
      out.push({ lang: open.lang, code: open.lines.join("\n") });
      open = null;
      continue;
    }
    open.lines.push(line);
  }
  if (open !== null) out.push({ lang: open.lang, code: open.lines.join("\n") });
  return out;
}

/** Every kind in a list of parsed blocks, a container's children right after it.
 *  [{type: "section", children: [{type: "table"}, {type: "callout"}]}] → ["section", "table", "callout"] */
export function kindsOf(blocks: Block[]): string[] {
  const kinds: string[] = [];
  for (const b of blocks) {
    kinds.push(b.type);
    if ("children" in b) kinds.push(...kindsOf(b.children));
  }
  return kinds;
}

/**
 * Decides the verdict for one reply. It fails when the turn errored, when blocks were wanted but none were drawn (no
 * fence, broken JSON, nothing drawable, or none of an expected kind), or when blocks were drawn on a question that
 * wanted none. It is a partial when everything expected was drawn but the parser dropped or redrew something. Else a
 * pass. Worked examples, for a question expecting [["table"], ["callout"]]:
 *   a fence with a section holding a table and a callout, nothing dropped → pass
 *   the same, but one table row had too many cells (dropped)             → partial ("1 item dropped")
 *   a fence with only a table                                             → fail ("no callout")
 *   a Markdown table and no fence                                         → fail ("no blocks fence")
 *   the same, and the turn never loaded the visuals skill                  → fail ("no blocks fence, visuals skill not loaded")
 * and for a question expecting [] ("What's the capital of Australia?"):
 *   plain text → pass;  a fence with a callout → fail ("blocks on a plain question")
 */
export function scoreReply(text: string, want: Expectation, error?: string | null, loadedVisuals?: boolean): ReplyScore {
  const fences = fencesIn(text);
  const blockFences = fences.filter((f) => f.lang === "odie-blocks");
  const imageFences = fences.filter((f) => f.lang === "odie-images");
  const otherFences = fences.filter((f) => f.lang !== "odie-blocks" && f.lang !== "odie-images").map((f) => f.lang || "plain");

  // Step 1: read every block fence with the app's parser.
  let parsed = true;
  const kinds: string[] = [];
  const dropped: Diagnostic[] = [];
  blockFences.forEach((f, i) => {
    const read = readBlocks(f.code);
    if (!read) {
      parsed = false;
      return;
    }
    kinds.push(...kindsOf(read.blocks));
    for (const d of read.dropped) dropped.push({ path: `f${i + 1}:${d.path}`, why: d.why });
  });
  for (const f of imageFences) {
    if (parseImages(f.code)) kinds.push("images");
    else parsed = false;
  }

  // Step 2: which expected groups were met, and which nice-to-haves showed up.
  const missing: string[] = [];
  for (const group of want.expect) {
    const met = group.some((k) => kinds.includes(k));
    if (!met) missing.push(group.join("|"));
  }
  const nice = want.nice ?? [];
  const niceUsed = nice.filter((k) => kinds.includes(k));

  // Step 3: the verdict and its reasons.
  const reasons: string[] = [];
  const wantsBlocks = want.expect.length > 0;
  const fenceCount = blockFences.length + imageFences.length;
  if (error) reasons.push(`error: ${error}`);
  if (wantsBlocks) {
    if (fenceCount === 0) reasons.push(noFenceReason(otherFences, loadedVisuals));
    else if (!parsed) reasons.push("fence isn't valid JSON");
    else if (kinds.length === 0) reasons.push("nothing drawable");
    const somethingDrawn = fenceCount > 0 && parsed && kinds.length > 0;
    if (somethingDrawn) {
      for (const m of missing) reasons.push(`no ${m}`);
    }
  } else if (fenceCount > 0) {
    reasons.push("blocks on a plain question");
  }
  let verdict: Verdict = "pass";
  if (reasons.length) verdict = "fail";
  else if (dropped.length) {
    verdict = "partial";
    reasons.push(`${dropped.length} item${dropped.length === 1 ? "" : "s"} dropped`);
  }

  return { fences: fenceCount, other_fences: otherFences, parsed, kinds, dropped, missing, nice_used: niceUsed, verdict, reasons };
}

/** Why a reply that should have blocks has none, in words: "no blocks fence", plus which other fence it wrote and
 *  whether the turn loaded the visuals skill (undefined: not known).
 *  (["json"], true) → "no blocks fence (wrote json fence)";  ([], false) → "no blocks fence, visuals skill not loaded" */
function noFenceReason(otherFences: string[], loadedVisuals?: boolean): string {
  let reason = "no blocks fence";
  if (otherFences.length) reason += ` (wrote ${otherFences.join(", ")} fence)`;
  if (loadedVisuals === false) reason += ", visuals skill not loaded";
  return reason;
}

export type RunSummary = { pass: number; partial: number; fail: number; total: number; dropped: number };

/** Counts over a run's scores: [pass, partial, fail] → {pass: 1, partial: 1, fail: 1, total: 3, dropped: …} */
export function summarise(scores: ReplyScore[]): RunSummary {
  const out: RunSummary = { pass: 0, partial: 0, fail: 0, total: scores.length, dropped: 0 };
  for (const s of scores) {
    out[s.verdict] += 1;
    out.dropped += s.dropped.length;
  }
  return out;
}
