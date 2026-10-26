// What a form becomes when the user presses Send: one message with two parts. First a line the bubble shows
// ("Where: Beach · Pace: Easy"), then an ```odie-form-answer fence the model reads by field id. A bubble shows only the
// line (withoutFormAnswers); a reply's form finds its answer again in the fence (readFormAnswers).
import { formatWithUnit } from "./fenceValues";
import type { FormBlock, FormField } from "./parse/form";

export type FormValue = string | string[] | number | null;
export type FormValues = Record<string, FormValue>;
export type FormAnswer = { form: string; values: FormValues };

const FENCE = "odie-form-answer";
const ANSWER_FENCE = /\n*```odie-form-answer\n([\s\S]*?)\n```/g;

/** The values a form starts with: the model's prefilled guesses, else blank (null for a dropdown or radio nobody has
 *  picked, [] for checkboxes, "" for text, the slider's own value). */
export function startingValues(form: FormBlock): FormValues {
  const values: FormValues = {};
  for (const f of form.fields) {
    if (f.kind === "checkbox") values[f.id] = [...f.value];
    else if (f.kind === "slider") values[f.id] = f.value;
    else if (f.kind === "text") values[f.id] = f.value ?? "";
    else values[f.id] = f.value ?? null;
  }
  return values;
}

/** Whether a field has an answer: text with something besides spaces, a picked option, at least one ticked box; a
 *  slider always has one. "Asha" → yes; "  " → no; null → no; [] → no; ["Music"] → yes; 40 → yes */
export function hasValue(value: FormValue | undefined): boolean {
  if (typeof value === "number") return true;
  if (Array.isArray(value)) return value.length > 0;
  return typeof value === "string" && value.trim() !== "";
}

/** Whether Send may be pressed: the form isn't sent yet, no reply is streaming, and every required field has a value
 *  (hasValue). A required name left blank → no; all filled while a reply streams → no; all filled, not sent → yes. */
export function canSend(form: FormBlock, values: FormValues, busy: boolean, sent: boolean): boolean {
  if (busy || sent) return false;
  return form.fields.every((f) => !f.required || hasValue(values[f.id]));
}

/** A field's answer as words: an option's label for its value, ticked boxes joined by ", ", a slider with its unit,
 *  text as typed; "" when blank. */
function spoken(field: FormField, value: FormValue | undefined): string {
  if (!hasValue(value ?? null)) return "";
  if (field.kind === "slider") return formatWithUnit(value as number, field.unit);
  if (field.kind === "text") return String(value).trim();
  const labelOf = (v: string) => field.options.find((o) => o.value === v)?.label ?? v;
  if (field.kind === "checkbox") return (value as string[]).map(labelOf).join(", ");
  return labelOf(String(value));
}

/**
 * The line the bubble shows, in field order: "Label: value" joined by " · ", blank fields left out, the fields of one
 * group as "Group: Label → value, Label → value".
 *   Cast group (Narrator, The keeper), Length radio, empty notes
 *   → "Cast: Narrator → Fairy Godmother, The keeper → Old Mortlake · Length: 3 min"
 */
export function humanLine(form: FormBlock, values: FormValues): string {
  const parts: string[] = [];
  let i = 0;
  while (i < form.fields.length) {
    const group = form.fields[i].group;
    if (!group) {
      const words = spoken(form.fields[i], values[form.fields[i].id]);
      if (words) parts.push(`${form.fields[i].label}: ${words}`);
      i += 1;
      continue;
    }
    const inGroup: string[] = [];
    while (i < form.fields.length && form.fields[i].group === group) {
      const words = spoken(form.fields[i], values[form.fields[i].id]);
      if (words) inGroup.push(`${form.fields[i].label} → ${words}`);
      i += 1;
    }
    if (inGroup.length) parts.push(`${group}: ${inGroup.join(", ")}`);
  }
  return parts.join(" · ") || "Sent the form with nothing filled in.";
}

/** The answer as the model reads it: the form's id and every field's value by id. */
export function answerOf(form: FormBlock, values: FormValues): FormAnswer {
  const byId: FormValues = {};
  for (const f of form.fields) byId[f.id] = values[f.id] ?? null;
  return { form: form.id, values: byId };
}

/** The whole message Send sends: the line, then the answer fence. */
export function answerMessage(form: FormBlock, values: FormValues): string {
  return `${humanLine(form, values)}\n\n\`\`\`${FENCE}\n${JSON.stringify(answerOf(form, values))}\n\`\`\``;
}

/** A user message as its bubble shows it: without any odie-form-answer fence. "Where: Beach\n\n```odie-form-answer\n{…}\n```"
 *  → "Where: Beach";  "Just words." → as it is. */
export function withoutFormAnswers(text: string): string {
  return text.replace(ANSWER_FENCE, "").trim();
}

/** The form answers a user message carries; a fence that isn't a readable answer is skipped.
 *  "Where: Beach\n\n```odie-form-answer\n{"form": "trip", "values": {"where": "b"}}\n```" → [{form: "trip", values: {where: "b"}}] */
export function readFormAnswers(text: string): FormAnswer[] {
  const found: FormAnswer[] = [];
  for (const m of text.matchAll(ANSWER_FENCE)) {
    try {
      const data = JSON.parse(m[1]);
      const isAnswer = data && typeof data.form === "string" && data.values && typeof data.values === "object" && !Array.isArray(data.values);
      if (isAnswer) found.push({ form: data.form, values: data.values });
    } catch {
      // not an answer: left out
    }
  }
  return found;
}

/** "HH:MM" for a time in milliseconds, on this device's clock: 15:42 → "15:42"; 9:05 → "09:05". */
export function sentTime(at: number): string {
  const d = new Date(at);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
