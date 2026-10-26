import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { ASK_CARD_CLASS } from "./LocationAsk";

const styles = readFileSync(new URL("../styles.css", import.meta.url), "utf8");

describe("the location ask card", () => {
  it("keeps the composer's horizontal bounds on a desktop", () => {
    expect(ASK_CARD_CLASS.split(" ")).toContain("chat-aside");  // the class the composer's desktop rule also covers
    const desktopRule = /\.chat-composer,\s*\.chat-aside\s*\{[^}]*max\(12px, calc\(\(100% - 796px\) \/ 2\)\)/;
    expect(styles).toMatch(desktopRule);
  });
});
