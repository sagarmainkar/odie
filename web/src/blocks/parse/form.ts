import { niceStep } from "./calculator";
import { clean, firstList, firstText, firstTextOrNumber, keepFirst, num, type Trail } from "./fields";

export type FormOption = { value: string; label: string; note?: string; preview?: string };
type FieldBase = { id: string; label: string; group?: string; required: boolean };
export type ChoiceField = FieldBase & { kind: "select" | "radio"; options: FormOption[]; value?: string };
export type CheckboxField = FieldBase & { kind: "checkbox"; options: FormOption[]; value: string[] };
export type TextField = FieldBase & { kind: "text"; placeholder?: string; multiline: boolean; value?: string };
export type SliderField = FieldBase & { kind: "slider"; min: number; max: number; step: number; value: number; unit?: string; ends?: [string, string] };
export type FormField = ChoiceField | CheckboxField | TextField | SliderField;
/** path: where the form sits in its fence ("0"), so its answered state can be saved and found again. */
export type FormBlock = { type: "form"; id: string; title?: string; submit: string; fields: FormField[]; path: string };

export const MAX_FIELDS = 12;
export const MAX_OPTIONS = 60;  // a voice list is about 40
const LABEL = 100;  // models write labels as questions: "Anything to slip in? (her pet's name, a toy)"
const NOTE = 80;
export const TEXT_VALUE = 500;
const PREVIEW_PREFIX = "/api/voice/preview/";
const KINDS = ["select", "radio", "checkbox", "text", "slider"] as const;
type Kind = (typeof KINDS)[number];
// The names models also write for a kind, and what they mean.
const KIND_NAMES: Record<string, Kind> = {
  select: "select", dropdown: "select", radio: "radio", choice: "radio",
  checkbox: "checkbox", checkboxes: "checkbox", multi: "checkbox", multiselect: "checkbox",
  text: "text", input: "text", textarea: "text", slider: "slider", range: "slider",
};

/**
 * form: a small form the user fills in and sends; its answer comes back as a message, by field id.
 * - id: what the answer carries, so the model knows which form it is (missing: from the title, else "form-1").
 * - title, submit (the button's words, default "Send").
 * - fields, up to 12: {id, kind (also `type`), label, value (the model's best guess), group (a heading shared by the
 *   fields after it), required}. Kinds: select (also `dropdown`), radio, checkbox (also `checkboxes`; value is a
 *   list), text (also `textarea`, which is multiline), slider (also `range`). select, radio and checkbox take
 *   options, up to 60: text, or {value, label, note, preview}. A slider takes min, max, step, unit and ends
 *   [low word, high word].
 *   {type: "form", title: "Plan it", fields: [{id: "where", type: "dropdown", label: "Where", value: "Hills", options: ["Hills", "Beach"]}]}
 *   → {type: "form", id: "plan-it", title: "Plan it", submit: "Send", path: "0",
 *      fields: [{id: "where", kind: "select", label: "Where", required: false, value: "Hills",
 *                options: [{value: "Hills", label: "Hills"}, {value: "Beach", label: "Beach"}]}]}
 * Dropped: a field with an unknown kind, no id or a repeated id (each with a note); the whole form when no field is
 * left.
 */
export function readForm(raw: any, here: Trail): FormBlock | null {
  const rawFields = firstList([raw.fields, raw.inputs, raw.questions]);
  if (!rawFields) return here.drop("form needs fields");
  const fields: FormField[] = [];
  rawFields.forEach((item, i) => {
    const where = here.at("fields").at(i);
    const field = readField(item, where);
    if (!field) return;
    if (fields.some((f) => f.id === field.id)) {
      where.drop(`field id "${field.id}" is used twice`);
      return;
    }
    fields.push(field);
  });
  if (!fields.length) return here.drop("form has no usable field");
  const title = firstText([raw.title, raw.label], 80);
  const id = formIdFrom(firstText([raw.id, raw.name], 60), title);
  const submit = firstText([raw.submit, raw.button], 24) ?? "Send";
  return clean({ type: "form" as const, id, title, submit, fields: keepFirst(fields, MAX_FIELDS, here, "fields"), path: here.path });
}

/** The form's id: the model's own, else its title as a slug, else "form-1".
 *  ("trip", "Plan the weekend") → "trip";  (none, "Plan the weekend!") → "plan-the-weekend";  (none, none) → "form-1" */
