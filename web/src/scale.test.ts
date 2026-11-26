import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// The app's type and corner scale (styles.css, @theme): text sizes and radii come from a short list of named steps
// (text-small, rounded-card...) instead of one-off pixel values. This guard reads every .tsx file and fails on an
// arbitrary text-[Npx] or rounded-[Npx] class that isn't one of the named exceptions below.
const SRC = fileURLToPath(new URL(".", import.meta.url));
const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");

// The few sizes the scale leaves alone, each with why. A file listed here may use that class; nothing else may.
const EXCEPTIONS: { file: string; cls: string; why: string }[] = [
  { file: "components/MoneyCard.tsx", cls: "text-[9px]", why: "a bank's initials inside a 36px coin" },
  { file: "screens/Today.tsx", cls: "text-[34px]", why: "Today's greeting, a display line" },
  { file: "screens/Today.tsx", cls: "text-[40px]", why: "the serif word in Today's greeting" },
  { file: "blocks/Rich.tsx", cls: "text-[34px]", why: "a big count, a display number" },
  { file: "components/MorningCard.tsx", cls: "text-[34px]", why: "the temperature, a display number" },
  { file: "components/UpNext.tsx", cls: "text-[84px]", why: "the day of the month, a giant display number" },
  { file: "blocks/Table.tsx", cls: "rounded-[2px]", why: "a bar inside a table cell (a chart mark)" },
  { file: "components/HBarChart.tsx", cls: "rounded-[3px]", why: "a chart's bars" },
  { file: "components/PieChart.tsx", cls: "rounded-[3px]", why: "a chart legend's swatch" },
  { file: "blocks/Form.tsx", cls: "rounded-[2px]", why: "the small square in a ticked box" },
  { file: "screens/Chat.tsx", cls: "rounded-[3px]", why: "the stop square in the dictation button" },
  { file: "components/LocalTalk.tsx", cls: "rounded-[3px]", why: "the stop square in Talk's Interrupt button" },
];

// An arbitrary pixel size or radius, with any variant in front: "text-[13px]", "lg:rounded-[26px]", "rounded-br-[8px]".
const ARBITRARY = /(?:[a-z0-9]+:)*((?:text|rounded(?:-[a-z]+)?)-\[\d+(?:\.\d+)?px\])/g;

/** Every .tsx file under src, as a path relative to src ("screens/Settings.tsx"). */
function tsxFiles(dir: string = SRC): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) found.push(...tsxFiles(path));
    else if (entry.name.endsWith(".tsx")) found.push(relative(SRC, path));
  }
  return found;
}

/** Whether a class found in a file is one of the named exceptions.
 *  "text-[84px]" in components/UpNext.tsx -> true; "text-[84px]" in screens/Chat.tsx -> false;
 *  "text-[13px]" anywhere -> false. */
function allowed(file: string, cls: string): boolean {
  return EXCEPTIONS.some((e) => e.file === file && e.cls === cls);
}

/** The arbitrary classes in one file's text that aren't allowed, as "file: class" lines. */
function strays(file: string, text: string): string[] {
  const out: string[] = [];
  for (const match of text.matchAll(ARBITRARY)) {
    const cls = match[1];
    if (!allowed(file, cls)) out.push(`${file}: ${match[0]}`);
  }
  return out;
}

describe("the type and corner scale", () => {
  it("finds arbitrary classes, variants included, and lets only the named exceptions through", () => {
    expect(strays("screens/Chat.tsx", 'className="text-[13px] lg:rounded-[26px] rounded-br-[8px] text-small"')).toEqual([
      "screens/Chat.tsx: text-[13px]", "screens/Chat.tsx: lg:rounded-[26px]", "screens/Chat.tsx: rounded-br-[8px]"]);
    expect(strays("components/UpNext.tsx", 'className="text-[84px]"')).toEqual([]);
    expect(strays("screens/Chat.tsx", 'className="text-[84px]"')).toEqual(["screens/Chat.tsx: text-[84px]"]);
  });

  it("defines the named steps in styles.css, with replies at 15.5px", () => {
    for (const step of ["tiny", "caption", "small", "ui", "body", "title", "heading", "display-sm", "display", "display-lg"]) {
      expect(css).toMatch(new RegExp(`--text-${step}:\\s*[\\d.]+px;`));
    }
    expect(css).toMatch(/--text-body:\s*15\.5px;/);
    for (const step of ["inner", "control", "tile", "card"]) {
      expect(css).toMatch(new RegExp(`--radius-${step}:\\s*\\d+px;`));
    }
  });

  it("has no arbitrary text-[Npx] or rounded-[Npx] class outside the named exceptions", () => {
    const found = tsxFiles().flatMap((file) => strays(file, readFileSync(join(SRC, file), "utf8")));
    expect(found).toEqual([]);
  });

  it("lists only exceptions that are still in use", () => {
    const unused = EXCEPTIONS.filter((e) => !readFileSync(join(SRC, e.file), "utf8").includes(e.cls));
    expect(unused).toEqual([]);
  });
});
