import { describe, expect, it } from "vitest";
import { badge, brainState, partLine, said, tone, type BrainReport } from "./brain";

const report = (verdict: BrainReport["verdict"]): BrainReport => ({
  provider: "ollama", model: "glm", verdict, sentence: "glm: …", checked_at: "2026-10-06T21:00:00Z",
  parts: [{ name: "tools", status: "pass", detail: "3 of 3 calls had the right fields and values" },
          { name: "speed", status: "warn", detail: "6 tokens a second" },
          { name: "context", status: "unknown", detail: "context unknown" }],
});

describe("brain check", () => {
  it("has a tone per verdict", () => {
    expect(tone(report("good"))).toBe("good");
    expect(tone(report("slow"))).toBe("warn");
    expect(tone(report("warn"))).toBe("warn");
    expect(tone(report("fail"))).toBe("bad");
  });

  it("says each part in plain words", () => {
    const [tools, speed, ctx] = report("slow").parts.map(partLine);
    expect(tools).toBe("✓ Tool calls: 3 of 3 calls had the right fields and values");
    expect(speed).toBe("! Speed: 6 tokens a second");
    expect(ctx).toBe("· Context: context unknown");
  });

  it("says the sentence without the model's name, even with a colon in it", () => {
    const r = { ...report("good"), model: "glm-5.3-flash:cloud", sentence: "glm-5.3-flash:cloud: uses tools correctly · fast · good choice" };
    expect(said(r)).toBe("uses tools correctly · fast · good choice");
  });

  it("has a short badge for the model list", () => {
    expect(badge(report("good"))).toBe("✓ good");
    expect(badge(report("slow"))).toBe("! slow");
    expect(badge(report("fail"))).toBe("✕ won't work");
  });
});

describe("brainState", () => {
  it("never shows a model nobody picked as if it worked", () => {
    expect(brainState(true, true)).toBe("ready");
    expect(brainState(true, false)).toBe("unreachable");
    expect(brainState(false, false)).toBe("none");
    expect(brainState(false, true)).toBe("ready");
    expect(brainState(undefined, undefined)).toBe("ready");  // an older server that doesn't say
  });
});
