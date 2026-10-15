// Screenshots of every screen at phone width, light and dark, for a look before a release. Run through
// scripts/screens.sh, which starts a throwaway Odie for it; by hand:
//   node web/scripts/screens.mjs <odie address> <folder> [screens, e.g. today,settings]
// Uses the Chrome (or Edge) already on the computer. Writes one PNG per screen and theme, plus report.txt: anything
// wider than the phone, and buttons or links smaller than 36 px to tap.
import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { chromium } from "playwright-core";

const [base, out, only] = process.argv.slice(2);
if (!base || !out) {
  console.error("usage: node web/scripts/screens.mjs <odie address> <folder>");
  process.exit(2);
}
mkdirSync(out, { recursive: true });

const ALL = ["setup", "today", "chat", "sample", "brain", "settings"];
const SCREENS = only ? only.split(",") : ALL;
const SETTINGS_PANELS = ["Providers", "Web search", "Skills", "Connected apps"];  // opened one at a time on Settings
const PHONE = { width: 390, height: 844 };
const LONG = { width: 390, height: 2600 };  // the app scrolls inside its screens, so a tall window shows a whole one

async function launch() {
  for (const channel of ["chrome", "msedge"]) {
    try { return await chromium.launch({ channel }); } catch { /* try the next one */ }
  }
  throw new Error("No Chrome or Edge found: install one, or run this where one is.");
}

/** What a reviewer should look at on the page as it is now: the width it really takes, and tap targets under 36 px
 *  (Apple asks for 44; 36 is where a thumb starts missing). */
async function problems(page) {
  return page.evaluate(() => {
    const SMALL = 36;
    const found = [];
    if (document.documentElement.scrollWidth > window.innerWidth + 1) {
      found.push(`wider than the phone: ${document.documentElement.scrollWidth}px`);
    }
    for (const el of document.querySelectorAll("button, a, input, select, [role=switch]")) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      if (r.height < SMALL || r.width < SMALL) {
        const name = (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || "").trim().slice(0, 40);
        found.push(`small tap target ${Math.round(r.width)}x${Math.round(r.height)}: "${name}"`);
      }
    }
    return found;
  });
}

async function shoot(browser, scheme, size, tag, report) {
  const context = await browser.newContext({ viewport: size, deviceScaleFactor: 2, colorScheme: scheme, serviceWorkers: "block" });
  const page = await context.newPage();
  for (const screen of SCREENS) {
    await page.goto(`${base}/#${screen}`, { waitUntil: "networkidle" }).catch(() => {});
    await page.waitForTimeout(1200);
    await page.screenshot({ path: join(out, `${screen}-${scheme}-${tag}.png`) });
    if (scheme === "light" && tag === "phone") report.push([screen, await problems(page)]);
  }
  const panels = SCREENS.includes("settings") ? SETTINGS_PANELS : [];
  for (const panel of panels) {
    await page.goto(`${base}/#settings`, { waitUntil: "networkidle" }).catch(() => {});
    await page.waitForTimeout(800);
    const opened = await page.locator(`button:has-text("${panel}")`).first().click({ timeout: 3000 }).then(() => true, () => false);
    if (!opened) continue;
    await page.waitForTimeout(800);
    const name = panel.toLowerCase().replaceAll(" ", "-");
    await page.screenshot({ path: join(out, `settings-${name}-${scheme}-${tag}.png`) });
  }
  await context.close();
}

const browser = await launch();
const report = [];
for (const scheme of ["light", "dark"]) {
  await shoot(browser, scheme, PHONE, "phone", report);
  await shoot(browser, scheme, LONG, "long", report);
}
await browser.close();
const lines = report.map(([screen, found]) => `${screen}: ${found.length ? "\n  " + found.join("\n  ") : "nothing to look at"}`);
appendFileSync(join(out, "report.txt"), lines.join("\n") + "\n");
console.log(`Screens in ${out} (report.txt lists what to look at).`);
