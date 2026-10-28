// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ThinkChip, ThinkSwitch } from "./ThinkHarder";

describe("the Think harder chip by the composer", () => {
  it("shows while the chat thinks harder", () => {
    const html = renderToStaticMarkup(<ThinkChip on={true} onTap={() => {}} />);
    expect(html).toContain("Think harder");
    expect(html).toContain('aria-label="Think harder is on for this chat"');
  });

  it("is nothing when it's off", () => {
    expect(renderToStaticMarkup(<ThinkChip on={false} onTap={() => {}} />)).toBe("");
  });
});

describe("the + menu switch", () => {
  it("says whether it's on", () => {
    expect(renderToStaticMarkup(<ThinkSwitch on={true} disabled={false} onToggle={() => {}} />)).toContain('aria-checked="true"');
    expect(renderToStaticMarkup(<ThinkSwitch on={false} disabled={false} onToggle={() => {}} />)).toContain('aria-checked="false"');
  });

  it("is held while a change is saved", () => {
    expect(renderToStaticMarkup(<ThinkSwitch on={false} disabled={true} onToggle={() => {}} />)).toContain("disabled");
    expect(renderToStaticMarkup(<ThinkSwitch on={false} disabled={false} onToggle={() => {}} />)).not.toContain("disabled=\"\"");
  });
});
