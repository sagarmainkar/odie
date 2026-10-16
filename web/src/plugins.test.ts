import { describe, expect, it } from "vitest";
import { checkSummary, linkCarriesToken, specFromForm, statusLabel } from "./plugins";

describe("statusLabel", () => {
  it("names every status plainly", () => {
    expect(statusLabel("ok")).toEqual({ text: "Ready", tone: "good" });
    expect(statusLabel("blocked")).toEqual({ text: "Needs your OK", tone: "warn" });
    expect(statusLabel("failed").tone).toBe("warn");
    expect(statusLabel("disabled")).toEqual({ text: "Off", tone: "soft" });
  });
});

describe("specFromForm", () => {
  it("builds a stdio or url spec, and rejects bad input", () => {
    expect(specFromForm({ name: "gh", target: "npx -y @mcp/github", description: "", env: [["TOKEN", "x"]] }))
      .toEqual({ name: "gh", spec: { command: "npx", args: ["-y", "@mcp/github"], env: { TOKEN: "x" } } });
    expect(specFromForm({ name: "notion", target: "https://mcp.notion.com/mcp", description: "Notes", env: [] }))
      .toEqual({ name: "notion", spec: { url: "https://mcp.notion.com/mcp", description: "Notes" } });
    expect(specFromForm({ name: "Bad Name", target: "x", description: "", env: [] })).toMatch(/lower-case/);
    expect(specFromForm({ name: "ok", target: "", description: "", env: [] })).toMatch(/command or a URL/);
  });
});

import { formFromServer, serverTitle, toolLabel } from "./plugins";

describe("plain words", () => {
  it("turns tool names into labels", () => {
    expect(toolLabel("search_notes")).toBe("Search notes");
    expect(toolLabel("index_status")).toBe("Index status");
    expect(toolLabel("get-issue")).toBe("Get issue");
  });
  it("shows a server's title, else its name", () => {
    expect(serverTitle({ name: "vault", spec: { title: "Obsidian notes" } } as any)).toBe("Obsidian notes");
    expect(serverTitle({ name: "github", spec: {} } as any)).toBe("github");
  });
});

describe("formFromServer", () => {
  it("fills the edit form, secrets stay masked", () => {
    const f = formFromServer({ name: "vault", spec: { url: "http://127.0.0.1:8766/mcp", headers: { "X-Profile": "••••" }, title: "Obsidian notes", description: "Notes" } } as any);
    expect(f).toEqual({ name: "vault", title: "Obsidian notes", target: "http://127.0.0.1:8766/mcp", description: "Notes", env: [["X-Profile", "••••"]] });
    const g = formFromServer({ name: "gh", spec: { command: "npx", args: ["-y", "@mcp/github"] } } as any);
    expect(g.target).toBe("npx -y @mcp/github");
    expect(g.env).toEqual([["", ""]]);
  });
  it("round-trips through specFromForm, keeping the title", () => {
    const f = formFromServer({ name: "vault", spec: { url: "http://h/mcp", headers: { K: "••••" }, title: "Obsidian notes" } } as any);
    expect(specFromForm(f)).toEqual({ name: "vault", spec: { url: "http://h/mcp", headers: { K: "••••" }, title: "Obsidian notes" } });
  });
});

describe("arguments with spaces", () => {
  it("keeps quoted arguments whole and quotes them again for editing", async () => {
    const { formFromServer, splitArgs } = await import("./plugins");
    expect(splitArgs(`uvx mcp-obsidian --vault "/Users/me/My Vault" --mode 'read only'`)).toEqual(["uvx", "mcp-obsidian", "--vault", "/Users/me/My Vault", "--mode", "read only"]);
    const r = specFromForm({ name: "obs", target: `uvx mcp-obsidian --vault "/Users/me/My Vault"`, description: "", env: [["", ""]] });
    expect(typeof r !== "string" && r.spec.args).toEqual(["mcp-obsidian", "--vault", "/Users/me/My Vault"]);
    const f = formFromServer({ name: "obs", spec: { command: "uvx", args: ["mcp-obsidian", "--vault", "/Users/me/My Vault"] } } as any);
    expect(f.target).toBe(`uvx mcp-obsidian --vault "/Users/me/My Vault"`);
  });
});

describe("the connection check", () => {
  const t = (asks: boolean) => ({ name: "x", read_only: false, asks });
  it("says how many tools there are and how many ask for a tap", () => {
    expect(checkSummary([])).toBe("No tools");
    expect(checkSummary([t(true)])).toBe("1 tool · it asks for a tap");
    expect(checkSummary([t(false)])).toBe("1 tool · no taps needed");
    expect(checkSummary([t(true), t(true)])).toBe("2 tools · each asks for a tap");
    expect(checkSummary([...Array(8)].map(() => t(false)).concat([...Array(4)].map(() => t(true))))).toBe("12 tools · 4 ask for a tap");
    expect(checkSummary([t(true), t(false), t(false)])).toBe("3 tools · 1 asks for a tap");
    expect(checkSummary([t(false), t(false)])).toBe("2 tools · no taps needed");
  });

  it("knows a link that carries its own code", () => {
    expect(linkCarriesToken("https://mcp.zapier.com/api/v1/connect?token=QUJD")).toBe(true);
    expect(linkCarriesToken("https://mcp.zapier.com/api/v1/connect")).toBe(false);
    expect(linkCarriesToken("not a link")).toBe(false);
  });
});

import { ownSkills, type SkillRow } from "./plugins";

describe("ownSkills", () => {
  const row = (name: string, source: SkillRow["source"]): SkillRow => ({ name, description: "", source, status: "ok", tools: [], reason: "" });

  it("keeps the user's skills and leaves Odie's built-in ones out", () => {
    const rows = [row("podcast", "builtin"), row("travel-planner", "user"), row("explainer-video", "builtin"), row("habit-log", "user")];
    expect(ownSkills(rows).map((s) => s.name)).toEqual(["travel-planner", "habit-log"]);
  });

  it("is empty when there are only built-in skills", () => {
    expect(ownSkills([row("podcast", "builtin")])).toEqual([]);
  });
});
