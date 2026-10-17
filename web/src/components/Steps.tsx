import { useState } from "react";
import { Icon, Tile, toolTile } from "./Tile";

export type Tool = { name: string; done: boolean };

// Past tense once a tool finished, present tense while it runs.
const TOOL_LABEL: Record<string, [string, string]> = {
  gmail_search: ["Searching mail", "Searched mail"], gmail_read: ["Reading the email", "Read the email"], gmail_read_thread: ["Reading the thread", "Read the thread"],
  gmail_label: ["Labelling", "Labelled"], gmail_create_draft: ["Drafting", "Drafted"], search_notes: ["Searching your notes", "Searched your notes"], search_everything: ["Searching your notes and photos", "Searched your notes and photos"],
  read_note: ["Reading a note", "Read a note"], task_add: ["Adding to your threads", "Added to your threads"], task_update: ["Updating a thread", "Updated a thread"],
  task_list: ["Checking threads", "Checked threads"], now: ["Checking the time", "Checked the time"], calendar_list_events: ["Checking calendar", "Checked calendar"],
  calendar_find_free: ["Looking for a slot", "Looked for a slot"], life_admin: ["Checking your ledger", "Checked your ledger"],
  fetch_memory: ["Recalling", "Recalled a memory"], search_memories: ["Searching memory", "Searched memory"], update_memory: ["Remembering", "Remembered that"],
  run_shell: ["Running a command", "Ran a command"], web_search: ["Searching the web", "Searched the web"], web_fetch: ["Reading a page", "Read a page"],
  gmail_send_draft: ["Sending", "Sent the email"], gmail_trash: ["Moving to Trash", "Moved to Trash"], calendar_create_event: ["Creating an event", "Created an event"],
  calendar_respond: ["Replying to the invite", "Replied to the invite"], market_history: ["Checking markets", "Checked markets"],
  speak: ["Recording", "Recorded"], browser_open: ["Opening the page", "Opened a page"], browser_click: ["Clicking", "Clicked"],
  browser_type: ["Typing", "Typed"], browser_scroll: ["Scrolling", "Scrolled"], browser_sign_in: ["Asking you to sign in", "Asked you to sign in"], find_images: ["Finding photos", "Found photos"], find_clips: ["Finding clips", "Found clips"],
  make_file: ["Making the file", "Made a file"], attach_file: ["Attaching", "Attached a file"],
  make_slides: ["Making the slides", "Made the slides"], make_document: ["Writing the document", "Wrote the document"],
  load_skill: ["Loading a skill", "Loaded a skill"], unload_skill: ["Putting a skill away", "Put a skill away"],
  odie_features: ["Checking what I can do", "Checked what I can do"], related_notes: ["Finding related notes", "Found related notes"],
  quarterly_financials: ["Reading the results", "Read the results"], build_report: ["Building the report", "Built the report"],
  track: ["Starting a tracker", "Started a tracker"], list_trackers: ["Checking trackers", "Checked trackers"], stop_tracker: ["Stopping a tracker", "Stopped a tracker"],
  skill_guide: ["Reading the skill guide", "Read the skill guide"], read_skill: ["Reading a skill", "Read a skill"],
  draft_skill: ["Drafting a skill", "Drafted a skill"], install_skill: ["Installing a skill", "Installed a skill"],
};

/** A tool's step in words: its own label, else its name made readable, so a raw id never shows.
 *    {name: "web_search", done: true}           -> "Searched the web"
 *    {name: "GMAIL_FETCH_EMAILS", done: false}  -> "Using gmail fetch emails"
 *    {name: "GMAIL_FETCH_EMAILS", done: true}   -> "Used gmail fetch emails" */
export function toolLabel(t: Tool): string {
  const known = TOOL_LABEL[t.name];
  if (known) return known[t.done ? 1 : 0];
  const words = t.name.replace(/[_-]+/g, " ").trim().toLowerCase();
  return `${t.done ? "Used" : "Using"} ${words}`;
}

/** "Searched mail, checked calendar": each distinct step once, in the order it happened. */
export function stepsSummary(tools: Tool[]): string {
  const labels = [...new Set(tools.map((t) => toolLabel({ ...t, done: true })))];
  return labels.map((l, i) => (i ? l.charAt(0).toLowerCase() + l.slice(1) : l)).join(", ");
}

/** What the assistant did, as a trace (after Beautiful UI's ThinkingState, MIT, © 2026 Shane Levine): a shimmering
 * header while it works, steps fading in along a thin line (spinner, then a tick), and once done a quiet summary that
 * opens to show them again. */
export function Steps({ tools, running }: { tools: Tool[]; running: boolean }) {
  const [manual, setManual] = useState<boolean | null>(null);
  if (!tools.length) return null;
  const current = [...tools].reverse().find((t) => !t.done);
  const working = running && !!current;
  const open = manual ?? working;  // open while it works, folds itself when done; a tap decides from then on
  const title = working ? `${toolLabel(current!)}…` : stepsSummary(tools);
  return (
    <div className="flex flex-col py-0.5">
      <button type="button" onClick={() => setManual(!open)} aria-expanded={open}
        className="-mx-1.5 flex w-fit max-w-full min-h-9 items-center gap-2 rounded-[10px] px-1.5 py-1 text-left active:bg-well">
        <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true" className="shrink-0" style={{ fill: working ? "var(--t-ink-2)" : "var(--t-dim)" }}>
          <path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z" />
        </svg>
        <span role="status" className={`min-w-0 truncate text-[13.5px] font-semibold ${working ? "shimmer-text" : "text-ink-2 trace-fade"}`}>{title}</span>
        {!working && <span className="shrink-0 text-[12px] text-dim">{tools.length} step{tools.length > 1 ? "s" : ""}</span>}
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--t-dim)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"
          className="shrink-0 transition-transform duration-300" style={{ transform: open ? "rotate(180deg)" : "none" }} aria-hidden="true">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      <div className="grid transition-[grid-template-rows,opacity] duration-[400ms]" style={{ gridTemplateRows: open ? "1fr" : "0fr", opacity: open ? 1 : 0, transitionTimingFunction: "cubic-bezier(.23,1,.32,1)" }}>
        <div className="overflow-hidden">
          <div className="relative mt-0.5 ml-[6px] pl-4">
            <span aria-hidden="true" className="absolute left-[2px] top-1 bottom-2 w-px bg-line-2" />
            <div className="flex flex-col gap-0.5 py-1">
              {tools.map((t, i) => {
                const k = toolTile(t.name);
                const spinning = running && !t.done;
                return (
                  <div key={i} className="trace-row flex min-h-7 items-center gap-2 text-[13px]" style={{ animationDelay: `${Math.min(i, 6) * 60}ms` }}>
                    {spinning ? <span className="size-3 shrink-0 rounded-full border-[1.5px] border-line-2 border-t-ink-2 animate-spin" />
                      : <span className="shrink-0 text-dim"><Icon name="check" size={13} stroke={2.6} /></span>}
                    <span className={`min-w-0 truncate ${spinning ? "text-ink font-medium" : "text-ink-2"}`}>{toolLabel(t)}</span>
                    <span className="shrink-0 opacity-70"><Tile icon={k.icon} color={k.color} small /></span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
