import { clean, keepFirst, num, str, type Trail } from "./fields";

export type Step = { label: string; at: number };
export type ProgressBlock = { type: "progress"; title: string; value: number; goal: number; unit?: string; steps: Step[] };

/**
 * progress: how far value is towards goal, with up to 6 checkpoints sorted by where they sit.
 *   {type: "progress", title: "Level 4", value: 95, goal: 120, steps: [{label: "90 XP", at: 90}, {label: "30 XP", at: 30}, {label: "bad"}]}
 *   → {type: "progress", title: "Level 4", value: 95, goal: 120, steps: [{label: "30 XP", at: 30}, {label: "90 XP", at: 90}]}
 * Dropped: no title, no numeric value, or a goal that isn't above 0.
 */
export function readProgress(raw: any, here: Trail): ProgressBlock | null {
  const title = str(raw.title, 40);
  if (!title) return here.drop("progress needs a title");
  if (num(raw.value) === null) return here.drop("progress needs a numeric value");
  const goal = num(raw.goal);
  if (goal === null || goal <= 0) return here.drop("progress needs a goal above 0");

  const steps: Step[] = [];
  const rawSteps = Array.isArray(raw.steps) ? raw.steps : [];
  rawSteps.forEach((st: any, i: number) => {
    if (!st || !str(st.label) || num(st.at) === null) {
      here.at("steps").at(i).drop("checkpoint needs a label and a number `at`");
      return;
    }
    steps.push({ label: str(st.label, 28)!, at: st.at });
  });
  steps.sort((a, b) => a.at - b.at);
  return clean({ type: "progress" as const, title, value: raw.value, goal, unit: str(raw.unit, 12), steps: keepFirst(steps, 6, here, "checkpoints") });
}
