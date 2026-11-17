import { describe, expect, it } from "vitest";
import type { Approval } from "./components/ApprovalCard";
import { CHAT_PASS_BUTTON, chatPassNote, chatPassScope, kindWords } from "./chatPass";

const card: Approval = {
  id: 7, tool: "run_shell", summary: "Run a command", status: "pending", risk: "normal",
  detail: { command: "rm ~/old-notes/a.md", asks_because: "deletes or stops something", chat_pass: true },
};

describe("kindWords", () => {
  it("says each kind a pass may cover in plain words", () => {
    expect(kindWords("deletes or stops something")).toBe("deleting or stopping things");
    expect(kindWords("writes a file from code")).toBe("writing files from code");
    expect(kindWords("sets something to run later or at login")).toBe("setting things to run later or at login");
    expect(kindWords("edits files in place")).toBe("editing files in place");
    expect(kindWords("writes a file outside /tmp")).toBe("writing files outside ordinary folders");
    expect(kindWords("replaces a file")).toBe("replacing files");
  });
  it("knows no words for a kind that never gets a pass, or for nothing", () => {
    expect(kindWords("reads secrets")).toBeNull();
    expect(kindWords("installs software (runs its install scripts)")).toBeNull();
    expect(kindWords("runs text as commands")).toBeNull();
    expect(kindWords("sends data out")).toBeNull();
    expect(kindWords("touches Odie's own files")).toBeNull();
    expect(kindWords(undefined)).toBeNull();
    expect(kindWords(3)).toBeNull();
  });
});

describe("chatPassScope", () => {
  it("is offered on a Smart shell card the server marked, with the kind in words", () => {
    expect(chatPassScope(card, true)).toBe("Only for deleting or stopping things, only in this chat. Everything else still asks.");
  });
  it("is not offered in Careful, unmarked, for another tool, after reading mail, or for a kind it can't name", () => {
    expect(chatPassScope(card, false)).toBeNull();
    expect(chatPassScope({ ...card, detail: { ...card.detail, chat_pass: false } }, true)).toBeNull();
    expect(chatPassScope({ ...card, tool: "GMAIL_SEND_EMAIL" }, true)).toBeNull();
    expect(chatPassScope({ ...card, risk: "from_email", provenance: [{ from: "a@example.com", subject: "hi" }] }, true)).toBeNull();
    expect(chatPassScope({ ...card, risk: "unknown" }, true)).toBeNull();
    expect(chatPassScope({ ...card, detail: { ...card.detail, asks_because: "reads secrets" } }, true)).toBeNull();
    expect(chatPassScope({ ...card, detail: null }, true)).toBeNull();
  });
  it("has one plain button label", () => {
    expect(CHAT_PASS_BUTTON).toBe("Run it, and don't ask again in this chat for 30 min");
  });
});

describe("chatPassNote", () => {
  it("says until when this chat won't ask for that kind", () => {
    expect(chatPassNote("deletes or stops something", "12:31")).toBe("Until 12:31 (or until Odie restarts), this chat won't ask again for deleting or stopping things.");
  });
  it("falls back to plain words for a kind it doesn't know", () => {
    expect(chatPassNote("something new", "12:31")).toBe("Until 12:31 (or until Odie restarts), this chat won't ask again for this kind of command.");
  });
});