export function formIdFrom(id: string | undefined, title: string | undefined): string {
  if (id) return id;
  const slug = (title ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
  if (slug) return slug;
  return "form-1";
}

/** A preview the app may play: only a path to Odie's own voice previews, on this server, that doesn't climb out of it.
 *  "/api/voice/preview/phonon/Fairy%20Godmother" → kept;  "https://evil.example/a.mp3" → undefined;
 *  "/api/voice/preview/../../x" → undefined;  42 → undefined */
export function previewPath(v: unknown): string | undefined {
  if (typeof v !== "string" || !v.startsWith(PREVIEW_PREFIX) || v.includes("\\")) return undefined;
  let decoded: string;
  try {
    decoded = decodeURIComponent(v);
  } catch {
    return undefined;
  }
  const climbsOut = decoded.split("/").includes("..");
  if (climbsOut) return undefined;
  return v.slice(0, 300);
}

/** A label at most LABEL characters: whole when it fits, else cut at the last word that fits, with "…" (a single long
 *  word is cut where it must). "Length" → "Length"; a 120-character question → its first ~99 characters up to a word, "…". */
export function shortLabel(text: string, max = LABEL): string {
  if (text.length <= max) return text;
  const room = text.slice(0, max - 1);
  const lastSpace = room.lastIndexOf(" ");
  const atWord = lastSpace > max / 2 ? room.slice(0, lastSpace) : room;
  return `${atWord.trimEnd()}…`;
}

/** The first label-ish text of several fields, shortened by shortLabel; undefined when none is text. */
function labelFrom(values: unknown[]): string | undefined {
  const whole = firstText(values, 400);
  if (whole === undefined) return undefined;
  return shortLabel(whole);
}

/** One field of the form; null (with a note) when its kind is unknown, it has no id, or it can't be used.
 *  {kind: "dropdown", id: "who", options: ["Me", "Us"]} → a select field; {kind: "date", id: "d"} → null, "field kind
 *  \"date\" isn't one of …"; {kind: "radio", id: "x", options: []} → null, "radio needs options". */
function readField(item: any, here: Trail): FormField | null {
  if (!item || typeof item !== "object") return here.drop("field is not an object");
  const named = String(item.kind ?? item.type ?? "").trim().toLowerCase();
  const kind = KIND_NAMES[named];
  if (!kind) return here.drop(`field kind "${named}" isn't one of ${KINDS.join(", ")}`);
  const id = firstText([item.id, item.name, item.key], 40);
  if (!id) return here.drop("field needs an id");
  const label = labelFrom([item.label, item.title]) ?? id;
  const group = labelFrom([item.group, item.section]);
  const base = clean({ id, label, group, required: item.required === true });
  if (kind === "text") return readText(item, named, base);
  if (kind === "slider") return readSlider(item, base, here);
  const options = readOptions(firstList([item.options, item.choices]) ?? [], here);
  if (!options.length) return here.drop(`${kind} needs options`);
  const values = options.map((o) => o.value);
  if (kind === "checkbox") {
    const given = prefilledList(item.value);
    const ticked = given.map((v: unknown) => String(v)).filter((v: string) => values.includes(v));
    return { ...base, kind, options, value: [...new Set(ticked)] as string[] };
  }
  const given = firstTextOrNumber([item.value, item.default]);
  const value = given !== undefined && values.includes(given) ? given : undefined;  // not an option: nothing preselected
  return clean({ ...base, kind, options, value });
}

/** A checkbox field's prefilled value as a list: a list as it is, one value as a list of one, nothing as [].
 *  ["Music", "Sea sounds"] → the same; "Music" → ["Music"]; undefined → [] */
function prefilledList(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (value === undefined) return [];
  return [value];
}

/** The options of a select, radio or checkbox: text (or a number), or {value, label, note, preview}; the first of a
 *  repeated value is kept, and at most 60.  ["1 min", {value: "3", label: "3 min", note: "a story"}]
 *  → [{value: "1 min", label: "1 min"}, {value: "3", label: "3 min", note: "a story"}] */
function readOptions(list: unknown[], here: Trail): FormOption[] {
  const options: FormOption[] = [];
  for (const o of list as any[]) {
    const isObject = !!o && typeof o === "object";
    const value = isObject ? firstTextOrNumber([o.value, o.id, o.label], NOTE) : firstTextOrNumber([o], NOTE);
    if (value === undefined || options.some((x) => x.value === value)) continue;
    let label = isObject ? labelFrom([o.label, o.name]) : undefined;
    if (label === undefined) label = shortLabel(value);
    const note = isObject ? firstText([o.note, o.description], NOTE) : undefined;
    const preview = isObject ? previewPath(o.preview) : undefined;
    options.push(clean({ value, label, note, preview }));
  }
  return keepFirst(options, MAX_OPTIONS, here, "options");
}

function readText(item: any, named: string, base: FieldBase): TextField {
  const placeholder = firstText([item.placeholder, item.hint], NOTE);
  const multiline = item.multiline === true || named === "textarea";
  const value = firstText([item.value, item.default], TEXT_VALUE);
  return clean({ ...base, kind: "text" as const, placeholder, multiline, value });
}

/** A slider; null (with a note) when its min isn't below its max. Its value is kept in range and put on its step.
 *  {min: 0, max: 100, step: 10, value: 43} → value 40; {min: 5, max: 5} → null, "slider needs min below max";
 *  no step, 0 to 1 → a step of 0.01. */
function readSlider(item: any, base: FieldBase, here: Trail): SliderField | null {
  const min = num(item.min) ?? 0;
  const max = num(item.max) ?? 100;
  if (min >= max) return here.drop("slider needs min below max");
  const given = num(item.step);
  const step = given !== null && given > 0 ? given : niceStep((max - min) / 100);
  const value = onStep(num(item.value) ?? num(item.default) ?? min, min, max, step);
  const unit = firstText([item.unit], 12);
  const ends = readEnds(item.ends);
  return clean({ ...base, kind: "slider" as const, min, max, step, value, unit, ends });
}

/** A slider value kept between min and max and moved to the nearest step from min, without float dust.
 *  (43, 0, 100, 10) → 40;  (7, 0, 1, 0.1) → 1;  (12.34, 10, 20, 0.5) → 12.5 */
export function onStep(value: number, min: number, max: number, step: number): number {
  const inRange = Math.min(max, Math.max(min, value));
  const snapped = Math.min(max, min + Math.round((inRange - min) / step) * step);
  const digits = Math.max(decimals(step), decimals(min));
  return Number(snapped.toFixed(digits));
}

function decimals(n: number): number {
  const text = String(n);
  const dot = text.indexOf(".");
  return dot === -1 ? 0 : text.length - dot - 1;
}

/** The words under a slider's two ends: two short texts, else none. ["slow", "quick"] → ["slow", "quick"]; ["slow"] → undefined */
function readEnds(v: unknown): [string, string] | undefined {
  if (!Array.isArray(v) || v.length !== 2) return undefined;
  const low = firstText([v[0]], 20);
  const high = firstText([v[1]], 20);
  if (!low || !high) return undefined;
  return [low, high];
}
