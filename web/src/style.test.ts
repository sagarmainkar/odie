// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { applyStyle, barColour, getStyle, initLook, lookNote, shownStyle } from "./theme";

// The style (Glass or Newspaper) under the look: kept in this browser's storage, shown as data-style on <html>.
beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.style;
  document.head.innerHTML = '<meta name="theme-color" content="#000000">';
});
afterEach(() => localStorage.clear());

const bar = () => document.querySelector('meta[name="theme-color"]')?.getAttribute("content");

describe("the style", () => {
  it("is Glass by default, and Glass puts nothing on the page", () => {
    expect(getStyle()).toBe("glass");
    initLook();
    expect(document.documentElement.hasAttribute("data-style")).toBe(false);
    expect(shownStyle()).toBe("glass");
    expect(["#F7F3EE", "#F3F5F9", "#F6F1F0", "#110F18"]).toContain(bar());  // one of Glass's washes, as before
  });

  it("keeps Newspaper and shows it on <html>, with the paper's colour in the browser bar", () => {
    applyStyle("paper");
    expect(localStorage.getItem("odie.style")).toBe("paper");
    expect(document.documentElement.dataset.style).toBe("paper");
    expect(shownStyle()).toBe("paper");
    expect(["#F3F2EE", "#1E1D1B"]).toContain(bar());
  });

  it("comes back as Newspaper on the next start", () => {
    localStorage.setItem("odie.style", "paper");
    initLook();
    expect(document.documentElement.dataset.style).toBe("paper");
  });

  it("goes back to Glass: the attribute and the stored choice both go", () => {
    applyStyle("paper");
    applyStyle("glass");
    expect(document.documentElement.hasAttribute("data-style")).toBe(false);
    expect(localStorage.getItem("odie.style")).toBeNull();
  });

  it("reads anything else stored as Glass", () => {
    localStorage.setItem("odie.style", "sepia");
    expect(getStyle()).toBe("glass");
  });

  it("tells the screens when it changes", () => {
    let heard = 0;
    const hear = () => { heard += 1; };
    window.addEventListener("odie:style", hear);
    applyStyle("paper");
    window.removeEventListener("odie:style", hear);
    expect(heard).toBe(1);
  });
});

describe("barColour", () => {
  it("keeps Glass's washes and gives Newspaper its paper or the dark edition", () => {
    expect(barColour("dawn", "glass")).toBe("#F7F3EE");
    expect(barColour("night", "glass")).toBe("#110F18");
    expect(barColour("noon", "paper")).toBe("#F3F2EE");
    expect(barColour("evening", "paper")).toBe("#F3F2EE");
    expect(barColour("night", "paper")).toBe("#1E1D1B");
  });
});

describe("lookNote", () => {
  it("explains Glass's washes, or Newspaper's two editions", () => {
    expect(lookNote("glass")).toContain("warm in the morning, sky at noon, rose in the evening");
    expect(lookNote("paper")).toContain("the dark edition in dark mode");
  });
});
