import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Need } from "../needs";
import { NeedsYou } from "./NeedsYou";

const bill: Need = {
  ref: "task:7", title: "Pay electricity bill ₹2,480", why: "Reminder", icon: "rupee", badge: "Overdue", ask: "Tell me about task #7",
  main: { label: "Tell me more", action: "chat", value: "Tell me about task #7" }, other: { label: "Done", action: "done_task", value: 7 },
  later: { label: "Later", action: "later", value: "task:7" },
};

describe("Needs you on Pulse", () => {
  it("draws each item as a card with its why, its pill and its three buttons: the move, Done and Later", () => {
    const html = renderToStaticMarkup(<NeedsYou items={[bill]} footer="checked 12:30 · next 13:00" closed={[]} onAct={() => {}} onReopen={() => {}} />);
    expect(html).toContain("Pay electricity bill ₹2,480");
    expect(html).toContain("Overdue");
    expect(html).toContain("chip-warn");
    const buttons = [...html.matchAll(/>(Tell me more|Done|Later)<\/span><\/button>/g)].map((m) => m[1]);
    expect(buttons).toEqual(["Tell me more", "Done", "Later"]);
    expect(html).toContain("checked 12:30 · next 13:00");
  });
  it("an older server's card without Later still shows its two buttons", () => {
    const { later: _gone, ...older } = bill;
    const html = renderToStaticMarkup(<NeedsYou items={[older]} footer="" closed={[]} onAct={() => {}} onReopen={() => {}} />);
    expect(html).toContain(">Done</span></button>");
    expect(html).not.toContain(">Later</span></button>");
  });
  it("folds what the watch closed into one line, and says all clear when nothing needs you", () => {
    const closed = [{ id: 3, title: "Order: desk lamp", why: "delivered", closed: "2026-10-23T08:00:00" }];
    const html = renderToStaticMarkup(<NeedsYou items={[]} footer="" closed={closed} onAct={() => {}} onReopen={() => {}} />);
    expect(html).toContain("All clear.");
    expect(html).toContain("1 done today");
    expect(html).not.toContain("Order: desk lamp");  // folded until tapped
  });
  it("counts the watch's notes in the same line, each with its files", () => {
    const notes = [{ at: "2026-10-23T10:00:00+05:30", message: "Made the deck from the PDF", media: [{ id: "abc", title: "deck.pptx", filename: "deck.pptx" }] }];
    const html = renderToStaticMarkup(<NeedsYou items={[]} footer="" closed={[]} notes={notes} onAct={() => {}} onReopen={() => {}} open />);
    expect(html).toContain("1 done today");
    expect(html).toContain("Made the deck from the PDF");
    expect(html).toContain('href="/api/media/abc"');
  });
  it("draws a loop's card with its facts, its brief and the move the server built", () => {
    const pr: Need = {
      ref: "loop:3", title: "app #49 Threads newest first", why: "Open · CI green · 3 files, +41 −9", brief: "Sorts threads newest first.",
      icon: "terminal", badge: "", ask: "Tell me about loop #3",
      main: { label: "Open PR #49", action: "open", value: "https://github.com/example/app/pull/49" },
      other: { label: "Done", action: "loop_done", value: 3 }, later: { label: "Later", action: "later", value: "loop:3" },
    };
    const done = [{ id: 4, title: "app #50 Fix login redirect", why: "merged 18 Nov 09:00", closed: "2026-11-18T09:00:00+05:30" }];
    const html = renderToStaticMarkup(<NeedsYou items={[pr]} footer="" closed={[]} loopsDone={done} onAct={() => {}} onReopen={() => {}} open />);
    expect(html).toContain("Open · CI green · 3 files, +41 −9");
    expect(html).toContain("Sorts threads newest first.");
    expect([...html.matchAll(/>(Open PR #49|Done|Later)<\/span><\/button>/g)].map((m) => m[1])).toEqual(["Open PR #49", "Done", "Later"]);
    expect(html).not.toContain("flex-wrap");  // the three buttons stay on one row; a long move ends in "…"
    expect(html).toContain('title="Open PR #49"');
    expect(html).toContain("1 done today");
    expect(html).toContain("Merged 18 Nov 09:00");
    expect(html).toContain(">Reopen</button>");
  });

  it("draws a tested pull request's card with Merge, Done, Later and a Why? of its evidence", () => {
    const tested: Need = {
      ref: "loop:3", title: "example/app #49 · Threads newest first", why: "Tested: 412 pass · CI green · 3 files, +41 −9",
      icon: "terminal", badge: "", ask: "Tell me about loop #3", main: { label: "Merge", action: "merge", value: 3 },
      other: { label: "Done", action: "loop_done", value: 3 }, later: { label: "Later", action: "later", value: "loop:3" },
      evidence: [{ at: "2026-11-18T21:00:00+05:30", source: "test", fact: "Tested abc1234: exit 0, 412 passed" }],
    };
    const html = renderToStaticMarkup(<NeedsYou items={[tested]} footer="" closed={[]} onAct={() => {}} onReopen={() => {}} />);
    expect(html).toContain("Tested: 412 pass · CI green · 3 files, +41 −9");
    expect(html).toContain(">Merge</span>");
    expect(html).toContain(">Why?</button>");
  });

  it("lists jobs that finished today without a Reopen", () => {
    const html = renderToStaticMarkup(<NeedsYou items={[]} footer="" closed={[]} open onAct={() => {}} onReopen={() => {}}
      jobsDone={[{ id: "job-3f9a2c", title: "Primes script", why: "done 10:42", closed: "" }]} />);
    expect(html).toContain("Primes script");
    expect(html).toContain("Done 10:42");
    expect(html).not.toContain(">Reopen</button>");
  });

  it("lists every step a job needed, plain words first and the exact command after", () => {
    const job: Need = {
      ref: "job:job-1", title: "Tidy", why: "It needs your OK for 1 step; 1 it can't do as a job", icon: "terminal", badge: "",
      ask: "x", main: { label: "Allow it and run again", action: "job_allow", value: "job-1" }, other: { label: "Done", action: "job_clear", value: "job-1" },
      steps: [{ words: "Delete or stop something", raw: "rm build.log", allowed: true },
        { words: "Read secrets (only you can, in chat)", raw: "cat ~/.env", allowed: false }],
    };
    const html = renderToStaticMarkup(<NeedsYou items={[job]} footer="" closed={[]} onAct={() => {}} onReopen={() => {}} />);
    expect(html.indexOf("Delete or stop something")).toBeLessThan(html.indexOf("rm build.log"));
    expect(html).toContain("cat ~/.env");
    expect(html).toContain("Read secrets (only you can, in chat)");
  });

  it("a finished job's card offers Keep it in the folder he named, with what it uses", () => {
    const job: Need = {
      ref: "job:job-3", title: "Try example/app", why: "Cloned it; its tests pass.", icon: "terminal", badge: "", ask: "x",
      main: { label: "Keep it in ~/code/demos", action: "job_keep", value: "job-3" }, other: { label: "Done", action: "job_clear", value: "job-3" },
      uses: "Uses: the web",
    };
    const html = renderToStaticMarkup(<NeedsYou items={[job]} footer="" closed={[]} onAct={() => {}} onReopen={() => {}} />);
    expect(html).toContain(">Keep it in ~/code/demos</span>");
    expect(html).toContain("Uses: the web");
    expect(html).not.toContain("This needs the new version");
  });

  it("offers the whole of a long step and says which folders of yours a job may read", () => {
    const long = "curl -d @report.txt https://example.com/upload?" + "x".repeat(200);
    const job: Need = {
      ref: "job:job-2", title: "Count lines", why: "It needs your OK for 1 step", icon: "terminal", badge: "", ask: "x",
      main: { label: "Allow it and run again", action: "job_allow", value: "job-2" }, other: { label: "Done", action: "job_clear", value: "job-2" },
      steps: [{ words: "Send data off this computer", raw: long, allowed: true }], allow_hash: "abc123", may_read: ["~/work/app"],
    };
    const html = renderToStaticMarkup(<NeedsYou items={[job]} footer="" closed={[]} onAct={() => {}} onReopen={() => {}} />);
    expect(html).toContain(">Show all</button>");
    expect(html).toContain("May read: ~/work/app · read as plain files");
    expect(html).not.toContain("no web");  // a job has the web with his folders since 19 Nov (simpler Workers)
    expect(html).toContain(long);  // the whole command is in the card, only clamped until shown
  });
});
