import { describe, expect, it } from "vitest";
import {
  SAME_AS_ODIE, appsUrl, avatarUrl, brainChoiceUrl, brainHeading, canUseLabel, canUseUrl, connectNote, connectUrl, deleteWords, goneWords, modelsUrl,
  personaUrl, pickedBrainSub, sharedCreativityLine, showsCanUse, switchProblem, showsDelete, showsSameAsOdie, showsWhoLine, soulUrl, whoLine,
} from "./settingsPick";

describe("Settings follows the picked personality", () => {
  it("reads and saves the name, the picture and the personality of whoever is picked", () => {
    expect(personaUrl("abc")).toBe("/api/persona?personality=abc");
    expect(avatarUrl("abc")).toBe("/api/persona/avatar?personality=abc");
    expect(soulUrl("abc")).toBe("/api/soul?personality=abc");
  });

  it("says so for everyday Odie too, with an empty pick", () => {
    expect(personaUrl("")).toBe("/api/persona?personality=");
    expect(soulUrl("")).toBe("/api/soul?personality=");
  });

  it("offers Delete for a personality, never for Odie", () => {
    expect(showsDelete("abc")).toBe(true);
    expect(showsDelete("")).toBe(false);
  });

  it("says who is being edited once there is someone else to edit", () => {
    expect(showsWhoLine("", 0)).toBe(false);  // no personalities: Settings looks as it always has
    expect(showsWhoLine("", 2)).toBe(true);
    expect(showsWhoLine("abc", 1)).toBe(true);
    expect(whoLine("Mira")).toBe("Editing Mira");
  });

  it("asks before deleting, in words that say what goes and what Odie can't reach", () => {
    const rest = " Its threads, memory, instructions and picture are erased for good, and so are the debug copies of recent "
      + "model requests. Not erased: log lines, and anything already sent to a tracing service.";
    expect(deleteWords("Mira", 4)).toBe("Delete Mira and its 4 threads?" + rest);
    expect(deleteWords("Mira", 1)).toBe("Delete Mira and its 1 thread?" + rest);
    expect(deleteWords("Mira", 0)).toBe("Delete Mira?" + rest);
  });
});

describe("Settings → Brain follows the picked personality", () => {
  it("reads and picks the brain of whoever is picked, saying who even for Odie", () => {
    expect(modelsUrl("abc")).toBe("/api/models?personality=abc");
    expect(modelsUrl("")).toBe("/api/models?personality=");
    expect(brainChoiceUrl("abc")).toBe("/api/models/selection?personality=abc");
    expect(brainChoiceUrl("")).toBe("/api/models/selection?personality=");
  });

  it("offers \"Same as Odie\" first for a personality, never for Odie", () => {
    expect(showsSameAsOdie("abc")).toBe(true);
    expect(showsSameAsOdie("")).toBe(false);
    expect(SAME_AS_ODIE).toBe("Same as Odie");
  });

  it("says whose brain the card shows", () => {
    expect(brainHeading("Mira")).toBe("Mira is using");
    expect(brainHeading("Odie")).toBe("Odie is using");
  });

  it("words the Settings row for a personality's brain", () => {
    const same = { provider: "lmstudio", model: "lmstudio-community/gemma-4", same_as_odie: true, gone: false, reachable: true };
    expect(pickedBrainSub(same, "LM Studio")).toBe("Same as Odie · gemma-4 · LM Studio");
    const own = { provider: "work-box", model: "qwen3.8", same_as_odie: false, gone: false, reachable: true };
    expect(pickedBrainSub(own, "Work box")).toBe("qwen3.8 · Work box");
    expect(pickedBrainSub({ ...own, reachable: false }, "Work box")).toBe("qwen3.8 · Work box isn't reachable");
    expect(pickedBrainSub({ ...own, gone: true, reachable: false }, "work-box")).toBe("qwen3.8 · isn't set up any more: pick another");
  });

  it("words the line when a personality's own brain is gone", () => {
    expect(goneWords("Mira")).toBe("Mira's brain isn't set up any more, so Mira won't answer. Pick another below, or Same as Odie.");
  });
});

describe("Connected apps follow the picked personality", () => {
  it("lists, adds and connects apps for whoever is picked", () => {
    expect(appsUrl("abc")).toBe("/api/mcp?personality=abc");
    expect(appsUrl("")).toBe("/api/mcp?personality=");
    expect(connectUrl("abc")).toBe("/api/mcp/connect?personality=abc");
  });

  it("flips one app's switch for whoever is picked", () => {
    expect(canUseUrl("work-mail", "abc")).toBe("/api/mcp/work-mail/access?personality=abc");
    expect(canUseUrl("work-mail", "")).toBe("/api/mcp/work-mail/access?personality=");
    expect(canUseLabel("Mira")).toBe("Mira can use this");
    expect(canUseLabel("Odie")).toBe("Odie can use this");
  });

  it("shows that switch once there is someone else to switch it for, or when the app is off for the picked one", () => {
    expect(showsCanUse("", 0, true)).toBe(false);  // no personalities: the list looks as it always has
    expect(showsCanUse("", 1, true)).toBe(true);
    expect(showsCanUse("abc", 1, true)).toBe(true);
    expect(showsCanUse("", 0, false)).toBe(true);  // off for Odie with no one else around: the switch to turn it on
  });
});

describe("Connecting a service again says what it will do", () => {
  const zapier = (canUse: boolean, onlyPick: boolean) => ({ title: "Zapier", canUse, onlyPick });
  it("replaces a connection only the picked one uses", () => {
    expect(connectNote([zapier(true, true)], "Zapier", "Odie")).toBe(
      "This replaces your Zapier connection: the new link and code take the old ones' place, and its switches stay.");
  });

  it("gives the picked one its own when the one there is shared or someone else's", () => {
    expect(connectNote([zapier(true, false)], "Zapier", "Mira")).toBe(
      "Mira gets a Zapier connection of its own; the one there is left as it is.");
    expect(connectNote([zapier(false, false)], "Zapier", "Mira")).toBe(
      "Mira gets a Zapier connection of its own; the one there is left as it is.");
  });

  it("says nothing when there is none yet", () => {
    expect(connectNote([], "Zapier", "Mira")).toBe("");
  });
});

describe("Creativity under a personality", () => {
  it("says it is shared with everyday Odie", () => {
    expect(sharedCreativityLine("Mira")).toBe("Shared with everyday Odie: this one setting is for Mira and Odie alike.");
  });
});

describe("A refused app switch says why", () => {
  it("shows the server's words, such as a second connection of a service", () => {
    const words = "Mira already has these tools from 'mail-2'; switch that one off for Mira first.";
    expect(switchProblem(new Error(words))).toBe(words);
  });

  it("says something plain when there are no words", () => {
    expect(switchProblem(new Error(""))).toBe("That didn't change. Try again.");
    expect(switchProblem("nope")).toBe("That didn't change. Try again.");
  });
});
