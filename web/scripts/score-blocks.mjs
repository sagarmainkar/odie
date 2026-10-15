// Scores a blocks-eval results file in place, with the app's own parser (src/blocks/eval/score.ts).
//   node web/scripts/score-blocks.mjs ../evals/blocks/2026-10-11-anthropic-claude-sonnet-5-5.json
// Why Vite: the parser is TypeScript and imports .tsx files; Vite (already a dev dependency) loads them in Node the way
// the app's build does, so nothing new is installed. scripts/blocks_eval.sh runs this after the model's turns.
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const webDir = fileURLToPath(new URL("..", import.meta.url));
const files = process.argv.slice(2);
if (!files.length) {
  console.error("usage: node web/scripts/score-blocks.mjs <results.json> …");
  process.exit(2);
}

const vite = await createServer({ root: webDir, configFile: false, logLevel: "error", server: { middlewareMode: true, hmr: false } });
try {
  const { scoreReply, summarise } = await vite.ssrLoadModule("/src/blocks/eval/score.ts");
  for (const file of files) {
    const run = JSON.parse(await readFile(file, "utf8"));
    for (const q of run.questions) {
      // Since 2026-10-12 the catalogue is in the system prompt (no visuals skill to load): not loading it means nothing.
      const loadedVisuals = run.visuals_in_prompt
        ? undefined
        : (q.tools ?? []).some((t) => t.tool === "load_skill" && t.args?.skill_name === "visuals");
      q.score = scoreReply(q.reply ?? "", { expect: q.expect, nice: q.nice }, q.error, loadedVisuals);
    }
    run.summary = summarise(run.questions.map((q) => q.score));
    await writeFile(file, JSON.stringify(run, null, 2) + "\n");
    const s = run.summary;
    console.log(`${file}: ${s.pass} pass, ${s.partial} partial, ${s.fail} fail of ${s.total}`);
  }
} finally {
  await vite.close();
}
