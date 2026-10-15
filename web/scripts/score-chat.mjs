// Scores a chat-replay results file in place, with the app's own Markdown and block parsers (src/blocks/eval/chatScore.ts).
//   node web/scripts/score-chat.mjs ../evals/chats/<date>-<provider>-<model>.json
// Loaded through Vite, as score-blocks.mjs does, because the parsers are TypeScript. scripts/chat_replay.sh runs this.
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const webDir = fileURLToPath(new URL("..", import.meta.url));
const files = process.argv.slice(2);
if (!files.length) {
  console.error("usage: node web/scripts/score-chat.mjs <chat.json> …");
  process.exit(2);
}

const vite = await createServer({ root: webDir, configFile: false, logLevel: "error", server: { middlewareMode: true, hmr: false } });
try {
  const { scoreChatReply } = await vite.ssrLoadModule("/src/blocks/eval/chatScore.ts");
  for (const file of files) {
    const chat = JSON.parse(await readFile(file, "utf8"));
    let drawn = 0;
    let notDrawn = 0;
    for (const turn of chat.turns) {
      turn.score = scoreChatReply(turn.reply ?? "");
      if (turn.score.kinds.length) drawn += 1;
      notDrawn += turn.score.not_drawn.length;
    }
    await writeFile(file, JSON.stringify(chat, null, 2) + "\n");
    console.log(`${file}: ${chat.turns.length} turns, ${drawn} drew something, ${notDrawn} pieces not drawn`);
  }
} finally {
  await vite.close();
}
