import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TaskRow } from "./Today";

describe("a thread on Today", () => {
  it("draws a mail thread with the sender's letter and a Reply pill, like a chat row", () => {
    const t = { id: 7, title: "Reply to Priya Nair: Can we move our 1:1?", kind: "followup", status: "open", due_at: null, next_check_at: null,
                source_kind: "mail", detail: "from Priya Nair <priya@acme.example>\nCould we move to Thursday?" };
    const html = renderToStaticMarkup(<TaskRow t={t} onDone={() => {}} onSnooze={() => {}} />);
    expect(html).toContain(">P</span>");
    expect(html).toContain("Priya Nair · Can we move our 1:1?");
    expect(html).toContain("chip-inline");
    expect(html).toContain("Could we move to Thursday?");
  });
});
