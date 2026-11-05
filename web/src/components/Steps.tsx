import { useState } from "react";
import { Icon } from "./Tile";
import { allowedPill, argLine, metaLine, outputHead, type Tool } from "../steps";

export type { Tool };

// Past tense once a tool finished, present tense while it runs.
const TOOL_LABEL: Record<string, [string, string]> = {
  gmail_search: ["Searching mail", "Searched mail"], gmail_read: ["Reading the email", "Read the email"], gmail_read_thread: ["Reading the thread", "Read the thread"],
  gmail_label: ["Labelling", "Labelled"], gmail_create_draft: ["Drafting", "Drafted"], search_notes: ["Searching your notes", "Searched your notes"], search_everything: ["Searching your notes and photos", "Searched your notes and photos"],
  read_note: ["Reading a note", "Read a note"], task_add: ["Adding to your threads", "Added to your threads"], task_update: ["Updating a thread", "Updated a thread"],
  task_list: ["Checking threads", "Checked threads"], now: ["Checking the time", "Checked the time"], calendar_list_events: ["Checking calendar", "Checked calendar"],
  calendar_find_free: ["Looking for a slot", "Looked for a slot"], life_admin: ["Checking your ledger", "Checked your ledger"],
  fetch_memory: ["Recalling", "Recalled a memory"], recall: ["Looking back", "Looked back"], update_memory: ["Remembering", "Remembered that"],
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

/** The pill's colours by who let the step run: your tap in the brand's tint, a pass in green, a refusal in red.
 *    allowed {by: "you"} -> brand tint;  allowed {by: "pass"} -> green;  state "no" -> red */
function pillTone(t: Tool): string {
  if (t.state === "no" || t.allowed?.by === "no") return "bg-bad-tint text-bad";
  if (t.allowed?.by === "pass") return "bg-good-tint text-good";
  return "bg-ember-tint text-ember-text";
}

/** Whether a step has output to open: it ran (not refused) and printed something.
 *    run_shell, result "a.txt\nb.txt"   -> yes (a tap shows the two lines)
 *    run_shell, result ""                -> no  (its meta line says No output)
 *    run_shell, state "no"               -> no  (it never ran)
 *    now, no result (old history)        -> no */
function hasOutput(t: Tool): boolean {
  if (t.state === "no") return false;
  return outputHead(t.result ?? "").head !== "";
}

/** The tick, or a spinner while the step runs or waits for your tap, or a cross when you said no. */
function StepMark({ t, spinning }: { t: Tool; spinning: boolean }) {
  if (spinning) {
    const waiting = t.state === "wait";
    return <span role="img" aria-label={waiting ? "Waiting" : "Running"} className="size-3.5 shrink-0 rounded-full border-[1.5px] border-line-2 border-t-ink-2 animate-spin" />;
  }
  const refused = t.state === "no";
  const tone = refused ? "bg-bad-tint text-bad" : "bg-good-tint text-good";
  return <span className={`grid size-3.5 shrink-0 place-items-center rounded-full ${tone}`}><Icon name={refused ? "x" : "check"} size={9} stroke={3.2} /></span>;
}

/** One step of the opened trace, as a receipt: what it was, who let it run, what it was asked, and (on a tap) what it
 * printed. Old history knows only the name, so then it is the label alone. */
function StepRow({ t, spinning, delay }: { t: Tool; spinning: boolean; delay: number }) {
  const [argWhole, setArgWhole] = useState(false);
  const [outOpen, setOutOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const arg = argLine(t);
  const meta = metaLine(t);
  const pill = allowedPill(t);
  const openable = hasOutput(t);
  const result = t.result ?? "";
  const { head, rest } = outputHead(result);
  const whole = outputHead(result, Number.POSITIVE_INFINITY).head;
  const total = whole.split("\n").length;
  const shown = showAll ? whole : head;
  const mono = t.name === "run_shell";
  const toggleOutput = () => setOutOpen(!outOpen);

  const headline = (
    <>
      <StepMark t={t} spinning={spinning} />
      <span className={`min-w-0 truncate font-semibold ${t.state === "no" ? "text-muted" : "text-ink"}`}>{toolLabel(t)}</span>
      {pill && <span className={`ml-auto shrink-0 rounded-full px-[7px] py-[2px] text-[10.5px] font-semibold whitespace-nowrap ${pillTone(t)}`}>{pill}</span>}
    </>
  );
  const headClass = "flex min-h-7 items-center gap-2 text-left text-[13px]";
  return (
    <div data-step className="trace-row flex flex-col gap-[3px] py-1" style={{ animationDelay: `${delay}ms` }}>
      {openable
        ? <button type="button" aria-expanded={outOpen} onClick={toggleOutput} className={`${headClass} w-full transition-opacity active:opacity-60`}>{headline}</button>
        : <div className={`${headClass} w-full`}>{headline}</div>}
      {arg && (
        <button type="button" data-arg aria-expanded={argWhole} onClick={() => setArgWhole(!argWhole)}
          className="block w-full rounded-[8px] bg-well px-2 py-[5px] text-left text-[12px] leading-[1.45] text-ink-2">
          {/* the font sits on the span: the app's own rule gives every button the body font */}
          <span className={`block ${mono ? "font-mono" : ""} ${argWhole ? "whitespace-pre-wrap break-all" : "truncate"}`}>{arg}</span>
        </button>
      )}
      {meta && !outOpen && (openable
        ? <button type="button" onClick={toggleOutput} className="w-fit text-left text-[11.5px] text-muted transition-opacity active:opacity-60">{meta}</button>
        : <span className="text-[11.5px] text-muted">{meta}</span>)}
      {outOpen && (
        <div className="trace-row rounded-[10px] border border-line bg-surface-2 px-[9px] py-[7px]">
          <pre className="m-0 overflow-x-auto font-mono text-[11.5px] leading-[1.5] text-ink-2">{shown}</pre>
          {!showAll && rest > 0 && (
            <button type="button" onClick={() => setShowAll(true)} className="mt-1 block text-[12px] font-semibold text-ember-text">Show all {total} lines</button>
          )}
        </div>
      )}
    </div>
  );
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
            <div className="flex flex-col py-1">
              {tools.map((t, i) => (
                <StepRow key={t.id ?? i} t={t} spinning={(running && !t.done) || t.state === "wait"} delay={Math.min(i, 6) * 60} />
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
