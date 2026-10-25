import type { MacApps } from "./mac";
/** Onboarding: the checklist, and what each piece of the Setup screen needs to know. */
export const STEPS = ["brain", "names", "vault", "embeddings", "photos", "search", "voice", "apps", "phone"] as const;
export type Step = (typeof STEPS)[number];
export type Line = { role: "user" | "assistant"; text: string; note?: boolean };
export type KeyCard = { type: "key"; provider: string; kind: "provider" | "search"; label: string; note: string };
export type AppCard = { type: "app"; app: string; label: string; where: string; key_label: string; steps?: string[] };
export type Card = KeyCard | AppCard;
/** A server somewhere else: the kinds it can be, each with an example address. */
export type ServerCard = { type: "server"; kinds: { id: string; label: string; example: string }[] };
export type Choice = { id: string; label: string; note: string; recommended: boolean; needs: Card | { type: "path" } | ServerCard | null; value?: unknown };
export type Phone = { tailscale: boolean; serving: boolean; address: string; pairing: boolean; download: string; serve_command: string; steps: string[] };
/** The current step as the screen shows it: Odie's question (already in the thread), what it is, and its controls. */
export type Panel = {
  step: Step; label: string; question: string; explain: string; choices: Choice[]; skip: string | null;
  fields: { id: string; label: string; value: string }[]; phone: Phone | null;
  mac_apps?: MacApps | null;  // the apps step on a Mac: the Mac's own apps, allowed right here
};
export type SetupState = { done: boolean; can_leave?: boolean; current: Step | null; steps: Record<Step, "todo" | "done" | "skipped">; thread: Line[]; panel?: Panel | null };
export type Turn = { reply: string; cards: Card[]; state: SetupState; panel?: Panel | null; error?: string };

export const LABEL: Record<Step, string> = {
  brain: "Brain", names: "Names", vault: "Notes", embeddings: "Smart search", photos: "Photos", search: "Web search", voice: "Voice", apps: "Apps", phone: "Phone",
};
// Where each step is done by hand.
export const BY_HAND: Partial<Record<Step, string>> = {
  brain: "#brain", vault: "#settings", embeddings: "#settings", photos: "#settings", search: "#settings", voice: "#settings", apps: "#settings", phone: "#settings",
};

export function chipState(step: Step, s: SetupState): "done" | "skipped" | "current" | "todo" {
  const st = s.steps[step];
  if (st !== "todo") return st;
  return s.current === step ? "current" : "todo";
}

export function keyRoute(card: KeyCard): string {
  return card.kind === "search" ? `/api/search/${card.provider}/key` : `/api/providers/${card.provider}/key`;
}

export function brainDone(report: { verdict: string } | undefined): boolean {
  return !!report && report.verdict !== "fail";
}

/** What a choice needs before it can be saved: a key form, an app form, a folder path, a server's address and model,
 * or nothing (Continue saves it). */
export function formFor(choice: Choice | undefined): "key" | "app" | "path" | "server" | null {
  return (choice?.needs?.type as "key" | "app" | "path" | "server" | undefined) ?? null;
}

/** The choice picked when a step opens: the recommended one, else the first. */
export function firstPick(panel: Panel): string {
  return (panel.choices.find((c) => c.recommended) ?? panel.choices[0])?.id ?? "";
}

export function canSkip(step: Step): boolean {
  return step !== "brain" && step !== "names";
}

/** The conversation as shown: Odie's own notes (a key was saved, a step skipped) are for the model only. */
export function visibleThread(thread: Line[]): Line[] {
  return thread.filter((m) => !m.note);
}

type ProviderModels = { id: string; name: string; local: boolean; error: string | null; models: { id: string; local: boolean }[] };

/** The brain step's list: local models first, at most `per` from each provider unless a search narrows it. */
export function modelRows<P extends ProviderModels>(providers: P[], query: string, per: number): { p: P; m: P["models"][number] }[] {
  const q = query.trim().toLowerCase();
  const rows = providers.flatMap((p) => {
    const ms = p.models.filter((m) => !q || m.id.toLowerCase().includes(q));
    return (q ? ms : ms.slice(0, per)).map((m) => ({ p, m }));
  });
  return rows.sort((a, b) => Number(b.m.local) - Number(a.m.local));
}
