import { useEffect, useState } from "react";
import { previewUrl } from "../voiceSettings";
import type { FormBlock, FormField, FormOption } from "./parse/form";

/** The voices of the engine chosen in Settings, as /api/voice lists them: what a form's voice options are matched to. */
export type VoiceList = { engine: string; voices: { id: string; label: string }[] };

/** The chosen engine's voices from /api/voice's answer; null when it names no engine it lists, or isn't an answer.
 *  {engine: "phonon", engines: [{id: "kokoro", …}, {id: "phonon", voices: [Hugh]}]} → {engine: "phonon", voices: [Hugh]};
 *  {engine: "gone", engines: []} → null */
export function voiceListFrom(answer: unknown): VoiceList | null {
  if (!answer || typeof answer !== "object") return null;
  const { engine, engines } = answer as { engine?: unknown; engines?: unknown };
  if (typeof engine !== "string" || !Array.isArray(engines)) return null;
  const chosen = engines.find((e) => e && e.id === engine);
  if (!chosen || !Array.isArray(chosen.voices)) return null;
  const voices = chosen.voices
    .filter((v: any) => v && typeof v.id === "string")
    .map((v: any) => ({ id: v.id as string, label: labelOf(v) }));
  return { engine, voices };
}

/** A listed voice's label, or its id when it has none: {id: "af_heart", label: "Heart"} → "Heart"; {id: "Hugh"} → "Hugh". */
function labelOf(voice: { id: string; label?: unknown }): string {
  if (typeof voice.label === "string") return voice.label;
  return voice.id;
}

/** The voice an option names, by its value or its label, matched to a voice's id or label without minding case;
 *  undefined when it names none. "Hugh" → Hugh; "heart" on Kokoro → af_heart (its label is "Heart"); "Horror" → none. */
function voiceOf(option: FormOption, list: VoiceList): { id: string } | undefined {
  const names = [option.value, option.label].map((n) => n.toLowerCase());
  return list.voices.find((v) => names.includes(v.id.toLowerCase()) || names.includes(v.label.toLowerCase()));
}

function filledField(field: FormField, list: VoiceList): FormField {
  if (field.kind !== "select" && field.kind !== "radio") return field;
  const options = field.options.map((option) => {
    if (option.preview) return option;
    const voice = voiceOf(option, list);
    if (!voice) return option;
    return { ...option, preview: previewUrl(list.engine, voice.id) };
  });
  return { ...field, options };
}

/** Decides which options of a form get a ▶: a select or radio option that names a voice of the chosen engine (by
 *  id or label) and has no preview gets that voice's, so a cast form plays its voices even when the model rewrote
 *  the options and dropped the previews a tool gave it. An option's own preview stays; anything that isn't a
 *  voice ("Horror"), checkboxes, text and sliders are left as they are; no voice list → the form as it is.
 *  Phonon, a select ["Hugh", "Nobody"] → Hugh gets "/api/voice/preview/phonon/Hugh", Nobody nothing. */
export function withVoicePreviews(form: FormBlock, list: VoiceList | null): FormBlock {
  if (!list || !list.voices.length) return form;
  return { ...form, fields: form.fields.map((field) => filledField(field, list)) };
}

/** Whether a form has a select or radio option without a preview, the only kind withVoicePreviews can change:
 *  a genre radio → yes (asked once a page, then known); a form of text and sliders → no (Odie isn't asked). */
function mayNameVoices(form: FormBlock): boolean {
  return form.fields.some((f) => (f.kind === "select" || f.kind === "radio") && f.options.some((o) => !o.preview));
}

let asked: Promise<VoiceList | null> | null = null;

/** The chosen engine's voices, asked of Odie once a page; a failed ask (offline, an old server) is asked again next
 *  time. */
function loadVoiceList(): Promise<VoiceList | null> {
  if (!asked) {
    asked = askVoices().then((list) => {
      if (!list) asked = null;
      return list;
    });
  }
  return asked;
}

async function askVoices(): Promise<VoiceList | null> {
  try {
    const answer = await fetch("/api/voice");
    if (!answer.ok) return null;
    return voiceListFrom(await answer.json());
  } catch {
    return null;
  }
}

/** For tests: forget the voices asked for. */
export function resetVoiceList() {
  asked = null;
}

/** The form with its voice options' previews filled in (withVoicePreviews), once Odie has said which voices the
 *  chosen engine has; the form as it is until then. */
export function useVoicePreviews(form: FormBlock): FormBlock {
  const [list, setList] = useState<VoiceList | null>(null);
  const wanted = mayNameVoices(form);
  useEffect(() => {
    if (!wanted) return;
    let live = true;
    void loadVoiceList().then((found) => { if (live) setList(found); });
    return () => { live = false; };
  }, [wanted]);
  return withVoicePreviews(form, list);
}
