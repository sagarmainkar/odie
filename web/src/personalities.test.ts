import { describe, expect, it } from "vitest";
import { odieLine, rowLine, somethingElsewhere, type Personality } from "./personalities";

const mira = (more: Partial<Personality> = {}): Personality => ({ id: "abc", name: "Mira", avatar_url: null, threads: 4, waiting: 0, ...more });

describe("rowLine", () => {
  it("says how many threads a personality has", () => {
    expect(rowLine(mira(), undefined)).toBe("4 threads");
    expect(rowLine(mira({ threads: 1 }), undefined)).toBe("1 thread");
    expect(rowLine(mira({ threads: 0 }), undefined)).toBe("No threads yet");
  });

  it("says first when something of hers is waiting", () => {
    expect(rowLine(mira({ waiting: 1 }), undefined)).toBe("needs you");
    expect(rowLine(mira(), "card")).toBe("needs you");
    expect(rowLine(mira(), "reply")).toBe("new");
    expect(rowLine(mira({ waiting: 1 }), "reply")).toBe("needs you");  // a card comes before a reply
  });
});

describe("odieLine", () => {
  it("says everyday, unless something of Odie's waits while a personality is on screen", () => {
    expect(odieLine(undefined)).toBe("everyday");
    expect(odieLine("card")).toBe("needs you");
    expect(odieLine("reply")).toBe("new");
  });
});

describe("somethingElsewhere", () => {
  it("is true when a personality that isn't on screen has a card or a new reply", () => {
    expect(somethingElsewhere([mira({ waiting: 1 })], {}, "")).toBe(true);
    expect(somethingElsewhere([mira()], { abc: "reply" }, "")).toBe(true);
  });

  it("is true when everyday Odie has something while a personality is on screen", () => {
    expect(somethingElsewhere([mira()], { "": "card" }, "abc")).toBe(true);
    expect(somethingElsewhere([mira()], { "": "card" }, "")).toBe(false);  // Odie is the one on screen
  });

  it("is false for the one on screen, and when nothing waits", () => {
    expect(somethingElsewhere([mira({ waiting: 1 })], { abc: "reply" }, "abc")).toBe(false);
    expect(somethingElsewhere([mira()], {}, "")).toBe(false);
  });
});
