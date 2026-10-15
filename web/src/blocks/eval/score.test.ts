import { describe, expect, it } from "vitest";
import { fencesIn, kindsOf, scoreReply, summarise } from "./score";

const fence = (json: unknown, lang = "odie-blocks") => "```" + lang + "\n" + JSON.stringify(json) + "\n```";
const table = { type: "table", columns: ["Phone", "Price"], rows: [["Pixel", "₹44,999"], ["Galaxy", "₹42,999"]] };
const callout = { type: "callout", tone: "tip", text: "Pixel if photos matter." };

describe("fencesIn", () => {
  it("finds each fence with its language, and an unclosed one at the end", () => {
    const text = "Intro\n```odie-blocks\n[1]\n```\nMiddle\n```json\n{}\n```\nTail\n```odie-blocks\n[2";
    expect(fencesIn(text)).toEqual([
      { lang: "odie-blocks", code: "[1]" },
      { lang: "json", code: "{}" },
      { lang: "odie-blocks", code: "[2" },
    ]);
  });
  it("finds none in plain text", () => {
    expect(fencesIn("Canberra is the capital of Australia.")).toEqual([]);
  });
});

describe("kindsOf", () => {
  it("lists a container, then its children", () => {
    expect(kindsOf([{ type: "section", collapsed: false, children: [{ type: "divider" }] }, { type: "divider" }])).toEqual(["section", "divider", "divider"]);
  });
});

describe("scoreReply", () => {
  const laptops = { expect: [["table"], ["callout"]], nice: ["section"] };

  it("passes a section holding a table and a callout, and notes the nice-to-have", () => {
    const s = scoreReply("Here.\n" + fence([{ type: "section", title: "Pick", children: [table, callout] }]), laptops);
    expect(s.verdict).toBe("pass");
    expect(s.kinds).toEqual(["section", "table", "callout"]);
    expect(s.nice_used).toEqual(["section"]);
    expect(s.reasons).toEqual([]);
  });
  it("is a partial when everything expected is drawn but a row was dropped", () => {
    const badRow = { ...table, rows: [...table.rows, ["Nothing", "₹39,999", "extra", "cells", "here"]] };
    const s = scoreReply(fence([badRow, callout]), laptops);
    expect(s.verdict).toBe("partial");
    expect(s.dropped.length).toBe(1);
    expect(s.dropped[0].path.startsWith("f1:0.rows")).toBe(true);
    expect(s.reasons).toEqual(["1 item dropped"]);
  });
  it("fails when an expected kind is missing", () => {
    const s = scoreReply(fence([table]), laptops);
    expect(s.verdict).toBe("fail");
    expect(s.missing).toEqual(["callout"]);
    expect(s.reasons).toEqual(["no callout"]);
  });
  it("accepts any kind of an either-or group", () => {
    const sip = { expect: [["calculator", "table", "chart"]] };
    expect(scoreReply(fence([table]), sip).verdict).toBe("pass");
  });
  it("fails a Markdown table with no fence, and says which other fence was used", () => {
    expect(scoreReply("| a | b |\n|---|---|\n| 1 | 2 |", laptops).reasons).toEqual(["no blocks fence"]);
    expect(scoreReply(fence([table], "json"), laptops).reasons).toEqual(["no blocks fence (wrote json fence)"]);
    expect(scoreReply("Prose only.", laptops, null, false).reasons).toEqual(["no blocks fence, visuals skill not loaded"]);
  });
  it("fails broken JSON and a fence with nothing drawable", () => {
    expect(scoreReply("```odie-blocks\n[{\"type\": \"table\",\n```", laptops).reasons).toEqual(["fence isn't valid JSON"]);
    const s = scoreReply(fence([{ type: "weather" }]), laptops);
    expect(s.reasons).toEqual(["nothing drawable"]);
    expect(s.dropped).toEqual([{ path: "f1:0", why: 'unknown type "weather"' }]);
  });
  it("passes plain text on a plain question, fails blocks there", () => {
    const plain = { expect: [] };
    expect(scoreReply("Canberra.", plain).verdict).toBe("pass");
    const s = scoreReply("Canberra.\n" + fence([callout]), plain);
    expect(s.verdict).toBe("fail");
    expect(s.reasons).toEqual(["blocks on a plain question"]);
  });
  it("counts an odie-images fence as the images kind", () => {
    const imgs = { title: "Kyoto", images: [{ url: "https://example.com/a.jpg" }] };
    expect(scoreReply(fence(imgs, "odie-images"), { expect: [["images"]] }).verdict).toBe("pass");
  });
  it("fails a turn that errored, even with nothing else wrong", () => {
    const s = scoreReply("", { expect: [] }, "TimeoutError: no reply in 180 s");
    expect(s.verdict).toBe("fail");
    expect(s.reasons).toEqual(["error: TimeoutError: no reply in 180 s"]);
  });
});

describe("summarise", () => {
  it("counts verdicts and dropped items", () => {
    const pass = scoreReply(fence([table]), { expect: [["table"]] });
    const fail = scoreReply("text", { expect: [["table"]] });
    expect(summarise([pass, fail])).toEqual({ pass: 1, partial: 0, fail: 1, total: 2, dropped: 0 });
  });
});
