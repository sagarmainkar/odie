import { describe, expect, it } from "vitest";
import { replyLine, usageLine } from "./usage";

describe("model usage", () => {
  it("says how much of the last reply's input came from the cache", () => {
    expect(usageLine({ input: 9800, cached: 8900, output: 250 })).toBe("Last reply: 9.8K tokens in, 91% from cache");
    expect(usageLine({ input: 12000, cached: 0, output: 300 })).toBe("Last reply: 12K tokens in, none from cache");
    expect(usageLine({ input: 640, cached: 0, output: 20 })).toBe("Last reply: 640 tokens in, none from cache");
    expect(usageLine(null)).toBe("");
  });

  it("names a reply's own share under it", () => {
    expect(replyLine({ input: 9800, cached: 8900, output: 250 })).toBe("9.8K tokens in · 91% from cache");
    expect(replyLine({ input: 640, cached: 0, output: 20 })).toBe("640 tokens in · none from cache");
    expect(replyLine(undefined)).toBe("");
  });
});
