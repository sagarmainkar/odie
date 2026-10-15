import { describe, expect, it } from "vitest";
import { plainInline, splitInline } from "./inlineSyntax";

describe("inline syntax", () => {
  it("reads badges with and without a tone, and icons", () => {
    expect(splitInline("Pixel :badge[Best]{good} :icon[plane] go")).toEqual([
      { kind: "text", text: "Pixel " }, { kind: "badge", text: "Best", tone: "good" }, { kind: "text", text: " " },
      { kind: "icon", name: "plane" }, { kind: "text", text: " go" }]);
    expect(splitInline(":badge[Sold out]{warn}")).toEqual([{ kind: "badge", text: "Sold out", tone: "warn" }]);
    expect(splitInline(":badge[New]")).toEqual([{ kind: "badge", text: "New", tone: undefined }]);
  });
  it("treats an unknown tone as a plain badge (the braces are not left behind)", () => {
    expect(splitInline(":badge[Hot]{red}!")).toEqual([{ kind: "badge", text: "Hot", tone: undefined }, { kind: "text", text: "!" }]);
  });
  it("keeps braces that hold more than a colour word as text after the badge (Gemma's table cell)", () => {
    expect(splitInline(":badge[Best]{up to 5400 mAh}")).toEqual([{ kind: "badge", text: "Best" }, { kind: "text", text: " up to 5400 mAh" }]);
    expect(splitInline("Battery :badge[Best]{5400mAh}, all day")).toEqual([
      { kind: "text", text: "Battery " }, { kind: "badge", text: "Best" }, { kind: "text", text: " 5400mAh, all day" }]);
    expect(plainInline(":badge[Best]{up to 5400 mAh}")).toBe("Best up to 5400 mAh");
  });
  it("drops an unknown icon and keeps the text around it in one piece", () => {
    expect(splitInline("Fly :icon[rocket]today")).toEqual([{ kind: "text", text: "Fly today" }]);
  });
  it("reads **bold** and https links in block text, but not other links", () => {
    expect(splitInline("**Pixel** at [Flipkart](https://flipkart.example/p)")).toEqual([
      { kind: "bold", text: "Pixel" }, { kind: "text", text: " at " }, { kind: "link", text: "Flipkart", url: "https://flipkart.example/p" }]);
    expect(splitInline("[x](javascript:alert(1))")).toEqual([{ kind: "text", text: "[x](javascript:alert(1))" }]);
  });
  it("leaves bold and links to Markdown when asked", () => {
    expect(splitInline("**a** :badge[b]", { markdown: false })).toEqual([{ kind: "text", text: "**a** " }, { kind: "badge", text: "b", tone: undefined }]);
  });
  it("leaves text without syntax alone, and broken syntax as text", () => {
    expect(splitInline("Just text: [not a badge] {x}")).toEqual([{ kind: "text", text: "Just text: [not a badge] {x}" }]);
    expect(splitInline(":badge[]")).toEqual([{ kind: "text", text: ":badge[]" }]);
    expect(splitInline("")).toEqual([]);
  });
  it("gives the plain words for sorting", () => {
    expect(plainInline(":badge[Best]{good} **Pixel** :icon[star]")).toBe("Best Pixel");
  });
});
