import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Blocks } from "./Blocks";
import { parseBlocks } from "./parse";
import { avatarColour, initialOf, rowLead } from "./rowAvatar";

function draw(json: unknown): string {
  const code = JSON.stringify(json);
  return renderToStaticMarkup(<Blocks blocks={parseBlocks(code)!} source={code} />);
}

describe("a list row's first letter", () => {
  it("is the first letter of the words a reader sees", () => {
    expect(initialOf("Asha · Lease renewal")).toBe("A");
    expect(initialOf("📦 amazon.in · Your order")).toBe("A");
    expect(initialOf(":badge[New] **ravi**")).toBe("R");
    expect(initialOf("3M · Invoice")).toBe("3");
  });
  it("is null for a title of only emoji or spaces", () => {
    expect(initialOf("🎉🎉")).toBeNull();
    expect(initialOf("   ")).toBeNull();
    expect(initialOf("")).toBeNull();
  });
});

describe("which picture a row leads with", () => {
  it("prefers a photo, then an icon, then the letter", () => {
    expect(rowLead({ title: "Asha", image: "https://x.test/a.jpg", icon: "mail" }, false, false)).toBe("image");
    expect(rowLead({ title: "Asha", icon: "alert" }, false, false)).toBe("icon");
    expect(rowLead({ title: "Asha · Lease renewal" }, false, false)).toBe("initial");
  });
  it("shows the letter when a private chat holds the photo back", () => {
    expect(rowLead({ title: "Asha", image: "https://x.test/a.jpg" }, false, true)).toBe("initial");
  });
  it("shows nothing in a ranked list or for a title with no letter", () => {
    expect(rowLead({ title: "Third Wave" }, true, false)).toBe("none");
    expect(rowLead({ title: "🎉" }, false, false)).toBe("none");
  });
});

describe("the circle's colour", () => {
  it("is the same for a sender in every row, whatever the subject or case", () => {
    expect(avatarColour("Asha · Lease renewal")).toBe(avatarColour("asha · Dinner on Sat"));
    expect(avatarColour("Asha")).toBe(avatarColour("  ASHA "));
  });
  it("is one of the palette's colours, and names spread over them", () => {
    const names = ["Asha", "Ravi", "Meera", "Bank", "Netflix", "Docs", "Kiran", "Zoe", "Uber", "Swiggy"];
    const colours = new Set(names.map(avatarColour));
    for (const c of colours) expect(c).toMatch(/^var\(--t-chart-[1235678]\)$/);
    expect(colours.size).toBeGreaterThan(3);
  });
});

describe("drawing mail rows", () => {
  it("draws a letter circle for a row without an icon, and the icon for a row with one", () => {
    const html = draw([{ type: "list", title: "Needs you", items: [
      { title: "Asha · Lease renewal", subtitle: ":badge[Action] Sign by Friday", value: "11:30am", icon: "alert", run: "Open the email from Asha about the lease renewal" },
      { title: "Ravi · Dinner on Sat", subtitle: "Asks if 8pm works", value: "Yesterday" },
    ] }]);
    expect(html).toContain("rounded-[12px] grid place-items-center bg-ember-tint");  // Asha's alert icon
    expect(html).toMatch(/rounded-full[^>]*background:var\(--t-chart-\d\)[^>]*>R</);  // Ravi's letter
    expect(html).not.toMatch(/rounded-full[^>]*>A</);  // Asha has an icon, so no letter
    expect(html).toContain("chip chip-inline");  // the Action badge
  });
});
