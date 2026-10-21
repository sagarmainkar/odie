// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { macAppLine, onAMac } from "../mac";
import { MacAppsBlock } from "./MacAppsBlock";
import { SourceBadges } from "./SourceBadges";

const data = { mac: true, default_calendar: "", apps: [
  { id: "mail", name: "Mail", status: "granted" as const }, { id: "calendar", name: "Calendar", status: "unknown" as const },
  { id: "reminders", name: "Reminders", status: "denied" as const }, { id: "contacts", name: "Contacts", status: "unknown" as const }] };

describe("the Mac apps rows", () => {
  it("know a Mac from a phone", () => {
    expect(onAMac("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) Safari/605", 0)).toBe(true);
    expect(onAMac("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) Safari/605", 5)).toBe(false);  // an iPad asking for the desktop site
    expect(onAMac("Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X)", 5)).toBe(false);
  });

  it("say the state in words", () => {
    expect(macAppLine("granted", true)).toBe("Allowed");
    expect(macAppLine("unknown", true)).toBe("Not asked yet");
    expect(macAppLine("unknown", false)).toBe("Allow this on the Mac");
    expect(macAppLine("denied", false)).toBe("Refused on the Mac");
  });

  it("offer Allow on a Mac for what isn't granted, and only look from a phone", () => {
    const mac = renderToStaticMarkup(<MacAppsBlock data={data} onChange={() => {}} mac={true} />);
    expect(mac).toContain('aria-label="Allow Calendar"');
    expect(mac).toContain('aria-label="Allow Reminders"');
    expect(mac).not.toContain('aria-label="Allow Mail"');
    expect(mac).toContain("Not asked yet");
    const phone = renderToStaticMarkup(<MacAppsBlock data={data} onChange={() => {}} mac={false} />);
    expect(phone).not.toContain("Allow Calendar");
    expect(phone).toContain("Allow this on the Mac");
  });

  it("show the calendar picker only once Calendar is allowed", () => {
    expect(renderToStaticMarkup(<MacAppsBlock data={data} onChange={() => {}} mac={true} />)).not.toContain("Events Odie adds go into");
    const allowed = { ...data, apps: data.apps.map((a) => a.id === "calendar" ? { ...a, status: "granted" as const } : a) };
    expect(renderToStaticMarkup(<MacAppsBlock data={allowed} onChange={() => {}} mac={true} />)).toContain("Events Odie adds go into");
  });
});

describe("source badges", () => {
  it("draw a mark per source and nothing for none", () => {
    expect(renderToStaticMarkup(<SourceBadges badges={[]} />)).toBe("");
    const two = renderToStaticMarkup(<SourceBadges badges={[{ kind: "gmail", app: "Gmail and Calendar" }, { kind: "icloud", app: "Calendar" }, { kind: "app", app: "Zapier" }]} />);
    expect(two).toContain('aria-label="Gmail and Calendar, Calendar, Zapier"');
    expect(two).toContain("Zapier");
  });
});
