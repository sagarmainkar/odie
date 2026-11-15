import { describe, expect, it } from "vitest";
import { colorFor, elapsed, going, headerWords, type Member } from "./team";

const m = (over: Partial<Member>): Member => ({ job: "job-1", bot: "researcher", status: "running", outcome: null, now: "", model: "", report: "", calls: 0, started_at: null, ended_at: null, ...over });

describe("team card", () => {
  it("keeps a bot's colour and the chief violet", () => {
    expect(colorFor("chief")).toBe("#8b6cf6");
    expect(colorFor("researcher")).toBe(colorFor("researcher"));
  });
  it("counts time worked", () => {
    expect(elapsed(m({}), 0)).toBe("");
    expect(elapsed(m({ started_at: "2026-11-15T10:00:00Z" }), Date.parse("2026-11-15T10:01:15Z"))).toBe("1:15");
    expect(elapsed(m({ started_at: "2026-11-15T10:00:00Z", ended_at: "2026-11-15T10:00:09Z" }), 0)).toBe("0:09");
  });
  it("says how far the team is", () => {
    const lead = m({ bot: "chief" });
    expect(headerWords({ title: "t", lead, team: [] })).toBe("Working");
    expect(headerWords({ title: "t", lead, team: [m({ status: "done" }), m({}), m({ status: "failed" })] })).toBe("Team at work · 2 of 3 done");
    expect(headerWords({ title: "t", lead: m({ status: "done" }), team: [] })).toBe("done");
    expect(headerWords({ title: "t", lead: m({ status: "failed" }), team: [] })).toBe("didn't finish");
    expect(going(m({ status: "waiting" }))).toBe(true);
  });
});
