import { describe, expect, it } from "vitest";
import { memoryPlace } from "./memoryPlace";

// Settings' Long-term memory row says where the file is in two short lines: its name, then its folder.
describe("where long-term memory lives, in two short lines", () => {
  it("names the file and its folder, with home as ~", () => {
    expect(memoryPlace("/Users/sam/.odie/memories.md", "")).toEqual({ name: "memories.md", folder: "~/.odie" });
    expect(memoryPlace("/home/sam/.odie/memories.md", "")).toEqual({ name: "memories.md", folder: "~/.odie" });
  });
  it("in the vault, starts the folder at the vault's own name", () => {
    expect(memoryPlace("/Users/sam/Notes Vault/Odie/memories.md", "/Users/sam/Notes Vault"))
      .toEqual({ name: "memories.md", folder: "Notes Vault/Odie" });
    expect(memoryPlace("/Users/sam/Notes Vault/memories.md", "/Users/sam/Notes Vault"))
      .toEqual({ name: "memories.md", folder: "Notes Vault" });
  });
  it("elides the middle of a long folder, keeping where it starts and its last two folders", () => {
    expect(memoryPlace("/private/tmp/runner-7/-Users-sam-work-odie/0f3a9c/scratchpad/check/home/memories.md", ""))
      .toEqual({ name: "memories.md", folder: "/private/…/check/home" });
    expect(memoryPlace("/Users/sam/Library/Application Support/Odie/data/memory/memories.md", ""))
      .toEqual({ name: "memories.md", folder: "~/…/data/memory" });
  });
  it("leaves a short folder whole, and nothing loaded as nothing", () => {
    expect(memoryPlace("/srv/odie/memories.md", "")).toEqual({ name: "memories.md", folder: "/srv/odie" });
    expect(memoryPlace("", "")).toEqual({ name: "", folder: "" });
  });
});
